"""Virtual Eurolite USB-DMX Pro for tests.

We don't have real hardware in this build session, so we substitute one. The
simulator opens a PTY pair: the slave path looks like a real serial device
(`/dev/pts/N`), so the production `EnttecProInterface` can talk to it without
modification. The simulator parses Enttec Pro packets on the master fd and
tracks universe state, frame stats, and protocol errors.

Linux + macOS only (no Windows pty support). That's fine for our test harness.

Usage:

    sim = EuroliteSimulator()
    sim.start()
    iface = EnttecProInterface(sim.slave_path)
    iface.open()
    iface.send(0, frame)
    ...
    sim.stop()
    assert sim.frames_received > 0
    assert sim.universe[0] == frame[0]
"""

from __future__ import annotations

import logging
import os
import pty
import select
import threading
from collections.abc import Callable

from lightning_mcllm.dmx.enttec_pro import EOM, LABEL_SEND_DMX, SOM

log = logging.getLogger(__name__)


class EuroliteSimulator:
    def __init__(self, *, on_frame: Callable[[bytes], None] | None = None):
        self._master_fd: int | None = None
        self._slave_fd: int | None = None
        self._slave_path: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.universe: bytearray = bytearray(512)
        self.frames_received: int = 0
        self.bytes_received: int = 0
        self.protocol_errors: int = 0
        self.last_label: int | None = None
        self._on_frame = on_frame

    @property
    def slave_path(self) -> str:
        if self._slave_path is None:
            raise RuntimeError("simulator not started")
        return self._slave_path

    def start(self) -> None:
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._slave_fd = slave_fd
        self._slave_path = os.ttyname(slave_fd)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="EuroliteSim", daemon=True)
        self._thread.start()
        log.debug("simulator started, slave=%s", self._slave_path)

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        for fd in (self._master_fd, self._slave_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._master_fd = None
        self._slave_fd = None
        self._slave_path = None

    def _run(self) -> None:
        assert self._master_fd is not None
        buf = bytearray()
        # State machine: looking for SOM, then label/length, then payload + EOM
        while not self._stop.is_set():
            try:
                rlist, _, _ = select.select([self._master_fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if not rlist:
                continue
            try:
                chunk = os.read(self._master_fd, 4096)
            except OSError:
                break
            if not chunk:
                continue
            self.bytes_received += len(chunk)
            buf.extend(chunk)
            self._consume(buf)

    def _consume(self, buf: bytearray) -> None:
        while True:
            if not buf:
                return
            # Resync: drop bytes until SOM
            if buf[0] != SOM:
                # Find next SOM, drop everything before
                try:
                    idx = buf.index(SOM)
                except ValueError:
                    self.protocol_errors += 1
                    buf.clear()
                    return
                self.protocol_errors += 1
                del buf[:idx]
                continue
            if len(buf) < 5:
                return  # need more bytes for header
            label = buf[1]
            length = buf[2] | (buf[3] << 8)
            if length > 600:  # sanity: max DMX payload is 1+512=513
                self.protocol_errors += 1
                del buf[0]
                continue
            total = 4 + length + 1
            if len(buf) < total:
                return  # need full payload + EOM
            if buf[4 + length] != EOM:
                self.protocol_errors += 1
                del buf[0]
                continue
            payload = bytes(buf[4 : 4 + length])
            del buf[:total]
            self._handle_packet(label, payload)

    def _handle_packet(self, label: int, payload: bytes) -> None:
        self.last_label = label
        if label == LABEL_SEND_DMX:
            if not payload or payload[0] != 0x00:
                self.protocol_errors += 1
                return
            channels = payload[1:]
            with self._lock:
                # Pad/truncate to 512 just in case
                count = min(len(channels), 512)
                self.universe[:count] = channels[:count]
                # Channels beyond `count` retain previous values (DMX semantics).
                self.frames_received += 1
            if self._on_frame is not None:
                try:
                    self._on_frame(bytes(self.universe))
                except Exception:  # noqa: BLE001
                    log.exception("on_frame callback raised")

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self.universe)
