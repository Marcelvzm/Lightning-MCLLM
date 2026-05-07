"""Process-wide configuration and well-known paths.

Resolved once at startup and passed explicitly down — no globals at import time
beyond defaults. Keeps the engine deterministic for testing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    env = os.environ.get("LIGHTNING_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # Project-local default — co-located with source for dev convenience.
    here = Path(__file__).resolve().parent.parent.parent
    return (here / "data").resolve()


def _default_runtime_dir() -> Path:
    env = os.environ.get("LIGHTNING_RUNTIME_DIR")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent.parent.parent
    return (here / "runtime").resolve()


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    runtime_dir: Path

    @property
    def fixture_library(self) -> Path:
        return self.data_dir / "fixture_library"

    @property
    def environments(self) -> Path:
        return self.data_dir / "environments"

    @property
    def state_file(self) -> Path:
        return self.runtime_dir / "state.json"

    @property
    def dmx_socket(self) -> Path:
        return self.runtime_dir / "dmx.sock"

    @property
    def engine_socket(self) -> Path:
        return self.runtime_dir / "engine.sock"


@dataclass(frozen=True)
class Settings:
    paths: Paths = field(default_factory=lambda: Paths(_default_data_dir(), _default_runtime_dir()))
    dmx_refresh_hz: int = 30
    web_host: str = "127.0.0.1"
    web_port: int = 7777
    # 250000 baud — needed for the Eurolite USB-DMX512 PRO MK2 to deliver a
    # full 512-channel universe at >=25Hz. The original Enttec USB Pro spec
    # used 57600, but at that rate a 513-byte frame takes ~89ms (longer than
    # one 30Hz tick) → write timeouts → adapter LED stays red and no DMX
    # makes it to the wire. 250000 covers most modern FTDI-based DMX
    # adapters. Override via `--baud` if your specific device disagrees.
    serial_baudrate: int = 250000
    # Default port; if None, auto-discover.
    serial_port: str | None = None
    # If True, engine runs without ever opening serial — null DMX (good for dev).
    force_null_dmx: bool = False


def load_settings() -> Settings:
    """Build settings from environment and ensure runtime dirs exist."""
    s = Settings(
        force_null_dmx=os.environ.get("LIGHTNING_NULL_DMX", "").lower() in {"1", "true", "yes"},
        serial_port=os.environ.get("LIGHTNING_SERIAL_PORT") or None,
    )
    s.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    s.paths.data_dir.mkdir(parents=True, exist_ok=True)
    s.paths.fixture_library.mkdir(parents=True, exist_ok=True)
    s.paths.environments.mkdir(parents=True, exist_ok=True)
    return s
