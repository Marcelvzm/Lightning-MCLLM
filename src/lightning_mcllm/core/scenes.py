"""Scene model.

A Scene is a snapshot: which fixtures should be at which channel values.
Scenes define values by *role* (e.g. `color/red: 255`), not by raw DMX offset, so
the same scene works against different fixtures with the same roles.

A scene resolves to a `RenderedScene` — explicit (universe, address) → value
mapping — once joined with an Environment's fixtures.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lightning_mcllm.core.selectors import Selector


class SceneTarget(BaseModel):
    """One target inside a scene: a selector + role-keyed values."""

    model_config = ConfigDict(extra="forbid")

    select: Selector
    values: dict[str, int] = Field(default_factory=dict)
    # Optional: preset names (looked up via fixture profile presets)
    presets: dict[str, str] | None = None

    @field_validator("values")
    @classmethod
    def _check_values(cls, v: dict[str, int]) -> dict[str, int]:
        for role, val in v.items():
            if not (0 <= val <= 255):
                raise ValueError(f"value for role {role!r} must be in 0..255 (got {val})")
        return {k.strip().lower(): v for k, v in v.items()}


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    targets: list[SceneTarget] = Field(default_factory=list)


class RenderedScene(BaseModel):
    """A scene resolved against concrete fixtures.

    Maps (universe, dmx_address) -> 0..255 value. This is what the engine
    interpolates toward.
    """

    name: str
    values: dict[tuple[int, int], int]

    def channel_set(self) -> set[tuple[int, int]]:
        return set(self.values.keys())
