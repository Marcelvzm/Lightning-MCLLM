"""Chase model.

A chase is a beat- or second-anchored sequence of action steps. Each step has
an anchor time and a list of actions that fire in parallel at that moment.

Two timing modes:
  * Beat-anchored:    `length_beats` + each step has `at_beat`. Steps are
                      scaled by the BPM clock at runtime.
  * Second-anchored:  `length_seconds` + each step has `at_seconds`. Steps run
                      in real-time regardless of BPM.

Action kinds:
  * `transition` — fade from current channel values to a target over `fade_seconds`.
  * `snap`       — set values immediately (zero-duration transition).
  * `release`    — stop voices on the selector. Channels hold their last value.

Targets can be either a named scene (`scene: warm_idle`) or inline role values
(`values: { color/red: 255 }`).

The chase loops if `loop` is true. On each loop iteration, voices that ran past
the loop boundary continue (they aren't cancelled), but new actions override
them when they target the same group.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lightning_mcllm.core.selectors import Selector


class TransitionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["transition"]
    group: Selector
    scene: str | None = None
    values: dict[str, int] | None = None
    fade_seconds: float = Field(ge=0, default=0.5)
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "linear"

    @model_validator(mode="after")
    def _scene_xor_values(self) -> "TransitionAction":
        if (self.scene is None) == (self.values is None):
            raise ValueError("transition action must specify exactly one of `scene` or `values`")
        return self

    @field_validator("values")
    @classmethod
    def _check_values(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is None:
            return None
        out: dict[str, int] = {}
        for role, val in v.items():
            if not (0 <= val <= 255):
                raise ValueError(f"value for role {role!r} must be 0..255 (got {val})")
            out[role.strip().lower()] = val
        return out


class SnapAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["snap"]
    group: Selector
    scene: str | None = None
    values: dict[str, int] | None = None

    @model_validator(mode="after")
    def _scene_xor_values(self) -> "SnapAction":
        if (self.scene is None) == (self.values is None):
            raise ValueError("snap action must specify exactly one of `scene` or `values`")
        return self


class ReleaseAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["release"]
    group: Selector


Action = TransitionAction | SnapAction | ReleaseAction


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_beat: float | None = None
    at_seconds: float | None = None
    actions: list[Action] = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _exactly_one_anchor(self) -> "Step":
        if (self.at_beat is None) == (self.at_seconds is None):
            raise ValueError("step must specify exactly one of `at_beat` or `at_seconds`")
        return self


class Chase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    loop: bool = True
    length_beats: float | None = Field(default=None, gt=0)
    length_seconds: float | None = Field(default=None, gt=0)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistency(self) -> "Chase":
        if (self.length_beats is None) == (self.length_seconds is None):
            raise ValueError("chase must specify exactly one of `length_beats` or `length_seconds`")
        beat_anchored = self.length_beats is not None
        for i, step in enumerate(self.steps):
            if beat_anchored:
                if step.at_beat is None:
                    raise ValueError(f"chase {self.name!r} is beat-anchored but step {i} uses at_seconds")
                if step.at_beat >= self.length_beats:  # type: ignore[operator]
                    raise ValueError(
                        f"step {i} at_beat={step.at_beat} >= length_beats={self.length_beats}"
                    )
            else:
                if step.at_seconds is None:
                    raise ValueError(f"chase {self.name!r} is time-anchored but step {i} uses at_beat")
                if step.at_seconds >= self.length_seconds:  # type: ignore[operator]
                    raise ValueError(
                        f"step {i} at_seconds={step.at_seconds} >= length_seconds={self.length_seconds}"
                    )
        return self

    @property
    def beat_anchored(self) -> bool:
        return self.length_beats is not None

    def length_in_seconds(self, bpm: float) -> float:
        if self.length_seconds is not None:
            return self.length_seconds
        assert self.length_beats is not None
        return self.length_beats * 60.0 / max(bpm, 1e-6)
