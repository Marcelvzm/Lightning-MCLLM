"""Bank model.

A Bank is a labelled collection of slots; each slot points to a scene or chase
that the user can trigger from the GUI. Multiple slots can be active
simultaneously — banks are a UI organisation tool, not a runtime constraint.

A `blackout` slot kind clears all voices and snaps every channel to 0. A
`release` slot kind only stops the voices for a given selector.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lightning_mcllm.core.selectors import Selector


class SceneSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    kind: Literal["scene"]
    name: str
    label: str | None = None
    fade_seconds: float = Field(ge=0, default=0.0)
    # Optional argument overrides forwarded to the scene's parameters at
    # trigger time. Empty dict / omitted = use scene defaults.
    args: dict[str, Any] = Field(default_factory=dict)
    # Optional keyboard shortcut. Single character (case-insensitive) or
    # a named key like "Space" / "Escape". No automatic mapping — if you
    # don't set this, the key is unbound.
    key: str | None = None


class ChaseSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    kind: Literal["chase"]
    name: str
    label: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    key: str | None = None


class BlackoutSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    kind: Literal["blackout"]
    label: str | None = "Blackout"
    fade_seconds: float = Field(ge=0, default=0.0)
    key: str | None = None


class ReleaseSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    kind: Literal["release"]
    group: Selector
    label: str | None = None
    key: str | None = None


Slot = SceneSlot | ChaseSlot | BlackoutSlot | ReleaseSlot


class Bank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    slots: list[Slot] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Bank":
        ids = [s.id for s in self.slots]
        if len(set(ids)) != len(ids):
            raise ValueError(f"bank {self.name!r}: duplicate slot ids {ids}")
        return self
