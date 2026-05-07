"""Tests for the runtime-parameters mechanism on scenes and chases."""

from __future__ import annotations

import time

import pytest

from lightning_mcllm.core.chases import Chase
from lightning_mcllm.core.parameters import (
    ParameterSpec,
    resolve_args,
    resolve_placeholder,
)
from lightning_mcllm.core.scenes import Scene


# ---------------------------------------------------------------------------
# resolve_args / resolve_placeholder unit tests
# ---------------------------------------------------------------------------


def test_resolve_args_uses_defaults_when_nothing_passed() -> None:
    spec = {"x": ParameterSpec(type="int", default=42)}
    assert resolve_args(spec, None) == {"x": 42}
    assert resolve_args(spec, {}) == {"x": 42}


def test_resolve_args_overrides_defaults() -> None:
    spec = {"x": ParameterSpec(type="int", default=42)}
    assert resolve_args(spec, {"x": 100}) == {"x": 100}


def test_resolve_args_rejects_unknown() -> None:
    spec = {"x": ParameterSpec(type="int", default=42)}
    with pytest.raises(ValueError, match="unknown parameter"):
        resolve_args(spec, {"y": 1})


def test_resolve_args_validates_min_max() -> None:
    spec = {"dim": ParameterSpec(type="int", default=100, min=0, max=255)}
    with pytest.raises(ValueError, match="below min"):
        resolve_args(spec, {"dim": -1})
    with pytest.raises(ValueError, match="above max"):
        resolve_args(spec, {"dim": 300})


def test_resolve_args_coerces_int_from_int_float() -> None:
    spec = {"x": ParameterSpec(type="int", default=0)}
    # 5.0 (float that's whole) coerces to int 5; 5.5 doesn't.
    assert resolve_args(spec, {"x": 5.0}) == {"x": 5}
    with pytest.raises(ValueError):
        resolve_args(spec, {"x": 5.5})


def test_resolve_args_validates_str_options() -> None:
    spec = {"col": ParameterSpec(type="str", default="red", options=["red", "blue"])}
    assert resolve_args(spec, {"col": "blue"}) == {"col": "blue"}
    with pytest.raises(ValueError, match="not in options"):
        resolve_args(spec, {"col": "purple"})


def test_resolve_placeholder_substitutes_dollar_brace() -> None:
    assert resolve_placeholder("${x}", {"x": 42}) == 42


def test_resolve_placeholder_substitutes_dollar_no_brace() -> None:
    assert resolve_placeholder("$x", {"x": 42}) == 42


def test_resolve_placeholder_passthroughs_non_string() -> None:
    assert resolve_placeholder(42, {"x": 1}) == 42
    assert resolve_placeholder(None, {"x": 1}) is None


def test_resolve_placeholder_passthroughs_plain_string() -> None:
    assert resolve_placeholder("plain text", {"x": 1}) == "plain text"


def test_resolve_placeholder_raises_on_undeclared() -> None:
    with pytest.raises(KeyError):
        resolve_placeholder("${unknown}", {"x": 1})


# ---------------------------------------------------------------------------
# Scene with parameters
# ---------------------------------------------------------------------------


def test_scene_accepts_parameter_placeholders_in_values() -> None:
    """A scene YAML with `${param}` in `values:` must parse cleanly."""
    sc = Scene.model_validate(
        {
            "name": "demo",
            "parameters": {"dim": {"type": "int", "default": 100, "min": 0, "max": 255}},
            "targets": [
                {
                    "select": {"tag": "par"},
                    "values": {"dimmer": "${dim}", "color/red": 255},
                }
            ],
        }
    )
    assert sc.parameters["dim"].default == 100
    assert sc.targets[0].values["dimmer"] == "${dim}"
    assert sc.targets[0].values["color/red"] == 255


def test_scene_render_with_default_args(stage) -> None:
    """Render scene with declared params but no caller args → uses defaults."""
    scene = Scene.model_validate(
        {
            "name": "param_demo",
            "parameters": {"d": {"type": "int", "default": 200, "min": 0, "max": 255}},
            "targets": [{"select": {"tag": "par"}, "values": {"dimmer": "${d}"}}],
        }
    )
    rendered = stage.render_scene(scene)
    # par-l in default env is at address 1 (offset 0 = dimmer per generic_rgbw_par)
    par_l_dim = (0, 0)  # address 1 → 0-indexed = 0
    assert rendered.values[par_l_dim] == 200


def test_scene_render_with_arg_override(stage) -> None:
    scene = Scene.model_validate(
        {
            "name": "param_demo",
            "parameters": {"d": {"type": "int", "default": 200, "min": 0, "max": 255}},
            "targets": [{"select": {"tag": "par"}, "values": {"dimmer": "${d}"}}],
        }
    )
    rendered = stage.render_scene(scene, args={"d": 50})
    par_l_dim = (0, 0)
    assert rendered.values[par_l_dim] == 50


