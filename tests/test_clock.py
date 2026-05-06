"""BPM clock — manual, tap tempo, monotonic advance."""

from __future__ import annotations

import time

from lightning_mcllm.engine.clock import BpmClock


def test_initial_bpm_advances_beat_position():
    c = BpmClock(bpm=120.0)
    pos0 = c.beat_position
    time.sleep(0.5)
    c.tick()
    assert c.beat_position - pos0 > 0.8  # ~1 beat at 120 BPM in 0.5s


def test_set_bpm_clamps():
    c = BpmClock(bpm=120.0)
    c.set_bpm(10.0)  # below clamp
    assert c.bpm == 20.0
    c.set_bpm(1000.0)
    assert c.bpm == 400.0


def test_pause_freezes_beat_position():
    c = BpmClock(bpm=120.0)
    c.tick()
    pos = c.beat_position
    c.set_running(False)
    time.sleep(0.3)
    c.tick()
    # beat position should not have advanced while paused
    assert c.beat_position == pos


def test_tap_tempo_locks_after_three_taps():
    c = BpmClock(bpm=120.0)
    # Tap at 100 BPM => 0.6s intervals
    interval = 60.0 / 100.0
    c.tap()
    time.sleep(interval)
    c.tap()
    time.sleep(interval)
    c.tap()
    # Should be near 100 BPM (allow ±5)
    assert 95.0 <= c.bpm <= 105.0
    assert c.source == "tap"
