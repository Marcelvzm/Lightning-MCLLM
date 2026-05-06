"""Genre presets — quick way to set BPM + recommended chases for a music style.

Stored per-environment as `genres.yaml`. The GUI surfaces this as a dropdown:
pick a genre, BPM is applied, recommended chases are highlighted (one click to
start the lead chase).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenrePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    bpm: float = Field(ge=20, le=400)
    # Lead chase to start when the user "applies" this genre. May be None.
    lead_chase: str | None = None
    # Other chases to suggest in the GUI (rendered as quick-fire buttons).
    recommended_chases: list[str] = Field(default_factory=list)
    # Scenes to suggest as one-click triggers.
    recommended_scenes: list[str] = Field(default_factory=list)


class GenreList(BaseModel):
    """Top-level structure of `genres.yaml`."""

    model_config = ConfigDict(extra="forbid")

    genres: list[GenrePreset] = Field(default_factory=list)
