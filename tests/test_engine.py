"""Engine behavior: voices, scenes, blackout, master, chase lifecycle."""

from __future__ import annotations

import time

import pytest


def _wait_until(predicate, timeout: float = 1.0, step: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def test_snap_scene_paints_channels(engine):
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140, 0.5)
    snap = engine.shadow_snapshot()
    # par-l (addr 1, offset 0..6): dim=140 red=200 green=80 blue=20 white=60
    assert snap[0] == 140
    assert snap[1] == 200
    assert snap[2] == 80
    assert snap[3] == 20
    assert snap[4] == 60
    # par-r (addr 8, offset 0..6): same values
    assert snap[7] == 140
    assert snap[8] == 200


def test_snap_scene_persists(engine):
    """A snap voice must keep painting until replaced (no time-based expiry)."""
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)
    time.sleep(0.5)
    assert engine.shadow_snapshot()[0] == 140


def test_snap_replace_by_newer_scene(engine):
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)
    engine.submit("snap_scene", scene="red_pulse_on")
    # par-l dimmer should jump to 255 (red_pulse_on)
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 255)


def test_blackout_zeros_output_but_preserves_voices(engine):
    engine.submit("snap_scene", scene="warm_idle")
    engine.submit("start_chase", chase="red_pulse")
    assert _wait_until(lambda: engine.status().active_voice_count >= 1)
    engine.submit("blackout")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 0)
    # Chase still active underneath
    assert any("chase:red_pulse" in k for k in engine.status().active_chases)


def test_release_blackout_restores_underlying_state(engine):
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)
    engine.submit("blackout")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 0)
    engine.submit("release_blackout")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)


def test_master_dimmer_scales(engine):
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)
    engine.submit("set_master", value=0.5)
    # 140 * 0.5 = 70, give a small tolerance for rounding
    assert _wait_until(lambda: 65 <= engine.shadow_snapshot()[0] <= 75, 0.5)


def test_stop_chase_drops_its_voices(engine):
    engine.submit("snap_scene", scene="warm_idle")
    engine.submit("start_chase", chase="red_pulse")
    assert _wait_until(lambda: any("chase:red_pulse" in k for k in engine.status().active_chases))
    time.sleep(0.5)  # let it spawn voices
    pre = engine.status().active_voice_count
    assert pre >= 2
    engine.submit("stop_chase", chase="red_pulse")
    # Chase voices removed; warm_idle voice survives.
    assert _wait_until(lambda: engine.status().active_voice_count == 1)
    assert engine.shadow_snapshot()[0] == 140  # warm_idle showing through


def test_stop_all_chases(engine):
    engine.submit("start_chase", chase="red_pulse")
    engine.submit("start_chase", chase="par_color_walk")
    assert _wait_until(lambda: len(engine.status().active_chases) == 2)
    engine.submit("stop_all_chases")
    assert _wait_until(lambda: engine.status().active_chases == [])


def test_unknown_scene_does_not_crash(engine):
    engine.submit("snap_scene", scene="this_scene_does_not_exist")
    time.sleep(0.1)
    assert engine.status().running
    assert any("unknown scene" in e for e in engine.status().last_errors)


def test_unknown_chase_does_not_crash(engine):
    engine.submit("start_chase", chase="ghost_chase")
    time.sleep(0.1)
    assert engine.status().running
    assert any("unknown chase" in e for e in engine.status().last_errors)


def test_set_value_overrides_channel(engine):
    engine.submit("set_value", address=1, value=99)
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 99)


def test_fire_slot_scene(engine):
    engine.submit("fire_slot", bank="starter", slot_id=1)  # warm_idle
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 140)


def test_fire_slot_chase_then_blackout_via_slot(engine):
    engine.submit("fire_slot", bank="starter", slot_id=5)  # red_pulse chase
    assert _wait_until(lambda: any("red_pulse" in k for k in engine.status().active_chases))
    engine.submit("fire_slot", bank="starter", slot_id=9)  # blackout slot
    assert _wait_until(lambda: engine.shadow_snapshot()[0] == 0)
