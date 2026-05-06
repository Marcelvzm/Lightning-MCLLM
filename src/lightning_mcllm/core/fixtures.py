"""Fixture model.

A `FixtureProfile` describes what kind of physical device exists (channels, roles).
A `FixtureInstance` patches a specific profile at a DMX address inside an environment.

Roles are slash-namespaced semantic labels (e.g. `color/red`, `position/pan`). Scenes
and chase actions reference roles by name, so the same scene can target different
fixture types as long as the role names match. Channels with no semantic equivalent
use `raw/<offset>` so they're still addressable but don't auto-mix.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Conventional role names. Not enforced — users can invent new roles freely — but
# documented here so the LLM and humans use a consistent vocabulary.
KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "dimmer",
        "shutter",
        "strobe",
        "color/red",
        "color/green",
        "color/blue",
        "color/white",
        "color/amber",
        "color/uv",
        "color/wheel",
        "color/cto",
        "position/pan",
        "position/pan_fine",
        "position/tilt",
        "position/tilt_fine",
        "movement/speed",
        "gobo/wheel",
        "gobo/wheel_fine",
        "gobo/rotation",
        "gobo/index",
        "focus",
        "zoom",
        "iris",
        "prism",
        "frost",
        "effect/macro",
        "effect/macro_speed",
        "control/reset",
        "control/lamp",
    }
)


class FixtureChannel(BaseModel):
    """One DMX channel in a fixture profile.

    `offset` is 0-indexed within the fixture (channel 1 → offset 0). The
    fixture's `address` (set on the instance, not here) determines the absolute
    DMX address.
    """

    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0, le=511)
    role: str = Field(min_length=1)
    default: int = Field(ge=0, le=255, default=0)
    description: str | None = None
    # Optional value map: human-friendly name -> DMX value (for gobo wheels, color wheels, macros)
    presets: dict[str, int] | None = None

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, v: str) -> str:
        return v.strip().lower()


class FixtureProfile(BaseModel):
    """Profile = "what kind of device". Kept in fixture_library/.

    Profiles are environment-independent and intended to be shared / reused.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    channels: list[FixtureChannel] = Field(min_length=1)

    @property
    def footprint(self) -> int:
        """Number of DMX channels this profile occupies."""
        if not self.channels:
            return 0
        return max(c.offset for c in self.channels) + 1

    @model_validator(mode="after")
    def _check_unique_offsets(self) -> "FixtureProfile":
        offsets = [c.offset for c in self.channels]
        if len(set(offsets)) != len(offsets):
            raise ValueError(f"profile {self.name!r}: duplicate channel offsets {offsets}")
        return self

    def role_to_offset(self, role: str) -> int | None:
        """Return the channel offset for a given role, or None if absent."""
        role = role.strip().lower()
        for ch in self.channels:
            if ch.role == role:
                return ch.offset
        return None


DmxAddress = Annotated[int, Field(ge=1, le=512)]
Universe = Annotated[int, Field(ge=0, le=63)]


class FixtureInstance(BaseModel):
    """A patched fixture: a profile at a specific DMX address in an environment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    address: DmxAddress
    universe: Universe = 0
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        return [t.strip().lower() for t in v if t.strip()]
