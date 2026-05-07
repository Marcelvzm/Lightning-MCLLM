"""Show — a scripted choreography that runs on a Stage.

A Show is the top of the authoring hierarchy. Below it sit chases, scenes,
banks, and the fixture rig. A Show specifies *how* those pieces are
sequenced over time: when to fire which scene, when to start which chase,
when to wait, when to drop, when to blackout.

Replaces the previous `Genre` concept — every Show carries the BPM and
description that genre had, plus a real script and per-key bindings for the
GUI play-mode.

YAML layout (simplified):

    name: techno_60min
    description: 60-minute techno set
    bpm: 128
    loop: false
    keybindings:
      "1": { kind: chase, name: pulse_4otf }
      "2": { kind: chase, name: mh_sweep }
      "Q": { kind: scene, name: warm_idle }

    script:
      - { do: snap_scene, scene: warm_idle }
      - { do: wait, seconds: 30 }
      - { do: start_chase, chase: pulse_4otf }
      - { do: wait, bars: 16 }
      - { do: blackout, fade: 0.5 }
      - { do: wait, beats: 1 }
      - { do: release_blackout }
      - do: loop
        times: 4
        actions:
          - { do: snap_scene, scene: red_full }
          - { do: wait, beats: 1 }
          - { do: snap_scene, scene: red_dim }
          - { do: wait, beats: 1 }

Action types are documented inline below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lightning_mcllm.core.selectors import Selector

if TYPE_CHECKING:
    from lightning_mcllm.core.banks import Bank
    from lightning_mcllm.core.chases import Chase
    from lightning_mcllm.core.scenes import Scene


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------


class ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapSceneAction(ActionBase):
    """Apply a named scene immediately (or with a fade)."""

    do: Literal["snap_scene"]
    scene: str
    fade: float = Field(ge=0, default=0.0)


class StartChaseAction(ActionBase):
    """Start a chase. Async — script continues immediately while chase loops."""

    do: Literal["start_chase"]
    chase: str


class StopChaseAction(ActionBase):
    do: Literal["stop_chase"]
    chase: str


class StopAllChasesAction(ActionBase):
    do: Literal["stop_all_chases"]


class FireSlotAction(ActionBase):
    """Fire a bank slot by id."""

    do: Literal["fire_slot"]
    bank: str
    slot: int = Field(ge=1)


class BlackoutAction(ActionBase):
    """Blackout. Without `group`, latches the global blackout. With `group`,
    snaps every channel of the selected fixtures to 0 (no latch — a later
    voice will override)."""

    do: Literal["blackout"]
    group: Selector | None = None
    fade: float = Field(ge=0, default=0.0)


class ReleaseBlackoutAction(ActionBase):
    do: Literal["release_blackout"]


class SetValuesAction(ActionBase):
    """Set values on a group (or single fixture by name). `fade=0` is a snap."""

    do: Literal["set_values"]
    group: Selector
    values: dict[str, int]
    fade: float = Field(ge=0, default=0.0)

    @field_validator("values")
    @classmethod
    def _check_values(cls, v: dict[str, int]) -> dict[str, int]:
        out: dict[str, int] = {}
        for role, val in v.items():
            if not (0 <= val <= 255):
                raise ValueError(f"value for role {role!r} must be 0..255 (got {val})")
            out[role.strip().lower()] = int(val)
        return out


class WaitAction(ActionBase):
    """Plain wait. Specify exactly one of `seconds`, `beats`, `bars`.
    `bars` and `beats` use the engine's BPM clock — pause the clock and the
    show waits indefinitely."""

    do: Literal["wait"]
    seconds: float | None = Field(default=None, ge=0)
    beats: float | None = Field(default=None, ge=0)
    bars: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _exactly_one(self) -> "WaitAction":
        chosen = sum(1 for x in (self.seconds, self.beats, self.bars) if x is not None)
        if chosen != 1:
            raise ValueError("wait must specify exactly one of seconds / beats / bars")
        return self


class WaitChaseAction(ActionBase):
    """Wait until a running chase completes one full loop iteration. If the
    chase isn't running, completes immediately. If the chase is non-looping,
    waits until it finishes and then completes."""

    do: Literal["wait_chase"]
    chase: str


class WaitGroupAction(ActionBase):
    """Wait until every voice currently writing channels in `group` has
    finished its transition (elapsed >= duration). If no such voices exist,
    completes immediately. Useful to chain "fade group A then fade group B"
    without hardcoding fade times."""

    do: Literal["wait_group"]
    group: Selector


class SetBpmAction(ActionBase):
    do: Literal["set_bpm"]
    bpm: float = Field(ge=20, le=400)


class LogAction(ActionBase):
    """Append a message to the engine's last_errors log (handy for debugging)."""

    do: Literal["log"]
    message: str


