"""Easing functions for transitions."""

from __future__ import annotations

import math
from typing import Callable

EasingFn = Callable[[float], float]


def linear(t: float) -> float:
    return t


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_in_out(t: float) -> float:
    return 0.5 * (1 - math.cos(math.pi * t))


_EASINGS: dict[str, EasingFn] = {
    "linear": linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out,
}


def get(name: str) -> EasingFn:
    return _EASINGS.get(name, linear)
