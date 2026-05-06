"""Verify the Enttec Pro driver against a virtual Eurolite over a PTY pair.

This is the strongest substitute for hardware testing — same `pyserial` code
path used in production, real binary packets on a real (virtual) serial line.
"""

from __future__ import annotations

import time

from lightning_mcllm.dmx.enttec_pro import (
    EnttecProInterface,
    LABEL_SEND_DMX,
    build_send_dmx_packet,
    parse_packet,
)
from lightning_mcllm.dmx.simulator import EuroliteSimulator


def test_packet_round_trip() -> None:
    """Build a packet, parse it, recover original payload."""
    payload = bytes([0x00] + [0xAA, 0x55, 0x10] + [0] * 509)
    packet = build_send_dmx_packet(payload[1:])  # the function adds the start code itself
    parsed = parse_packet(packet)
    assert parsed is not None
    label, decoded_payload = parsed
    assert label == LABEL_SEND_DMX
    assert decoded_payload == payload


def test_simulator_receives_frame_via_serial() -> None:
    """Open a PTY, point EnttecProInterface at it, send a frame, verify
    simulator reconstructs the universe state."""
    sim = EuroliteSimulator()
    sim.start()
    try:
        iface = EnttecProInterface(sim.slave_path, baudrate=57600)
        iface.open()
        assert iface.connected, "interface failed to open virtual serial"

        frame = bytes([(i * 17) & 0xFF for i in range(512)])
        iface.send(0, frame)
        # Give the simulator's reader thread time to consume.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and sim.frames_received < 1:
            time.sleep(0.01)

        assert sim.frames_received >= 1, f"sim got 0 frames; bytes={sim.bytes_received}, errors={sim.protocol_errors}"
        assert sim.protocol_errors == 0, f"protocol errors: {sim.protocol_errors}"
        assert sim.snapshot() == frame, "universe state mismatch"

        iface.close()
    finally:
        sim.stop()


def test_simulator_handles_many_frames() -> None:
    """Stream 200 frames at full tilt; simulator state must converge."""
    sim = EuroliteSimulator()
    sim.start()
    try:
        iface = EnttecProInterface(sim.slave_path)
        iface.open()
        last = b""
        for i in range(200):
            last = bytes([(i + j) & 0xFF for j in range(512)])
            iface.send(0, last)
        # drain
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and sim.frames_received < 200:
            time.sleep(0.01)
        assert sim.frames_received >= 200, f"got {sim.frames_received}/200"
        assert sim.protocol_errors == 0
        assert sim.snapshot() == last, "final universe state mismatch"
        iface.close()
    finally:
        sim.stop()


def test_send_after_disconnect_does_not_raise() -> None:
    """If the simulator goes away mid-stream, the driver must NOT raise — it
    must absorb the failure and try to reconnect. 'Show must go on' from the
    engine's perspective.
    """
    sim = EuroliteSimulator()
    sim.start()
    iface = EnttecProInterface(sim.slave_path, reconnect_delay=0.05)
    iface.open()
    iface.send(0, bytes(512))
    # Now stop the simulator — slave_path becomes invalid
    sim.stop()
    time.sleep(0.05)
    # Multiple sends should silently fail, no exceptions
    for _ in range(5):
        iface.send(0, bytes([42] * 512))  # must not raise
    iface.close()
