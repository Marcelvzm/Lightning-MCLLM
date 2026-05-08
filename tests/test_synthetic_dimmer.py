"""Tests for the synthetic_dimmer feature.

Profiles without a real `dimmer` channel (e.g. Involight RX350) can declare
a `synthetic_dimmer:` block telling the engine how to translate dimmer
writes into writes on other channels (effect/macro, color/r, ...).

The contract:
* dimmer < threshold → write each entry of `off_writes` to its target channel
* dimmer >= threshold → no-op (other voices keep painting whatever they want)
* Triggered both via render_scene (Scene targets) and render_inline_values
  (chase action `values:` block)
* Profiles WITH a real dimmer channel ignore synthetic_dimmer (real channel
  wins because role_to_offset returns the offset, not None)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lightning_mcllm.config import Paths, Settings
from lightning_mcllm.core.library import load_fixture_library, load_stage
from lightning_mcllm.core.scenes import Scene


REPO_DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture()
def stolz_stage(tmp_path: Path):
    """Stolz environment loads the RX350 (which declares synthetic_dimmer)."""
    settings = Settings(paths=Paths(REPO_DATA, tmp_path / "runtime"))
    lib, _ = load_fixture_library(settings.paths.fixture_library)
    stage, issues = load_stage(settings.paths.environments / "stolz", lib)
    assert stage is not None, f"failed to load stolz stage: {issues.errors}"
    return stage


def _rx350_macro_key(stage):
    """Channel key (universe, 0-indexed addr) for the RX350's effect/macro
    channel. Address from environment.yaml (39 → 0-indexed 38)."""
    rx = next(f for f in stage.fixtures if f.name == "rx350")
    return (rx.universe, rx.address - 1 + 0)  # offset 0 = effect/macro


def test_synthetic_dimmer_below_threshold_applies_off_writes(stolz_stage):
    """dimmer=0 on rx350 must force effect/macro=0."""
    scene = Scene.model_validate({
        "name": "test_dim_0",
        "targets": [{"select": {"tag": "beam_bar"}, "values": {"dimmer": 0}}],
    })
    rendered = stolz_stage.render_scene(scene)
    assert rendered.values[_rx350_macro_key(stolz_stage)] == 0


def test_synthetic_dimmer_at_threshold_is_noop(stolz_stage):
    """dimmer=1 (== threshold) means no off-write."""
    scene = Scene.model_validate({
        "name": "test_dim_1",
        "targets": [{"select": {"tag": "beam_bar"}, "values": {"dimmer": 1}}],
    })
    rendered = stolz_stage.render_scene(scene)
    # No-op → channel not present in this scene's render output.
    assert _rx350_macro_key(stolz_stage) not in rendered.values


def test_synthetic_dimmer_above_threshold_is_noop(stolz_stage):
    """dimmer=200 must NOT touch the macro channel (existing voice wins)."""
    scene = Scene.model_validate({
        "name": "test_dim_200",
        "targets": [{"select": {"tag": "beam_bar"}, "values": {"dimmer": 200}}],
    })
    rendered = stolz_stage.render_scene(scene)
    assert _rx350_macro_key(stolz_stage) not in rendered.values


def test_synthetic_dimmer_via_inline_values(stolz_stage):
    """Same logic on the chase-style inline path (render_inline_values)."""
    from lightning_mcllm.core.selectors import Selector
    sel = Selector(tag="beam_bar")
    out = stolz_stage.render_inline_values(sel, {"dimmer": 0})
    assert out[_rx350_macro_key(stolz_stage)] == 0
    out2 = stolz_stage.render_inline_values(sel, {"dimmer": 200})
    assert _rx350_macro_key(stolz_stage) not in out2


def test_synthetic_dimmer_does_not_fire_for_real_dimmer_profile(stolz_stage):
    """Cameo HAS a real dimmer channel — synthetic_dimmer must not trigger
    even if the profile declared one (it doesn't, but be defensive)."""
    scene = Scene.model_validate({
        "name": "test_par_dim",
        "targets": [{"select": {"tag": "cameo"}, "values": {"dimmer": 0}}],
    })
    rendered = stolz_stage.render_scene(scene)
    cameo = next(f for f in stolz_stage.fixtures if f.name == "cameo-1")
    cameo_dim_key = (cameo.universe, cameo.address - 1 + 0)
    # The real dimmer channel was set to 0; THAT is the right behaviour.
    assert rendered.values[cameo_dim_key] == 0


def test_synthetic_dimmer_does_not_affect_unrelated_writes(stolz_stage):
    """A scene that writes effect/macro directly without touching dimmer must
    not have any synthetic-dimmer side effects."""
    scene = Scene.model_validate({
        "name": "test_macro_direct",
        "targets": [{"select": {"tag": "beam_bar"}, "values": {"effect/macro": 80}}],
    })
    rendered = stolz_stage.render_scene(scene)
    assert rendered.values[_rx350_macro_key(stolz_stage)] == 80
