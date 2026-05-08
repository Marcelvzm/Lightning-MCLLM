"""IPC message schemas (engine ↔ web ↔ MCP).

Line-delimited JSON over TCP localhost. Each line is one self-contained message.
Messages are explicit Pydantic models so both sides agree on field names.

Design: requests are imperative ("do X"); status snapshots are pulled (not pushed).
Web subscribes to a status topic for periodic broadcasts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Top-level IPC frame."""

    model_config = ConfigDict(extra="forbid")

    op: str
    id: int = 0
    args: dict[str, Any] = Field(default_factory=dict)


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    ok: bool
    data: Any = None
    error: str | None = None


# --------- engine ops (op names match Engine.submit/dispatch) ---------------

ENGINE_OPS: tuple[str, ...] = (
    "snap_scene",
    "blackout",
    "release_blackout",
    "start_chase",
    "stop_chase",
    "stop_all_chases",
    "set_master",
    "set_bpm",
    "set_clock_running",
    "tap",
    "fire_slot",
    "set_value",
    "set_values_group",
    "play_show",
    "pause_show",
    "resume_show",
    "reset_show",
    "stop_show",
    "seek_show",
    "set_show_reference_bpm",
    "start_audio",
    "stop_audio",
    "set_bpm_range",
    "set_pause_on_silence",
    "all_off",
    "log",
    # special — handled in IPC server / web router, not via Engine.submit
    "status",
    "shadow",
    "list_environments",
    "switch_environment",
    "list_stage",
    "reload",
)


# Audio mode, future
class SetAudioModeArgs(BaseModel):
    mode: Literal["off", "audio", "manual"] = "manual"
