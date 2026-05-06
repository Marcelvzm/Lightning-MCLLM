"""BPM clock.

Tracks musical time as a continuous "beat position" (float, beats since clock
start or last reset). Used by beat-anchored chases.

Two modes:

* **Manual** — user sets a fixed BPM. Optionally tap-tempo: the user taps a
  button on every beat, we average inter-tap intervals into a BPM.
* **Audio** — wired up later via `audio.beat`. The audio detector pushes a
  `set_bpm()` and a `phase_align()` whenever it locks onto a new tempo.

The clock is monotonic — it never goes backward, even when BPM changes mid-
flight. We continue from the current beat position at the new rate.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockSnapshot:
    bpm: float
    beat_position: float
    running: bool
    source: str  # "manual" | "audio" | "tap"


class BpmClock:
    def __init__(self, bpm: float = 120.0):
        self._bpm = float(bpm)
        self._beat_position = 0.0
        self._last_tick = time.monotonic()
        self._running = True
        self._lock = threading.Lock()
        self._source = "manual"
        # Tap tempo state
        self._tap_times: deque[float] = deque(maxlen=8)
        self._tap_window_s = 3.0  # taps further apart than this reset the chain

    # ------------------------------------------------------------------ tick

    def tick(self) -> float:
        """Advance beat position by real time elapsed since last tick.

        Returns current beat position. Call this every engine frame.
        """
        now = time.monotonic()
        with self._lock:
            dt = now - self._last_tick
            self._last_tick = now
            if self._running and self._bpm > 0:
                self._beat_position += dt * self._bpm / 60.0
            return self._beat_position

    # --------------------------------------------------------------- accessors

    @property
    def beat_position(self) -> float:
        with self._lock:
            return self._beat_position

    @property
    def bpm(self) -> float:
        with self._lock:
            return self._bpm

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def source(self) -> str:
        with self._lock:
            return self._source

    def snapshot(self) -> ClockSnapshot:
        with self._lock:
            return ClockSnapshot(
                bpm=self._bpm,
                beat_position=self._beat_position,
                running=self._running,
                source=self._source,
            )

    # --------------------------------------------------------------- mutations

    def set_bpm(self, bpm: float, *, source: str = "manual") -> None:
        bpm = max(20.0, min(400.0, float(bpm)))
        with self._lock:
            self._bpm = bpm
            self._source = source
            log.info("BPM set to %.2f (%s)", bpm, source)

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._running = bool(running)

    def reset_phase(self, beat: float = 0.0) -> None:
        """Snap beat position to a value (typically 0). Called on bar-line."""
        with self._lock:
            self._beat_position = float(beat)
            self._last_tick = time.monotonic()

    def tap(self) -> ClockSnapshot:
        """Register a beat tap. After 3+ taps, locks BPM to inter-tap average."""
        now = time.monotonic()
        with self._lock:
            # Reset chain if last tap was long ago
            if self._tap_times and (now - self._tap_times[-1]) > self._tap_window_s:
                self._tap_times.clear()
            self._tap_times.append(now)
            if len(self._tap_times) >= 3:
                intervals = [
                    self._tap_times[i] - self._tap_times[i - 1]
                    for i in range(1, len(self._tap_times))
                ]
                avg = sum(intervals) / len(intervals)
                if avg > 0:
                    bpm = max(20.0, min(400.0, 60.0 / avg))
                    self._bpm = bpm
                    self._source = "tap"
                    self._beat_position = 0.0  # tap-driven phase reset
                    self._last_tick = now
                    log.info("tap tempo: %.2f BPM (from %d taps)", bpm, len(self._tap_times))
            return ClockSnapshot(
                bpm=self._bpm,
                beat_position=self._beat_position,
                running=self._running,
                source=self._source,
            )
