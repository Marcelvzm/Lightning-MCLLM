"""Scene model.

A Scene is a snapshot: which fixtures should be at which channel values.
Scenes define values by *role* (e.g. `color/red: 255`), not by raw DMX offset, so
the same scene works against different fixtures with the same roles.

A scene resolves to a `RenderedScene` — explicit (universe, address) → value
mapping — once joined with an Environment's fixtures.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lightning_mcllm.core.palettes import PaletteRef
from lightning_mcllm.core.parameters import ParameterSpec
from lightning_mcllm.core.selectors import Selector


class SceneTarget(BaseModel):
    """One target inside a scene: a selector + role-keyed values."""

    model_config = ConfigDict(extra="forbid")

    select: Selector
    # Values may be ints (literal channel values) or strings of the form
    # "${param}" — placeholders that get resolved at render time using the
    # scene's `parameters` and the caller-provided args. See
    # core/parameters.py for the substitution rules.
    values: dict[str, int | str] = Field(default_factory=dict)
    # Optional: preset names (looked up via fixture profile presets)
    presets: dict[str, str] | None = None
    # Optional: palette+facet reference. Resolves at render time against the
    # stage's palette library. Explicit `values:` win on role conflicts.
    palette: PaletteRef | None = None

    @field_validator("values")
    @classmethod
    def _check_values(cls, v: dict[str, int | str]) -> dict[str, int | str]:
        out: dict[str, int | str] = {}
        for role, val in v.items():
            if isinstance(val, int):
                if not (0 <= val <= 255):
                    raise ValueError(f"value for role {role!r} must be in 0..255 (got {val})")
                out[role.strip().lower()] = val
            elif isinstance(val, str):
                # Parameter placeholder; range check happens after resolution.
                out[role.strip().lower()] = val
            else:
                raise ValueError(f"value for role {role!r} must be int or '${{param}}' (got {val!r})")
        return out


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
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
