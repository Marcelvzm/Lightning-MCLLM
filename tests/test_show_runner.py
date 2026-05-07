"""ShowRunner tests — verify each script action and pause/resume/reset."""

from __future__ import annotations

import time

import pytest

from lightning_mcllm.core.shows import Show


def _wait(predicate, timeout: float = 2.0, step: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def _add_show(stage, show: Show) -> None:
    stage.shows[show.name] = show


# ---------------------------------------------------------------------- snap


def test_show_snap_scene_action(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t1",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
        ],
    }))
    engine.submit("play_show", show="t1")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140)


def test_show_wait_seconds(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t2",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.3},
            {"do": "snap_scene", "scene": "red_pulse_on"},
        ],
    }))
    engine.submit("play_show", show="t2")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140, timeout=0.5)
    # During the wait, dimmer is still at warm_idle's 140 (not yet at red 255)
    time.sleep(0.1)
    assert engine.shadow_snapshot()[0] == 140
    # After the wait, dimmer should jump to 255 (red_pulse_on)
    assert _wait(lambda: engine.shadow_snapshot()[0] == 255, timeout=1.0)


def test_show_wait_beats(engine, stage):
    """Beat-based wait completes when beat_position advances enough."""
    engine.submit("set_bpm", bpm=240.0)  # 4 beats/sec → wait 1 beat = 0.25s
    _add_show(stage, Show.model_validate({
        "name": "t3",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "beats": 1},
            {"do": "snap_scene", "scene": "red_pulse_on"},
        ],
    }))
    engine.submit("play_show", show="t3")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 255, timeout=1.0)


# ----------------------------------------------------------- start/stop chase


def test_show_start_chase_then_stop_all(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t4",
        "script": [
            {"do": "start_chase", "chase": "red_pulse"},
            {"do": "wait", "seconds": 0.3},
            {"do": "stop_all_chases"},
        ],
    }))
    engine.submit("play_show", show="t4")
    assert _wait(lambda: any("red_pulse" in k for k in engine.status().active_chases), 1.0)
    assert _wait(lambda: engine.status().active_chases == [], 2.0)


# --------------------------------------------------------------- blackout


def test_show_blackout_and_release(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t5",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.1},
            {"do": "blackout"},
            {"do": "wait", "seconds": 0.1},
            {"do": "release_blackout"},
        ],
    }))
    engine.submit("play_show", show="t5")
    # Show goes through warm_idle → blackout → release
    assert _wait(lambda: engine.shadow_snapshot()[0] == 0, 1.0)
    # release should restore warm_idle
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140, 1.0)


def test_show_blackout_group_only(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t6",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.1},
            {"do": "blackout", "group": {"tag": "par"}, "fade": 0.0},
        ],
    }))
    engine.submit("play_show", show="t6")
    # Wait for warm_idle to actually paint first (shadow starts at 0).
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140, 1.0)
    # Then wait for the par-only blackout to land.
    assert _wait(lambda: engine.shadow_snapshot()[0] == 0, 1.0)
    # MH channels should still hold their warm_idle values — the blackout_group
    # only zeros par channels.
    assert engine.shadow_snapshot()[99] == 128  # mh-l pan


# --------------------------------------------------------------- set_values


def test_show_set_values_group(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t7",
        "script": [
            {"do": "set_values", "group": {"tag": "par"},
             "values": {"dimmer": 99, "color/red": 11}, "fade": 0.0},
        ],
    }))
    engine.submit("play_show", show="t7")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 99 and engine.shadow_snapshot()[1] == 11, 1.0)


# ---------------------------------------------------------------- wait_chase


def test_show_wait_chase_returns_when_chase_loops(engine, stage):
    """wait_chase blocks until the chase wraps once. red_pulse at 60 BPM has
    length 4 beats = 4 seconds; we use a faster BPM to keep the test brief."""
    engine.submit("set_bpm", bpm=480.0)  # 8 beats/sec → 4-beat chase = 0.5s
    _add_show(stage, Show.model_validate({
        "name": "t8",
        "script": [
            {"do": "start_chase", "chase": "red_pulse"},
            {"do": "wait_chase", "chase": "red_pulse"},
            {"do": "blackout"},
        ],
    }))
    engine.submit("play_show", show="t8")
    # Within ~1s, chase should wrap once and blackout should fire
    assert _wait(lambda: engine.status().blackout, timeout=2.5)


# ---------------------------------------------------------------- wait_group