def test_scene_render_rejects_unknown_arg(stage) -> None:
    scene = Scene.model_validate(
        {
            "name": "param_demo",
            "parameters": {"d": {"type": "int", "default": 200}},
            "targets": [{"select": {"tag": "par"}, "values": {"dimmer": "${d}"}}],
        }
    )
    with pytest.raises(ValueError, match="unknown parameter"):
        stage.render_scene(scene, args={"foo": 1})


def test_scene_render_rejects_out_of_range_arg(stage) -> None:
    scene = Scene.model_validate(
        {
            "name": "param_demo",
            "parameters": {"d": {"type": "int", "default": 200, "min": 0, "max": 255}},
            "targets": [{"select": {"tag": "par"}, "values": {"dimmer": "${d}"}}],
        }
    )
    with pytest.raises(ValueError, match="above max"):
        stage.render_scene(scene, args={"d": 999})


# ---------------------------------------------------------------------------
# Chase with parameters
# ---------------------------------------------------------------------------


def _make_param_chase() -> Chase:
    return Chase.model_validate(
        {
            "name": "param_chase",
            "parameters": {
                "wheel": {"type": "int", "default": 14, "min": 0, "max": 255},
                "dim": {"type": "int", "default": 100, "min": 0, "max": 255},
                "fade": {"type": "float", "default": 0.5, "min": 0, "max": 10},
            },
            "loop": True,
            "length_beats": 4,
            "steps": [
                {
                    "at_beat": 0,
                    "actions": [
                        {
                            "kind": "snap",
                            "group": {"tag": "par"},
                            "values": {"dimmer": "${dim}", "color/red": "${wheel}"},
                        }
                    ],
                },
                {
                    "at_beat": 2,
                    "actions": [
                        {
                            "kind": "transition",
                            "group": {"tag": "par"},
                            "values": {"dimmer": 0},
                            "fade_seconds": "${fade}",
                        }
                    ],
                },
            ],
        }
    )


def test_chase_parses_with_placeholders() -> None:
    ch = _make_param_chase()
    assert ch.parameters["wheel"].default == 14
    assert ch.parameters["fade"].default == 0.5
    # placeholder strings preserved through pydantic validation
    assert ch.steps[0].actions[0].values["dimmer"] == "${dim}"
    assert ch.steps[1].actions[0].fade_seconds == "${fade}"


def test_chase_default_args_resolve_at_runtime(engine, stage) -> None:
    """ChaseRunner with no override args uses chase parameter defaults."""
    chase = _make_param_chase()
    stage.chases["param_chase"] = chase
    engine.submit("start_chase", chase="param_chase")
    time.sleep(0.15)  # let one tick fire the at_beat=0 action
    status = engine.status()
    assert any("param_chase" in k for k in status.active_chases)


def test_chase_arg_override_propagates_to_voice_targets(stage) -> None:
    """Direct check: ChaseRunner._resolve_targets uses overridden args."""
    from lightning_mcllm.engine.script import ChaseRunner

    chase = _make_param_chase()
    runner = ChaseRunner(
        chase=chase,
        stage=stage,
        instance_id="test:1",
        args={"wheel": 50, "dim": 200},
    )
    # Compile the snap step (at_beat=0 → first action)
    fired = runner._compile_step(chase.steps[0])
    assert len(fired) == 1
    targets = fired[0].targets
    # par-l dimmer at (0, 0), color/red at (0, 1)
    assert targets[(0, 0)] == 200  # ${dim}
    assert targets[(0, 1)] == 50  # ${wheel}


def test_chase_arg_override_on_fade_seconds(stage) -> None:
    from lightning_mcllm.engine.script import ChaseRunner

    chase = _make_param_chase()
    runner = ChaseRunner(
        chase=chase,
        stage=stage,
        instance_id="test:1",
        args={"fade": 3.7},
    )
    fired = runner._compile_step(chase.steps[1])  # transition step
    assert len(fired) == 1
    assert fired[0].duration == pytest.approx(3.7)


def test_chase_unknown_arg_raises_on_construction(stage) -> None:
    from lightning_mcllm.engine.script import ChaseRunner

    chase = _make_param_chase()
    with pytest.raises(ValueError, match="unknown parameter"):
        ChaseRunner(
            chase=chase,
            stage=stage,
            instance_id="test:1",
            args={"nonexistent": 1},
        )


# ---------------------------------------------------------------------------
# Bank slot args
# ---------------------------------------------------------------------------


def test_bank_slot_carries_args() -> None:
    from lightning_mcllm.core.banks import Bank

    bank = Bank.model_validate(
        {
            "name": "test",
            "slots": [
                {
                    "id": 1,
                    "kind": "chase",
                    "name": "some_chase",
                    "label": "with args",
                    "args": {"baseline_wheel": 34},
                }
            ],
        }
    )
    slot = bank.slots[0]
    assert slot.args == {"baseline_wheel": 34}


def test_bank_slot_args_default_to_empty() -> None:
    from lightning_mcllm.core.banks import Bank

    bank = Bank.model_validate(
        {
            "name": "test",
            "slots": [{"id": 1, "kind": "scene", "name": "x"}],
        }
    )
    assert bank.slots[0].args == {}
