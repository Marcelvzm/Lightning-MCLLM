"""Hot reload: edit YAML on disk, watcher fires, engine swaps show without dropping."""

from __future__ import annotations

import time

import pytest

from lightning_mcllm.engine.reload import HotReloader


def _wait(predicate, timeout=2.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def test_reload_picks_up_new_scene(engine, settings, tmp_data_dir):
    rel = HotReloader(engine, settings, "default", auto_resume=False)
    # Don't start the watcher — drive it manually.
    new_scene = tmp_data_dir / "environments" / "default" / "scenes" / "hot_test.yaml"
    new_scene.write_text("""
name: hot_test
description: created by test
targets:
  - select: { tag: par }
    values: { dimmer: 222, color/red: 100 }
""")
    show, issues = rel.reload_now()
    assert show is not None, issues.errors
    assert "hot_test" in show.scenes
    engine.submit("snap_scene", scene="hot_test")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 222)


def test_reload_with_broken_yaml_keeps_previous_show(engine, settings, tmp_data_dir):
    rel = HotReloader(engine, settings, "default", auto_resume=False)
    bad = tmp_data_dir / "environments" / "default" / "scenes" / "broken.yaml"
    bad.write_text("name: broken\ntargets:\n  - select: bogus_not_a_dict\n")
    show, issues = rel.reload_now()
    # New show failed; engine retains the prior show
    assert show is None
    assert issues.errors
    assert engine.show() is not None
    # Engine still functional
    engine.submit("snap_scene", scene="warm_idle")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 140)


def test_switch_environment(engine, settings, tmp_data_dir):
    """Create a second env, switch to it, verify show changes."""
    rel = HotReloader(engine, settings, "default", auto_resume=False)
    other = tmp_data_dir / "environments" / "alt"
    (other).mkdir()
    (other / "scenes").mkdir()
    (other / "environment.yaml").write_text("""
name: alt
fixtures:
  - { name: only-par, profile: generic_rgbw_par, address: 1, tags: [par, only] }
""")
    (other / "scenes" / "only.yaml").write_text("""
name: only_scene
targets:
  - select: { tag: only }
    values: { dimmer: 77, color/blue: 200 }
""")
    show, issues = rel.switch_environment("alt")
    assert show is not None, issues.errors
    assert show.name == "alt"
    assert "only_scene" in show.scenes
    engine.submit("snap_scene", scene="only_scene")
    assert _wait(lambda: engine.shadow_snapshot()[0] == 77)


def test_auto_resume_reapplies_running_chases(engine, settings, tmp_data_dir):
    rel = HotReloader(engine, settings, "default", auto_resume=True)
    engine.submit("start_chase", chase="red_pulse")
    assert _wait(lambda: any("red_pulse" in k for k in engine.status().active_chases))
    # Touch a scene file (no semantic change) and reload
    scene_file = tmp_data_dir / "environments" / "default" / "scenes" / "warm_idle.yaml"
    scene_file.write_text(scene_file.read_text() + "\n# touched\n")
    show, _ = rel.reload_now()
    assert show is not None
    # auto_resume should restart the chase post-reload
    assert _wait(lambda: any("red_pulse" in k for k in engine.status().active_chases))
