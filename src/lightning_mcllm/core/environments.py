"""Environment model.

An Environment is one self-contained "stage" — its own set of patched fixtures,
scenes, chases, and banks. Multiple environments live side-by-side under
`data/environments/<name>/` and the user picks one to run.

Migration is intentionally trivial: copy the env folder, copy individual scene
or chase YAML files between envs. As long as fixture tags line up, scenes work
across envs unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lightning_mcllm.core.fixtures import FixtureInstance


class EnvironmentManifest(BaseModel):
    """Top-level metadata + fixture patch list. Stored in environment.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    universes: list[int] = Field(default_factory=lambda: [0])
    fixtures: list[FixtureInstance] = Field(default_factory=list)
    default_bank: str | None = None

    @model_validator(mode="after")
    def _check_no_overlap_and_unique_names(self) -> "EnvironmentManifest":
        names = [f.name for f in self.fixtures]
        if len(set(names)) != len(names):
            dups = [n for n in names if names.count(n) > 1]
            raise ValueError(f"environment {self.name!r}: duplicate fixture names {sorted(set(dups))}")
        # Address overlap check requires profile lookup; deferred to Environment build.
        return self
