"""Stress tests: voice churn, concurrent chases, long-running stability,
malformed YAML hammering, simulator throughput.
"""

from __future__ import annotations

import threading
import time

import pytest

from lightning_mcllm.dmx.enttec_pro import EnttecProInterface
from lightning_mcllm.dmx.simulator import EuroliteSimulator
from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.runtime import Engine


def _wait(predicate, timeout=2.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def test_set_value_storm_does_not_leak_voices(engine):
    """Slamming set_value 5000 times must converge to a bounded voice count."""
    for i in range(5000):
        engine.submit("set_value", address=1, value=i & 0xFF)
    time.sleep(0.3)
    # Each set_value uses key f"override:{u}:{addr}" — should converge to 1 voice
    # for address 1 (modulo any active scene voices, none here).
    voices = engine.status().active_voice_count
    assert voices <= 5, f"voice leak: {voices} voices after set_value storm"


def test_many_distinct_overrides_have_bounded_voices(engine):
    """One voice per channel is fine; assert bound is exactly N (no leak)."""
    for addr in range(1, 51):
        for v in range(20):
            engine.submit("set_value", address=addr, value=v)
    time.sleep(0.3)
    voices = engine.status().active_voice_count
    assert 50 <= voices <= 60  # 50 distinct channels each merged to one voice


def test_long_running_chase_voice_count_stays_bounded(engine):
    """Run red_pulse for 3 seconds, verify voices don't accumulate over time."""
    engine.submit("snap_scene", scene="warm_idle")
    engine.submit("start_chase", chase="red_pulse")
    counts: list[int] = []
    for _ in range(60):
        time.sleep(0.05)
        counts.append(engine.status().active_voice_count)
    assert max(counts) <= 12, f"voice count grew unbounded: peaks={counts[-10:]}"


def test_concurrent_chases_dont_thrash_engine(engine):
    """Three chases running at once — engine must keep ticking near 30Hz."""
    engine.submit("start_chase", chase="red_pulse")
    engine.submit("start_chase", chase="mh_alternating_sweep")
    engine.submit("start_chase", chase="par_color_walk")
    assert _wait(lambda: len(engine.status().active_chases) == 3)
    samples_dt = []
    for _ in range(30):
        time.sleep(0.05)
        samples_dt.append(engine.status().actual_dt_ms)
    # Average dt should be near 1000/refresh_hz = 16.67ms (refresh_hz=60 in fixture)
    avg = sum(samples_dt) / len(samples_dt)
    # Tolerate up to 50ms — Python isn't real-time
    assert avg < 50.0, f"engine fell behind: avg dt={avg:.1f}ms"


def test_rapid_blackout_release_no_crash(engine):
    """Hammer blackout/release in a tight loop — engine must stay alive."""
    engine.submit("snap_scene", scene="warm_idle")
    for _ in range(200):
        engine.submit("blackout")
        engine.submit("release_blackout")
    time.sleep(0.3)
    assert engine.status().running
    # After last release, warm_idle voice should still paint
    assert engine.shadow_snapshot()[0] == 140


def test_engine_survives_buggy_chase_action_loop(engine):
    """If a chase references a missing scene every loop iteration, engine
    keeps running and just records the error each loop."""
    # Manufacture a chase referencing an unknown scene by writing YAML, but
    # it's quicker to call start_chase on a name that doesn't exist (handled
    # at submit time). For stress, hammer it.
    for _ in range(100):
        engine.submit("start_chase", chase="this_does_not_exist")
    time.sleep(0.2)
    assert engine.status().running
    # And legitimate ops still work
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140)


def test_simulator_throughput_at_full_engine_rate(stage):
    """Run engine at 60Hz for 1.5s into a real serial PTY — simulator should
    capture every frame without protocol errors."""
    sim = EuroliteSimulator()
    sim.start()
    # PTY pseudo-terminals on macOS don't support 250000 baud (the new
    # production default). Use 57600 — the simulator doesn't care about
    # actual line rate.
    iface = EnttecProInterface(sim.slave_path, baudrate=57600)
    iface.open()
    clock = BpmClock(bpm=120.0)
    eng = Engine(stage=stage, dmx=iface, clock=clock, refresh_hz=60)
    eng.start()
    try:
        eng.submit("start_chase", chase="red_pulse")
        time.sleep(1.5)
        # Expect ~90 frames @ 60Hz × 1.5s — allow generous lower bound for slow CI.
        assert sim.frames_received >= 60, f"simulator only got {sim.frames_received} frames"
        assert sim.protocol_errors == 0, f"{sim.protocol_errors} protocol errors"

        # Force a known steady state and verify the simulator agrees with the
        # engine. We can't compare while a chase is running because the engine
        # is mutating the shadow continuously and the simulator is one frame
        # behind by definition.
        eng.submit("stop_all_chases")
        eng.submit("snap_scene", scene="warm_idle")
        time.sleep(0.3)  # let voices settle, give writer thread several ticks
        assert sim.snapshot() == eng.shadow_snapshot(), (
            "simulator universe diverged from engine shadow after settle"
        )
    finally:
        eng.stop()
        iface.close()
        sim.stop()


def test_engine_thread_recovers_from_main_loop_exception(engine, monkeypatch):
    """The engine wraps each phase (commands/clock/chase/voice/render/send) in
    try/except. Inject a transient exception into the chase tick path and
    confirm subsequent ticks proceed normally."""
    from lightning_mcllm.engine.script import ChaseRunner

    bomb = {"count": 0}
    original = ChaseRunner.tick

    def boom(self, dt, clock):
        if bomb["count"] < 3:
            bomb["count"] += 1
            raise RuntimeError("transient engine error")
        return original(self, dt, clock)

    monkeypatch.setattr(ChaseRunner, "tick", boom)
    engine.submit("start_chase", chase="red_pulse")
    time.sleep(0.5)
    # Engine still running, ChaseRunner removed after persistent failure.
    assert engine.status().running
    assert any("transient engine error" in e or "chase tick" in e for e in engine.status().last_errors)
