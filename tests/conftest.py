"""Shared pytest fixtures: temp data dirs, ready-to-run engines, simulators."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Iterator

import pytest

from lightning_mcllm.config import Paths, Settings
from lightning_mcllm.core.library import load_fixture_library, load_stage
from lightning_mcllm.dmx.null import NullInterface
from lightning_mcllm.dmx.simulator import EuroliteSimulator
from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.runtime import Engine

REPO_DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Copy the bundled `data/` to a tmp dir so tests can mutate it freely."""
    dst = tmp_path / "data"
    shutil.copytree(REPO_DATA, dst)
    return dst


@pytest.fixture()
def settings(tmp_data_dir: Path, tmp_path: Path) -> Settings:
    return Settings(paths=Paths(tmp_data_dir, tmp_path / "runtime"))


@pytest.fixture()
def stage(settings: Settings):
    lib, _ = load_fixture_library(settings.paths.fixture_library)
    s, issues = load_stage(settings.paths.environments / "default", lib)
    assert s is not None, f"failed to load default stage: {issues.errors}"
    return s


@pytest.fixture()
def null_dmx() -> Iterator[NullInterface]:
    iface = NullInterface()
    iface.open()
    yield iface
    iface.close()


@pytest.fixture()
def engine(stage, null_dmx) -> Iterator[Engine]:
    clock = BpmClock(bpm=120.0)
    eng = Engine(stage=stage, dmx=null_dmx, clock=clock, refresh_hz=60)
    eng.start()
    # Let the loop warm up
    time.sleep(0.05)
    yield eng
    eng.stop()


@pytest.fixture()
def simulator() -> Iterator[EuroliteSimulator]:
    sim = EuroliteSimulator()
    sim.start()
    yield sim
    sim.stop()
