"""End-to-end: Engine + EnttecProInterface + EuroliteSimulator over a PTY.

This is the strongest substitute for hardware. The engine renders frames, the
real Enttec Pro driver writes to a PTY slave, the simulator reconstructs the
universe state and we verify it matches the engine's shadow.
"""

from __future__ import annotations

import time

import pytest

from lightning_mcllm.dmx.enttec_pro import EnttecProInterface
from lightning_mcllm.dmx.simulator import EuroliteSimulator
from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.runtime import Engine


def test_engine_drives_simulator(stage, simulator):
    iface = EnttecProInterface(simulator.slave_path)
    iface.open()
    clock = BpmClock(bpm=120.0)
    eng = Engine(stage=stage, dmx=iface, clock=clock, refresh_hz=30)
    eng.start()
    try:
        eng.submit("snap_scene", scene="warm_idle")
        # Wait for both: engine shadow has settled AND simulator received a frame
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if eng.shadow_snapshot()[0] == 140 and simulator.frames_received >= 1:
                break
            time.sleep(0.02)
        # Simulator state must equal engine shadow
        sim_frame = simulator.snapshot()
        eng_frame = eng.shadow_snapshot()
        assert sim_frame == eng_frame, "simulator universe diverged from engine shadow"
        assert simulator.protocol_errors == 0
    finally:
        eng.stop()
        iface.close()


def test_engine_continues_when_simulator_dies_mid_stream(stage):
    """Engine + driver must not crash when the underlying serial endpoint goes away."""
    sim = EuroliteSimulator()
    sim.start()
    try:
        iface = EnttecProInterface(sim.slave_path, reconnect_delay=0.05)
        iface.open()
        clock = BpmClock(bpm=120.0)
        eng = Engine(stage=stage, dmx=iface, clock=clock, refresh_hz=30)
        eng.start()
        try:
            eng.submit("snap_scene", scene="warm_idle")
            time.sleep(0.3)
            # Yank the simulator
            sim.stop()
            time.sleep(0.5)  # engine keeps trying to write; must not crash
            assert eng.status().running
            # Errors recorded but engine still alive
            # (driver swallows errors; engine doesn't see them — that's the point)
        finally:
            eng.stop()
            iface.close()
    finally:
        if sim._thread:
            sim.stop()