class LoopAction(ActionBase):
    """Repeat a sub-list of actions N times.

    `times: 0` is a no-op (defensive — easy to misedit a YAML to 0 and we
    don't want to halt the show on it). Forever-loops are intentionally not
    supported here — wrap the whole Show with `loop: true` instead.
    """

    do: Literal["loop"]
    times: int = Field(ge=0)
    actions: "list[Action]" = Field(min_length=1)


# Discriminated union — pydantic picks the right subclass based on `do`.
Action = Union[
    SnapSceneAction,
    StartChaseAction,
    StopChaseAction,
    StopAllChasesAction,
    FireSlotAction,
    BlackoutAction,
    ReleaseBlackoutAction,
    SetValuesAction,
    WaitAction,
    WaitChaseAction,
    WaitGroupAction,
    SetBpmAction,
    LogAction,
    LoopAction,
]


LoopAction.model_rebuild()  # resolve forward ref


# ---------------------------------------------------------------------------
# Keybinding
# ---------------------------------------------------------------------------


class Keybinding(BaseModel):
    """One key → fire scene/chase/blackout in play-mode."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scene", "chase", "blackout", "release_blackout", "stop_all_chases"]
    name: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _name_required_for_targets(self) -> "Keybinding":
        if self.kind in ("scene", "chase") and not self.name:
            raise ValueError(f"keybinding kind={self.kind!r} requires `name`")
        return self


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


class Show(BaseModel):
    """A scripted choreography. Lives in `data/environments/<env>/shows/*.yaml`.

    Runs on a Stage via `engine.show_runner.ShowRunner`. The script executes
    sequentially; async actions like `start_chase` don't block the timeline.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    bpm: float = Field(ge=20, le=400, default=120.0)
    loop: bool = False
    keybindings: dict[str, Keybinding] = Field(default_factory=dict)
    script: list[Action] = Field(default_factory=list)

    @field_validator("keybindings")
    @classmethod
    def _normalize_keys(cls, v: dict[str, Keybinding]) -> dict[str, Keybinding]:
        # Single-character keys get uppercased (case-insensitive matching).
        # Multi-char keys (e.g. "ArrowUp") stay as-is.
        out: dict[str, Keybinding] = {}
        for k, binding in v.items():
            key = k.upper() if len(k) == 1 else k
            if key in out:
                raise ValueError(f"duplicate keybinding {key!r}")
            out[key] = binding
        return out


# ---------------------------------------------------------------------------
# Cross-validation helper
# ---------------------------------------------------------------------------


def _walk_actions(actions: list[Action]):
    for a in actions:
        yield a
        if isinstance(a, LoopAction):
            yield from _walk_actions(a.actions)


def validate_show_against_stage(
    show: Show,
    scenes: "dict[str, Scene]",
    chases: "dict[str, Chase]",
    banks: "dict[str, Bank]",
) -> list[str]:
    """Walk the script + keybindings, return a list of warnings.

    These are warnings (not errors) so a show with a stale reference still
    loads — useful while the LLM is mid-edit."""
    warnings: list[str] = []

    def warn(msg: str) -> None:
        warnings.append(f"show {show.name!r}: {msg}")

    for action in _walk_actions(list(show.script)):
        if isinstance(action, SnapSceneAction):
            if action.scene not in scenes:
                warn(f"snap_scene references unknown scene {action.scene!r}")
        elif isinstance(action, (StartChaseAction, StopChaseAction)):
            if action.chase not in chases:
                warn(f"chase action references unknown chase {action.chase!r}")
        elif isinstance(action, WaitChaseAction):
            if action.chase not in chases:
                warn(f"wait_chase references unknown chase {action.chase!r}")
        elif isinstance(action, FireSlotAction):
            if action.bank not in banks:
                warn(f"fire_slot references unknown bank {action.bank!r}")

    for key, binding in show.keybindings.items():
        if binding.kind == "scene" and binding.name not in scenes:
            warn(f"keybinding {key!r} references unknown scene {binding.name!r}")
        elif binding.kind == "chase" and binding.name not in chases:
            warn(f"keybinding {key!r} references unknown chase {binding.name!r}")

    return warnings
