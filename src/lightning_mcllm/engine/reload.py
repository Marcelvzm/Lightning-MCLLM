"""Hot reload — file watcher + show rebuild without dropping the show.

Strategy:
    1. `watchfiles` watches the data dir for changes.
    2. On change, rebuild the FixtureLibrary + Show in a worker thread.
    3. If the rebuild succeeds, atomically swap the Engine's show.
    4. If it fails, log errors but keep running with the *previous* show.

The engine swap is just a reference swap. Voices that were spawned by the old
show keep their channel targets (they're plain dicts already resolved). Active
chase runners are dropped because their internal references would point at
stale Show fields. Re-trigger chases manually after a reload, OR enable
`auto_resume` (default) which restarts whatever was running.

This module also exposes a manual `reload()` callable for the MCP server to
invoke after the LLM finishes editing a YAML file (don't wait for fs polling).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lightning_mcllm.config import Settings
from lightning_mcllm.core.library import LoadIssues, Show, load_fixture_library, load_show
from lightning_mcllm.engine.runtime import Engine

log = logging.getLogger(__name__)


class HotReloader:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        environment_name: str,
        *,
        on_reload: Callable[[Show | None, LoadIssues], None] | None = None,
        auto_resume: bool = True,
    ):
        self._engine = engine
        self._settings = settings
        self._env_name = environment_name
        self._on_reload = on_reload
        self._auto_resume = auto_resume
        self._stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Track the version we last loaded so reloads are idempotent
        self._gen = 0
        # Remember active state so auto_resume can restore it
        self._last_active_chases: list[str] = []

    @property
    def env_name(self) -> str:
        return self._env_name

    def env_dir(self) -> Path:
        return self._settings.paths.environments / self._env_name

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._watch_thread is not None:
            return
        self._stop.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop, name="HotReloader", daemon=True
        )
        self._watch_thread.start()
        log.info("hot reloader watching %s", self._settings.paths.data_dir)

    def stop(self) -> None:
        self._stop.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2.0)
        self._watch_thread = None

    # -------------------------------------------------------------- public ops

    def reload_now(self) -> tuple[Show | None, LoadIssues]:
        """Synchronous reload — returns the new show + issues. Used by MCP."""
        with self._lock:
            return self._do_reload()

    def switch_environment(self, name: str) -> tuple[Show | None, LoadIssues]:
        with self._lock:
            self._env_name = name
            return self._do_reload()

    # ----------------------------------------------------------------- watcher

    def _watch_loop(self) -> None:
        try:
            from watchfiles import watch
        except ImportError:
            log.warning("watchfiles not installed; hot reload disabled")
            return
        debounce_until = 0.0
        try:
            for changes in watch(
                str(self._settings.paths.data_dir),
                stop_event=self._stop,
                # Coarse step to coalesce rapid bursts
                step=200,
                rust_timeout=500,
                yield_on_timeout=False,
            ):
                # Filter out non-yaml changes
                yamls = [c for c in changes if c[1].endswith((".yaml", ".yml"))]
                if not yamls:
                    continue
                log.info("data changed (%d files); reloading", len(yamls))
                with self._lock:
                    self._do_reload()
        except Exception as e:  # noqa: BLE001
            log.exception("hot reloader crashed: %s", e)

    # ---------------------------------------------------------------- reload op

    def _do_reload(self) -> tuple[Show | None, LoadIssues]:
        # Capture currently-running chase names BEFORE replacing
        active = list(self._engine.status().active_chases)
        # Strip 'chase:<name>:<n>' down to <name> for re-triggering
        active_names: list[str] = []
        for k in active:
            parts = k.split(":")
            if len(parts) >= 2 and parts[0] == "chase":
                active_names.append(parts[1])

        lib, lib_issues = load_fixture_library(self._settings.paths.fixture_library)
        env_dir = self.env_dir()
        if not env_dir.exists():
            issues = LoadIssues()
            issues.errors.extend(lib_issues.errors)
            issues.errors.append(f"environment directory not found: {env_dir}")
            log.error("reload aborted: environment dir missing %s", env_dir)
            if self._on_reload:
                self._on_reload(None, issues)
            return None, issues

        show, show_issues = load_show(env_dir, lib)
        # Compose issues
        combined = LoadIssues()
        combined.errors.extend(lib_issues.errors)
        combined.errors.extend(show_issues.errors)
        combined.warnings.extend(lib_issues.warnings)
        combined.warnings.extend(show_issues.warnings)

        if show is None:
            log.warning("reload failed; keeping previous show. errors:")
            for e in combined.errors:
                log.warning("  %s", e)
            if self._on_reload:
                self._on_reload(None, combined)
            return None, combined

        self._gen += 1
        self._engine.replace_show(show)
        log.info("reload OK (gen=%d): %d fixtures, %d scenes, %d chases, %d banks",
                 self._gen, len(show.fixtures), len(show.scenes), len(show.chases), len(show.banks))

        if self._auto_resume:
            for chase_name in active_names:
                if chase_name in show.chases:
                    self._engine.submit("start_chase", chase=chase_name)

        if self._on_reload:
            self._on_reload(show, combined)
        return show, combined
