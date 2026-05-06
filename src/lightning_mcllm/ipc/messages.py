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
    "tap",
    "fire_slot",
    "set_value",
    # special — handled in IPC server, not Engine.submit
    "status",
    "shadow",
    "list_environments",
    "switch_environment",
    "list_show",
    "reload",
)


# Audio mode, future
class SetAudioModeArgs(BaseModel):
    mode: Literal["off", "audio", "manual"] = "manual"
