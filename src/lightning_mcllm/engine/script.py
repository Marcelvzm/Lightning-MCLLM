"""Chase runner — converts chase YAML semantics into voice spawns over time.

Given a `Chase` and a `Show`, the runner advances a "position" each tick. When
the position crosses a step's anchor, the runner fires that step's actions:

  * `transition` -> spawn a Voice with a captured source state and a target.
  * `snap`       -> spawn a Voice with duration=0 (instant).
  * `release`    -> remove voices whose key matches the selector, channels hold.

Position is in beats (chase is beat-anchored) or seconds (time-anchored). When
looping, position wraps modulo length.

Step firing logic accounts for wrap: if the previous tick's position was 3.9
beats and the new position is 0.1 beats (wrapped past 4-beat length), steps
between [3.9, 4.0) and [0.0, 0.1) both fire.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from lightning_mcllm.core.chases import (
    Chase,
    ReleaseAction,
    SnapAction,
    Step,
    TransitionAction,
)
from lightning_mcllm.core.library import Show
from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.voice import Voice

log = logging.getLogger(__name__)


@dataclass
class FiredAction:
    """Result of firing a step action. The runtime turns these into voices."""

    voice_key: str
    targets: dict[tuple[int, int], int]
    duration: float
    easing: str
    release: bool = False
    """If True, this is a release action — the engine should drop voices with
    matching key prefix instead of starting a new voice.
    """


@dataclass
class ChaseRunner:
    chase: Chase
    show: Show
    instance_id: str
    """Unique key per running instance (e.g. 'chase:techno_basic:1')."""

    elapsed_seconds: float = 0.0
    """For time-anchored chases."""

    last_position: float = 0.0
    """Beat or seconds position at end of previous tick — used for step crossing."""

    _started: bool = False
    _completed: bool = False
    _pending_first_fire: list[Step] = field(default_factory=list)

    def stop(self) -> None:
        self._completed = True

    @property
    def completed(self) -> bool:
        return self._completed

    def tick(self, dt: float, clock: BpmClock) -> tuple[list[FiredAction], float]:
        """Advance one tick. Returns (fired actions, current position).

        Side-effect-free w.r.t. show state — the runtime decides what to do
        with the returned FiredActions (typically: convert to Voices and add to
        engine voice set, or drop voices for release).
        """
        if self._completed:
            return [], self.last_position

        if self.chase.beat_anchored:
            position = clock.beat_position
            length = self.chase.length_beats or 1.0
        else:
            self.elapsed_seconds += dt
            position = self.elapsed_seconds
            length = self.chase.length_seconds or 1.0

        prev = self.last_position
        if not self._started:
            # On first tick, anchor prev a hair below the wrap-normalized current
            # position so a step at exactly that position fires immediately.
            self._started = True
            if self.chase.beat_anchored:
                prev = (position % length) - 1e-9
            else:
                prev = -1e-9

        cur = position % length if self.chase.loop else min(position, length)
        wrapped = self.chase.loop and (cur < prev)

        fired: list[FiredAction] = []
        for step in self.chase.steps:
            anchor = step.at_beat if self.chase.beat_anchored else step.at_seconds
            if anchor is None:
                continue
            should_fire = False
            if not wrapped:
                # Normal: fire if anchor is in (prev, cur]
                if prev < anchor <= cur:
                    should_fire = True
            else:
                # Wrapped: fire if anchor in (prev, length) OR [0, cur]
                if anchor > prev or anchor <= cur:
                    should_fire = True
            if should_fire:
                fired.extend(self._compile_step(step))

        self.last_position = cur
        if not self.chase.loop and cur >= length:
            self._completed = True
        return fired, cur

    def _compile_step(self, step: Step) -> list[FiredAction]:
        # Each action gets its own voice key, indexed by step + action position so
        # snap-then-fade in the same step doesn't collapse onto one voice.
        step_idx = self.chase.steps.index(step)
        out: list[FiredAction] = []
        for action_idx, action in enumerate(step.actions):
            base_key = f"{self.instance_id}:s{step_idx}:a{action_idx}"
            if isinstance(action, TransitionAction):
                targets = self._resolve_targets(action.group, action.scene, action.values)
                out.append(
                    FiredAction(
                        voice_key=f"{base_key}:{action.group.describe()}",
                        targets=targets,
                        duration=action.fade_seconds,
                        easing=action.easing,
                    )
                )
            elif isinstance(action, SnapAction):
                targets = self._resolve_targets(action.group, action.scene, action.values)
                out.append(
                    FiredAction(
                        voice_key=f"{base_key}:{action.group.describe()}",
                        targets=targets,
                        duration=0.0,
                        easing="linear",
                    )
                )
            elif isinstance(action, ReleaseAction):
                # For release, the prefix targets ALL voices spawned by this chase
                # instance — we want to drop accumulated voices, not a single one.
                out.append(
                    FiredAction(
                        voice_key=self.instance_id,  # match-prefix in engine
                        targets={},
                        duration=0.0,
                        easing="linear",
                        release=True,
                    )
                )
        return out

    def _resolve_targets(self, selector, scene_name, inline_values):  # type: ignore[no-untyped-def]
        if scene_name is not None:
            scene = self.show.scenes.get(scene_name)
            if scene is None:
                log.warning("chase %r references missing scene %r", self.chase.name, scene_name)
                return {}
            rendered = self.show.render_scene(scene)
            # Filter to channels that belong to fixtures matching the selector
            allowed = self.show.channels_for(selector)
            return {k: v for k, v in rendered.values.items() if k in allowed}
        if inline_values is not None:
            return self.show.render_inline_values(selector, inline_values)
        return {}


def make_voice(fired: FiredAction, shadow_snapshot: dict[tuple[int, int], int]) -> Voice:
    """Build a Voice from a FiredAction by capturing source values from the
    given snapshot of channels we care about.
    """
    sources = {key: shadow_snapshot.get(key, 0) for key in fired.targets}
    return Voice(
        key=fired.voice_key,
        targets=dict(fired.targets),
        sources=sources,
        duration=fired.duration,
        easing=fired.easing,
    )
