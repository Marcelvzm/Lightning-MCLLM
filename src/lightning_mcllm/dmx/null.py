"""Null DMX interface — no hardware, just records the last frame.

Used when no Eurolite is connected (dev / overnight build) and in tests. Holds
the most recent frame so external observers (web UI, tests) can inspect what
the engine *would* be sending.
"""

from __future__ import annotations

import logging
import threading

from lightning_mcllm.dmx.interface import UNIVERSE_SIZE, DmxInterface

log = logging.getLogger(__name__)


class NullInterface(DmxInterface):
    def __init__(self, *, log_changes: bool = False):
        self._open = False
        self._frames: dict[int, bytes] = {}
        self._lock = threading.Lock()
        self._log_changes = log_changes

    def open(self) -> None:
        self._open = True
        log.info("null DMX interface opened")

    def close(self) -> None:
        self._open = False

    def send(self, universe: int, frame: bytes) -> None:
        if len(frame) != UNIVERSE_SIZE:
            raise ValueError(f"frame must be {UNIVERSE_SIZE} bytes, got {len(frame)}")
        with self._lock:
            prev = self._frames.get(universe)
            self._frames[universe] = frame
            if self._log_changes and prev != frame:
                non_zero = sum(1 for b in frame if b)
                log.debug("null DMX frame univ=%d nonzero=%d/%d", universe, non_zero, UNIVERSE_SIZE)

    def last_frame(self, universe: int = 0) -> bytes | None:
        with self._lock:
            return self._frames.get(universe)

    @property
    def connected(self) -> bool:
        return self._open

    @property
    def description(self) -> str:
        return "null"
