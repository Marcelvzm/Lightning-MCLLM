"""Voices — independent transition coroutines.

A `Voice` interpolates a set of (universe, address) channels from a captured
source value to a target value over a duration, then holds the target until it
is replaced by another voice.

Voices are owned by the engine. The engine maintains them per "voice key" — a
tuple of (origin, group_signature). When a new voice is started for an existing
key, the previous voice for that key is discarded (last-writer-wins per group).

Multiple voices with different keys can write to overlapping channels — the
**newest-started voice for any given channel wins** at write time. This is
simpler than HTP and matches the way humans intuitively chain effects.

Voices that have completed (`done`) are kept around for one extra tick so their
final value is rendered, then removed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from lightning_mcllm.dmx.interface import UNIVERSE_SIZE
from lightning_mcllm.engine.interp import get as get_easing


ChannelKey = tuple[int, int]  # (universe, address-0-indexed)


@dataclass
class Voice:
    key: str
    """Stable identifier — newer voices with the same key replace older ones.
    Format convention: '{origin}:{selector_describe}' e.g. 'chase:techno_basic:tag=front_pars'.
    """

    targets: dict[ChannelKey, int]
    """Final channel values once the voice completes."""

    sources: dict[ChannelKey, int] = field(default_factory=dict)
    """Captured source values at start. Filled in by the engine when the voice
    is added — the engine reads the current shadow values for each target key.
    """

    duration: float = 0.0
    """Seconds. 0 means snap (instant). Negative is treated as 0."""

    easing: str = "linear"
    """Name of the easing function — see `engine.interp`."""

    started_at: float = field(default_factory=time.monotonic)
    """Monotonic time the voice started ticking."""

    elapsed: float = 0.0

    def tick(self, dt: float) -> None:
        self.elapsed += dt

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 1.0
        return min(1.0, self.elapsed / self.duration)

    @property
    def done(self) -> bool:
        return self.progress >= 1.0

    def write_to(self, shadow: bytearray, universe: int = 0) -> None:
        """Apply this voice's interpolated values into a shadow universe buffer."""
        if not self.targets:
            return
        t = self.progress
        ease = get_easing(self.easing)
        if t >= 1.0:
            for (univ, addr), tgt in self.targets.items():
                if univ != universe or not (0 <= addr < UNIVERSE_SIZE):
                    continue
                shadow[addr] = max(0, min(255, int(tgt)))
            return
        eased = ease(t)
        for (univ, addr), tgt in self.targets.items():
            if univ != universe or not (0 <= addr < UNIVERSE_SIZE):
                continue
            src = self.sources.get((univ, addr), shadow[addr])  # fallback: current shadow
            val = src + (tgt - src) * eased
            shadow[addr] = max(0, min(255, int(round(val))))