def test_show_wait_group_returns_when_no_voice_active(engine, stage):
    """wait_group with no in-progress voice on the selector returns
    immediately (no transition is happening on par)."""
    _add_show(stage, Show.model_validate({
        "name": "t9",
        "script": [
            {"do": "wait_group", "group": {"tag": "par"}},
            {"do": "snap_scene", "scene": "red_pulse_on"},
        ],
    }))
    engine.submit("play_show", show="t9")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 255, timeout=1.0)


# -------------------------------------------------------------------- loops


def test_show_loop_repeats_n_times(engine, stage):
    """A 3× loop with snap+wait should fire 3 snaps."""
    _add_show(stage, Show.model_validate({
        "name": "t10",
        "script": [
            {"do": "loop",
             "times": 3,
             "actions": [
                 {"do": "snap_scene", "scene": "red_pulse_on"},
                 {"do": "wait", "seconds": 0.05},
                 {"do": "snap_scene", "scene": "red_pulse_off"},
                 {"do": "wait", "seconds": 0.05},
             ]},
        ],
    }))
    engine.submit("play_show", show="t10")
    # Sample dimmer over 0.6s and look for at least 3 distinct on-edges
    samples: list[int] = []
    deadline = time.monotonic() + 0.7
    while time.monotonic() < deadline:
        samples.append(engine.shadow_snapshot()[0])
        time.sleep(0.005)
    on_edges = 0
    last = 0
    for v in samples:
        if v >= 240 and last < 100:
            on_edges += 1
        last = v
    assert on_edges >= 3, f"expected >=3 on-edges, got {on_edges}; samples={set(samples)}"


# -------------------------------------------------------------- pause/resume


def test_show_pause_then_resume(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t11",
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.1},
            {"do": "snap_scene", "scene": "red_pulse_on"},
        ],
    }))
    engine.submit("play_show", show="t11")
    # Wait until first snap has fired but before second
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140, 0.5)
    engine.submit("pause_show")
    time.sleep(0.3)  # well past the 0.1s wait
    # Still at warm_idle because show was paused before second snap
    assert engine.shadow_snapshot()[0] == 140
    engine.submit("resume_show")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 255, 1.0)


def test_show_reset_restarts_from_beginning(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t12",
        "script": [
            {"do": "snap_scene", "scene": "red_pulse_on"},
            {"do": "wait", "seconds": 1.5},
            {"do": "snap_scene", "scene": "warm_idle"},
        ],
    }))
    engine.submit("play_show", show="t12")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 255, 0.5)
    time.sleep(0.2)
    # Reset → script back at start, snaps red again
    engine.submit("reset_show")
    # The red snap should fire immediately on reset
    time.sleep(0.1)
    assert engine.shadow_snapshot()[0] == 255


def test_show_loop_true_restarts_at_end(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t13",
        "loop": True,
        "script": [
            {"do": "snap_scene", "scene": "red_pulse_on"},
            {"do": "wait", "seconds": 0.1},
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.1},
        ],
    }))
    engine.submit("play_show", show="t13")
    # Detect at least 2 transitions back to red_pulse_on
    transitions = 0
    last = -1
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        v = engine.shadow_snapshot()[0]
        if v == 255 and last != 255:
            transitions += 1
        last = v
        time.sleep(0.005)
    assert transitions >= 2, f"loop didn't restart, only saw {transitions} transitions"


# ------------------------------------------------------ stop / play idempotent


def test_show_stop_clears_runner(engine, stage):
    _add_show(stage, Show.model_validate({
        "name": "t14",
        "loop": True,
        "script": [
            {"do": "snap_scene", "scene": "warm_idle"},
            {"do": "wait", "seconds": 0.05},
        ],
    }))
    engine.submit("play_show", show="t14")
    assert _wait(lambda: engine.status().show is not None, 0.5)
    engine.submit("stop_show")
    assert _wait(lambda: engine.status().show is None, 0.5)


def test_unknown_show_fails_gracefully(engine, stage):
    engine.submit("play_show", show="does_not_exist")
    time.sleep(0.1)
    assert engine.status().running
    assert any("unknown show" in e for e in engine.status().last_errors)


def test_keybinding_validation_in_show_yaml(stage):
    """Show YAML with duplicate keys (case-insensitive) should fail."""
    with pytest.raises(Exception):
        Show.model_validate({
            "name": "tdup",
            "keybindings": {
                "a": {"kind": "scene", "name": "warm_idle"},
                "A": {"kind": "scene", "name": "warm_idle"},  # collides
            },
            "script": [],
        })
