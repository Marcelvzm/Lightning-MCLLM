"""Enttec USB-DMX Pro / Pro MK2 protocol over pyserial.

The Eurolite USB-DMX512 PRO MK2 is FTDI-based and speaks the standard Enttec
USB Pro packet protocol. We implement that directly rather than depending on
DMXEnttecPro / pyenttec — one less moving part, full control of reconnect
behaviour.

Packet format (host -> device, label 6 = Send DMX):

    +------+-------+--------+--------+------+----+----+--------+------+
    | 0x7E | label | len_lo | len_hi | sc=0 | d1 | d2 | ... d512 | 0xE7 |
    +------+-------+--------+--------+------+----+----+--------+------+
        ^      ^      ^         ^       ^                          ^
       SOM   label  length (LE)        DMX                        EOM
                    of payload      start code

`sc` (start code) is 0 for normal DMX. `len = 1 + N` where N is the channel
count (1..512). We always send a full 512-channel frame to keep timing constant
on the wire.

Reconnect: any I/O error closes the port and tries to reopen on the next send.
We never raise upward — DMX must be best-effort from the engine's perspective.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Final

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover — pyserial is a hard dep, but be polite
    serial = None  # type: ignore[assignment]
    list_ports = None  # type: ignore[assignment]

from lightning_mcllm.dmx.interface import UNIVERSE_SIZE, DmxInterface

log = logging.getLogger(__name__)

# Protocol constants
SOM: Final[int] = 0x7E
EOM: Final[int] = 0xE7

LABEL_REPROGRAM_FIRMWARE: Final[int] = 1
LABEL_PROGRAM_FLASH_PAGE: Final[int] = 2
LABEL_GET_WIDGET_PARAMETERS: Final[int] = 3
LABEL_SET_WIDGET_PARAMETERS: Final[int] = 4
LABEL_RECEIVED_DMX: Final[int] = 5
LABEL_SEND_DMX: Final[int] = 6
LABEL_SEND_RDM: Final[int] = 7
LABEL_RECEIVE_DMX_ON_CHANGE: Final[int] = 8
LABEL_GET_SERIAL: Final[int] = 10


def build_send_dmx_packet(channels: bytes) -> bytes:
    """Wrap a DMX universe payload in an Enttec Pro Send-DMX packet.

    `channels` is the raw channel data (1..512 bytes). Start code 0x00 is
    prepended automatically.
    """
    if not (1 <= len(channels) <= 512):
        raise ValueError(f"channel count must be 1..512, got {len(channels)}")
    payload = b"\x00" + channels  # DMX start code byte + channel data
    length = len(payload)
    return bytes([SOM, LABEL_SEND_DMX, length & 0xFF, (length >> 8) & 0xFF]) + payload + bytes([EOM])


def parse_packet(buf: bytes) -> tuple[int, bytes] | None:
    """Best-effort packet parser. Returns (label, payload) or None if `buf` is
    incomplete / malformed. Used by the test simulator, not the driver itself.
    """
    if len(buf) < 5:
        return None
    if buf[0] != SOM:
        return None
    label = buf[1]
    length = buf[2] | (buf[3] << 8)
    if len(buf) < 5 + length:
        return None
    if buf[4 + length] != EOM:
        return None
    return label, bytes(buf[4 : 4 + length])


class EnttecProInterface(DmxInterface):
    """Pyserial-based driver. Auto-reconnect, never raises in send()."""

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 250000,
        write_timeout: float = 0.05,
        reconnect_delay: float = 1.0,
    ):
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        self._port = port
        self._baudrate = baudrate
        self._write_timeout = write_timeout
        self._reconnect_delay = reconnect_delay
        self._lock = threading.Lock()
        self._ser: "serial.Serial | None" = None
        self._last_reconnect = 0.0
        self._consecutive_failures = 0

    @property
    def description(self) -> str:
        return f"enttec_pro({self._port}@{self._baudrate})"

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(self) -> None:
        with self._lock:
            self._ensure_open_locked()

    def _ensure_open_locked(self) -> bool:
        if self._ser is not None and self._ser.is_open:
            return True
        # Backoff between reconnect attempts
        now = time.monotonic()
        if now - self._last_reconnect < self._reconnect_delay:
            return False
        self._last_reconnect = now
        try:
            self._ser = serial.Serial(
                self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.0,
                write_timeout=self._write_timeout,
            )
            log.info("opened DMX port %s @ %d", self._port, self._baudrate)
            self._consecutive_failures = 0
            return True
        except Exception as e:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures < 4 or self._consecutive_failures % 30 == 0:
                log.warning("could not open %s: %s", self._port, e)
            self._ser = None
            return False

    def close(self) -> None:
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ser = None

    def send(self, universe: int, frame: bytes) -> None:
        if len(frame) != UNIVERSE_SIZE:
            raise ValueError(f"frame must be {UNIVERSE_SIZE} bytes, got {len(frame)}")
        # Universe>0 not supported on single-port Enttec Pro. Silently drop —
        # the engine logs a one-time warning elsewhere.
        if universe != 0:
            return
        packet = build_send_dmx_packet(frame)
        with self._lock:
            if not self._ensure_open_locked():
                return
            try:
                assert self._ser is not None
                self._ser.write(packet)
            except Exception as e:  # noqa: BLE001
                log.warning("DMX write failed (%s); will reconnect", e)
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ser = None


def discover_port() -> str | None:
    """Scan available serial ports, return the first that looks like a DMX adapter.

    Heuristics (in order):
      * VID 0x0403 (FTDI) — covers Eurolite, Enttec, generic FTDI USB-DMX
      * Description contains 'DMX', 'Eurolite', or 'Enttec'
    """
    if list_ports is None:
        return None
    candidates: list[tuple[int, str]] = []  # (priority, port)
    for p in list_ports.comports():
        desc = (p.description or "").lower()
        manuf = (p.manufacturer or "").lower()
        prio = 0
        if p.vid == 0x0403:
            prio += 10
        if "ftdi" in desc or "ftdi" in manuf:
            prio += 5
        if any(s in desc + manuf for s in ("dmx", "eurolite", "enttec")):
            prio += 7
        if prio > 0:
            candidates.append((prio, p.device))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
