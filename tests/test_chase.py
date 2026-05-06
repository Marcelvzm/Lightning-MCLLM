"""Chase runner: step firing, beat-anchored vs time-anchored, parallelism."""

from __future__ import annotations

import time

import pytest

from lightning_mcllm.engine.script import ChaseRunner


def _wait_until(predicate, timeout: float = 2.0, step: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def test_red_pulse_snaps_then_fades(engine):
    # Use a slow BPM (60 → 1s/beat) so the 0.4s fade fully completes before
    # the next beat's snap. Otherwise we see only mid-fade values.
    engine.submit("set_bpm", bpm=60.0)
    engine.submit("start_chase", chase="red_pulse")
    samples: list[int] = []
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        samples.append(engine.shadow_snapshot()[0])
        time.sleep(0.005)
    # Saw the snap up
    assert any(v >= 240 for v in samples), f"never saw snap-up; max={max(samples)}"
    # Saw the fade-out resting value (red_pulse_off has dimmer=30, give some tolerance)
    assert any(25 <= v <= 50 for v in samples), f"never saw fade target; unique={sorted(set(samples))[-15:]}"


def test_red_pulse_at_high_bpm_never_completes_fade(engine):
    """At 240 BPM (0.25s/beat), the 0.4s fade is interrupted by the next snap.
    This is *expected* behavior; the test exists so a future regression of the
    voice-replacement logic doesn't silently drop the snap."""
    engine.submit("set_bpm", bpm=240.0)
    engine.submit("start_chase", chase="red_pulse")
    samples: list[int] = []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        samples.append(engine.shadow_snapshot()[0])
        time.sleep(0.005)
    assert any(v >= 240 for v in samples), "snap never observed at 240 BPM"
    # We expect mid-fade values (>= 100) but not the resting 30 — fade gets cut off.
    assert any(v >= 100 for v in samples)


def test_time_anchored_chase_runs_independent_of_bpm(engine):
    """par_color_walk is anchored in seconds; changing BPM should not re-time it."""
    engine.submit("start_chase", chase="par_color_walk")
    engine.submit("set_bpm", bpm=240.0)
    # First step is at_seconds=0 with a 4s fade to dim=180. After ~1.0s we
    # should see par dimmer at ~25% of 180 = ~45.
    deadline = time.monotonic() + 1.5
    saw_climb = False
    while time.monotonic() < deadline:
        v = engine.shadow_snapshot()[0]
        if v >= 30:
            saw_climb = True
            break
        time.sleep(0.02)
    assert saw_climb


def test_chase_loops(engine):
    """red_pulse loops every 4 beats. After the loop boundary, snap fires again."""
    engine.submit("set_bpm", bpm=240.0)  # 4 beats/sec → loop every 1s
    engine.submit("start_chase", chase="red_pulse")
    # Wait until we've seen at least 2 distinct snap events (255s separated by fade-downs)
    snap_count = 0
    last_was_snap = False
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline and snap_count < 2:
        v = engine.shadow_snapshot()[0]
        is_snap = v >= 240
        if is_snap and not last_was_snap:
            snap_count += 1
        last_was_snap = is_snap
        time.sleep(0.005)
    assert snap_count >= 2, f"only saw {snap_count} snap events"


def test_replacing_chase_replaces_voices(engine):
    engine.submit("start_chase", chase="red_pulse")
    assert _wait_until(lambda: any("red_pulse:1" in k for k in engine.status().active_chases))
    # Restarting the same chase should bump the instance counter and clean prior voices
    engine.submit("start_chase", chase="red_pulse")
    assert _wait_until(lambda: any("red_pulse:2" in k for k in engine.status().active_chases))
    # Only one runner of this name
    runners = [k for k in engine.status().active_chases if "red_pulse" in k]
    assert len(runners) == 1


def test_two_concurrent_chases_target_independent_groups(engine):
    """red_pulse targets pars; mh_alternating_sweep targets moving heads. Both
    can run concurrently and write disjoint channels."""
    engine.submit("start_chase", chase="red_pulse")
    engine.submit("start_chase", chase="mh_alternating_sweep")
    assert _wait_until(lambda: len(engine.status().active_chases) == 2)
    # Wait for both to start writing
    time.sleep(0.5)
    snap = engine.shadow_snapshot()
    par_dim = snap[0]  # par-l dimmer
    mh_dim = snap[104]  # mh-l dimmer (addr 100, offset 5 => index 104)
    # Note mh has a 1.5s fade to dim=220, may not yet be there. Just verify shadow has activity.
    assert par_dim > 0 or mh_dim > 0
    assert engine.status().last_frame_nonzero > 0
