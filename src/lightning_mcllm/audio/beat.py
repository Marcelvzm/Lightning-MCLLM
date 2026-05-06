"""Real-time BPM detection from audio input.

Uses `aubio` for tempo tracking (real-time-friendly, low-latency) and
`sounddevice` for input capture. Both are optional extras — install with
`pip install 'lightning-mcllm[audio]'`.

Design notes:
  * Detection runs in a background thread; the engine never blocks on it.
  * BPM updates are debounced and validated: a single "stray" detection
    doesn't yank the chase tempo. We require N agreement frames before
    pushing to the BpmClock.
  * Half/double errors are common in beat trackers. We bias toward staying
    near the current BPM unless the new estimate persists with high
    confidence.

If audio init fails (no input device, libs not installed, permission denied),
this module logs a clear error and reverts to manual BPM. The engine never
crashes because of audio.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from lightning_mcllm.engine.clock import BpmClock

log = logging.getLogger(__name__)


class AudioBpmDetector:
    """Optional aubio-based BPM tracker. Stays silent if libs are missing."""

    def __init__(
        self,
        clock: BpmClock,
        *,
        samplerate: int = 44100,
        buffer_size: int = 1024,
        confidence_threshold: float = 0.15,
        agreement_frames: int = 3,
        smoothing: float = 0.4,
    ):
        self._clock = clock
        self._samplerate = samplerate
        self._buffer_size = buffer_size
        self._conf_thresh = confidence_threshold
        self._agree_n = agreement_frames
        self._smooth = smoothing  # exponential smoothing factor for BPM
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._recent: deque[float] = deque(maxlen=8)
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            import aubio  # type: ignore[import-untyped]  # noqa: F401
            import sounddevice  # type: ignore[import-untyped]  # noqa: F401
        except ImportError as e:
            self._error = f"aubio/sounddevice not installed ({e}); audio BPM disabled"
            log.warning(self._error)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AudioBpm", daemon=True)
        self._thread.start()
        log.info("audio BPM detector starting")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        try:
            import aubio  # type: ignore[import-untyped]
            import numpy as np  # type: ignore[import-untyped]
            import sounddevice as sd  # type: ignore[import-untyped]
        except Exception as e:  # noqa: BLE001
            self._error = f"audio init failed: {e}"
            log.warning(self._error)
            return

        try:
            tempo = aubio.tempo("default", self._buffer_size * 2, self._buffer_size, self._samplerate)
        except Exception as e:  # noqa: BLE001
            self._error = f"aubio.tempo init failed: {e}"
            log.warning(self._error)
            return

        try:
            stream = sd.InputStream(
                samplerate=self._samplerate,
                blocksize=self._buffer_size,
                channels=1,
                dtype="float32",
            )
            stream.start()
        except Exception as e:  # noqa: BLE001
            self._error = f"audio input failed: {e}"
            log.warning(self._error)
            return

        log.info("audio BPM running (sr=%d block=%d)", self._samplerate, self._buffer_size)

        try:
            while not self._stop.is_set():
                try:
                    data, _overflow = stream.read(self._buffer_size)
                except Exception as e:  # noqa: BLE001
                    self._error = f"audio read failed: {e}"
                    log.warning(self._error)
                    time.sleep(0.5)
                    continue
                samples = np.asarray(data, dtype="float32").flatten()
                _ = tempo(samples)
                if tempo.get_confidence() < self._conf_thresh:
                    continue
                bpm = float(tempo.get_bpm())
                if not (40.0 <= bpm <= 240.0):
                    continue
                self._recent.append(bpm)
                # Require N recent reads in a tight band before pushing
                if len(self._recent) >= self._agree_n:
                    recent = list(self._recent)[-self._agree_n :]
                    spread = max(recent) - min(recent)
                    if spread > 4.0:
                        continue
                    avg = sum(recent) / len(recent)
                    cur = self._clock.bpm
                    smoothed = (1.0 - self._smooth) * cur + self._smooth * avg
                    self._clock.set_bpm(smoothed, source="audio")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
