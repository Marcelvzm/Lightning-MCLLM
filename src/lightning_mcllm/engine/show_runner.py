"""ShowRunner — interprets a `Show` script during engine ticks.

Lives inside the engine main loop. Submits commands back to the engine for
all "do something" actions; uses engine helpers (`chase_loop_position`,
`is_transitioning_in`) for wait-conditions.

State machine:

    idle ──play()──▶ running ──pause()──▶ paused
                       │  ▲                  │
                       │  └──── resume() ◀───┘
                       │
                       └──── reset() ──▶ running (from start)
                       └──── stop()  ──▶ idle

Loop semantics: the script is executed using a frame stack — every LoopAction
pushes a frame with its own pc and `iterations_remaining`. The top-level
script is itself a frame; if `show.loop` is true, its iterations_remaining
is -1 (infinite).

Per-tick budget: at most N actions execute per engine tick (default 200) to
prevent a malformed script with no waits from spinning forever in one tick.
The remainder runs on the next tick — consequence: a 1000-action script
without any waits takes ~5 ticks to fully execute, fine.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lightning_mcllm.core.shows import (
    Action,
    BlackoutAction,
    FireSlotAction,
    LogAction,
    LoopAction,
    ReleaseBlackoutAction,
    SetBpmAction,
    SetValuesAction,
    Show,
    SnapSceneAction,
    StartChaseAction,
    StopAllChasesAction,
    StopChaseAction,
    WaitAction,
    WaitChaseAction,
    WaitGroupAction,
)
from lightning_mcllm.engine.clock import BpmClock

if TYPE_CHECKING:
    from lightning_mcllm.engine.runtime import Engine

log = logging.getLogger(__name__)

ACTIONS_PER_TICK_BUDGET = 200


# ---------------------------------------------------------------------------
# Frame + wait state
# ---------------------------------------------------------------------------


@dataclass
class _Frame:
    """One level on the script execution stack — a list of actions plus the
    current program counter and remaining loop iterations."""

    actions: list[Action]
    pc: int = 0
    iterations_remaining: int = 1
    """Number of times to execute this frame's actions. -1 means infinite
    (used for the top-level frame when show.loop is true)."""


@dataclass
class _TimeWait:
    """Wait for a duration. Computed at the moment the action fires."""

    until_seconds: float | None = None
    """Wall-clock target (engine elapsed_seconds) for `seconds` waits."""

    until_beats: float | None = None
    """Beat-position target for `beats`/`bars` waits."""


@dataclass
class _ChaseWait:
    chase: str
    started_at_position: float
    started_at_monotonic: float


@dataclass
class _GroupWait:
    selector: object  # Selector (untyped here to avoid circular deps)


# ---------------------------------------------------------------------------
# ShowRunner
# ---------------------------------------------------------------------------


class ShowRunner:
    def __init__(self, show: Show, engine: "Engine", clock: BpmClock):
        self._show = show
        self._engine = engine
        self._clock = clock
        self._stack: list[_Frame] = []
        self._wait: _TimeWait | _ChaseWait | _GroupWait | None = None
        self._elapsed_seconds: float = 0.0
        self._state: str = "idle"  # idle | running | paused | completed
        self._current_action_desc: str = ""

    # ----------------------------------------------------------------- public

    @property
    def show_name(self) -> str:
        return self._show.name

    @property
    def state(self) -> str:
        return self._state

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_seconds

    @property
    def current_action_description(self) -> str:
        return self._current_action_desc

    @property
    def waiting_description(self) -> str:
        if isinstance(self._wait, _TimeWait):
            if self._wait.until_seconds is not None:
                return f"wait {max(0.0, self._wait.until_seconds - self._elapsed_seconds):.1f}s"
            if self._wait.until_beats is not None:
                return f"wait until beat {self._wait.until_beats:.2f}"
        if isinstance(self._wait, _ChaseWait):
            return f"wait_chase {self._wait.chase!r}"
        if isinstance(self._wait, _GroupWait):
            sel = getattr(self._wait.selector, "describe", lambda: "")()
            return f"wait_group {sel}"
        return ""

    @property
    def keybindings(self):
        return self._show.keybindings

    # --------------------------------------------------------------- controls

    def play(self) -> None:
        # If already running, no-op (idempotent). If paused, this is *not*
        # the same as resume — it's a full restart from the beginning.
        if self._state == "running":
            return
        self._reset_internal()
        self._state = "running"
        log.info("show %r: playing", self._show.name)

    def pause(self) -> None:
        if self._state == "running":
            self._state = "paused"
            log.info("show %r: paused at %.2fs", self._show.name, self._elapsed_seconds)

    def resume(self) -> None:
        if self._state == "paused":
            self._state = "running"
            log.info("show %r: resumed", self._show.name)

    def reset(self) -> None:
        self._reset_internal()
        self._state = "running"
        log.info("show %r: reset", self._show.name)

    def _reset_internal(self) -> None:
        top_iters = -1 if self._show.loop else 1
        self._stack = [_Frame(actions=list(self._show.script), pc=0, iterations_remaining=top_iters)]
        self._wait = None
        self._elapsed_seconds = 0.0

    def seek(self, target_seconds: float, reference_bpm: float | None = None) -> None:
        """Fast-forward replay to the given time position.

        Resets the show, then walks the script with no real-time waits:
        side-effect actions (snap_scene, start_chase, set_bpm, etc.) are
        submitted to the engine, wait durations are accounted by adding
        to a virtual elapsed counter. When that counter would cross
        target_seconds, the in-progress wait is split: its remainder
        becomes the live wait, and tick() picks up from there.

        wait_chase / wait_group are treated as instant during seek (their
        real duration depends on runtime conditions we can't simulate).
        """
        if target_seconds < 0:
            target_seconds = 0.0
        bpm = reference_bpm if (reference_bpm and reference_bpm > 0) else self._clock.bpm
        if not bpm or bpm <= 0:
            bpm = 120.0

        self._reset_internal()
        self._state = "running"

        # Cap iterations defensively against a malformed script.
        max_iter = 200_000
        iter_count = 0
        accumulated = 0.0

        while self._stack and iter_count < max_iter:
            iter_count += 1
            top = self._stack[-1]
            if top.pc >= len(top.actions):
                if top.iterations_remaining == -1:
                    # show.loop = true at the top; one full pass is what
                    # the timeline represents — stop here.
                    break
                top.iterations_remaining -= 1
                if top.iterations_remaining > 0:
                    top.pc = 0
                    continue
                self._stack.pop()
                continue
            action = top.actions[top.pc]
            top.pc += 1

            if isinstance(action, WaitAction):
                if action.seconds is not None:
                    wait_dur = action.seconds
                elif action.beats is not None:
                    wait_dur = action.beats * 60.0 / bpm
                elif action.bars is not None:
                    wait_dur = action.bars * 4.0 * 60.0 / bpm
                else:
                    wait_dur = 0.0
                if accumulated + wait_dur >= target_seconds:
                    # Crossing the target — settle here. The remainder of
                    # this wait becomes the live wait so tick() resumes
                    # naturally.
                    remainder = (accumulated + wait_dur) - target_seconds
                    self._elapsed_seconds = target_seconds
                    if action.seconds is not None or remainder == 0:
                        self._wait = _TimeWait(
                            until_seconds=self._elapsed_seconds + remainder,
                        )
                    else:
                        rem_beats = remainder * bpm / 60.0
                        self._wait = _TimeWait(
                            until_beats=self._clock.beat_position + rem_beats,
                        )
                    log.info(
                        "show %r: seeked to %.2fs (remainder wait %.2fs)",
                        self._show.name, target_seconds, remainder,
                    )
                    return
                accumulated += wait_dur
                continue

            if isinstance(action, (WaitChaseAction, WaitGroupAction)):
                # Runtime-dependent — treat as instant during seek.
                continue

            # Side-effect or LoopAction — let _execute do its thing.
            self._execute(action)
            # _execute might still install a wait for safety, but for the
            # action types remaining here it shouldn't. Clear defensively.
            self._wait = None

        # Reached the end of the script before target.
        self._state = "completed"
        self._elapsed_seconds = accumulated
        self._current_action_desc = "(seeked past end)"
        log.info(
            "show %r: seeked past end (target %.2fs, total %.2fs)",
            self._show.name, target_seconds, accumulated,
        )
        self._current_action_desc = ""

    # ------------------------------------------------------------------ tick

    def tick(self, dt: float) -> None:
        if self._state != "running":
            return
        self._elapsed_seconds += dt

        # Evaluate any active wait first.
        if self._wait is not None:
            if not self._wait_complete():
                return
            self._wait = None

        # Run as many actions as fit in the per-tick budget, OR until we hit a
        # wait, OR until the script ends.
        budget = ACTIONS_PER_TICK_BUDGET
        while budget > 0:
            budget -= 1
            if not self._stack:
                self._state = "completed"
                self._current_action_desc = "(completed)"
                return
            top = self._stack[-1]
            if top.pc >= len(top.actions):
                # End of this frame's action list — loop or pop.
                if top.iterations_remaining == -1:
                    top.pc = 0  # infinite loop
                    continue
                top.iterations_remaining -= 1
                if top.iterations_remaining > 0:
                    top.pc = 0
                    continue
                self._stack.pop()
                continue
            action = top.actions[top.pc]
            top.pc += 1
            self._execute(action)
            if self._wait is not None:
                # An action installed a wait; halt this tick.
                return

    # ------------------------------------------------------------ wait checks

    def _wait_complete(self) -> bool:
        w = self._wait
        if isinstance(w, _TimeWait):
            if w.until_seconds is not None and self._elapsed_seconds >= w.until_seconds:
                return True
            if w.until_beats is not None and self._clock.beat_position >= w.until_beats:
                return True
            return False
        if isinstance(w, _ChaseWait):
            pos_info = self._engine.chase_loop_position(w.chase)
            if pos_info is None:
                # Chase has stopped or never started — treat as completed.
                return True
            pos, length = pos_info
            # If we're past the start position by less than current pos OR we've
            # wrapped (current pos < start pos), one loop has completed.
            wrapped = pos < w.started_at_position - 1e-6
            elapsed_real = time.monotonic() - w.started_at_monotonic
            # Defensive: if wall-clock time exceeds 2x the chase length seconds,
            # treat as done (handles BPM=0 / paused-clock cases).
            if wrapped:
                return True
            # If the chase is beat-anchored and the BPM clock is paused, length
            # is in beats and won't advance — fall back to a coarse wall-clock
            # cap proportional to length (assume ~120 BPM for the cap).
            cap_seconds = max(length * 0.5, length / 2.0)  # crude
            if elapsed_real > cap_seconds * 2:
                return True
            return False
        if isinstance(w, _GroupWait):
            return not self._engine.is_transitioning_in(w.selector)
        return True

    # --------------------------------------------------------------- execute

    def _execute(self, action: Action) -> None:
        self._current_action_desc = _describe_action(action)

        if isinstance(action, SnapSceneAction):
            self._engine.submit("snap_scene", scene=action.scene, fade=action.fade)
        elif isinstance(action, StartChaseAction):
            self._engine.submit("start_chase", chase=action.chase)
        elif isinstance(action, StopChaseAction):
            self._engine.submit("stop_chase", chase=action.chase)
        elif isinstance(action, StopAllChasesAction):
            self._engine.submit("stop_all_chases")
        elif isinstance(action, FireSlotAction):
            self._engine.submit("fire_slot", bank=action.bank, slot_id=action.slot)
        elif isinstance(action, BlackoutAction):
            if action.group is not None:
                self._engine.submit("blackout", group=action.group, fade=action.fade)
            else:
                self._engine.submit("blackout", fade=action.fade)
        elif isinstance(action, ReleaseBlackoutAction):
            self._engine.submit("release_blackout")
        elif isinstance(action, SetValuesAction):
            self._engine.submit(
                "set_values_group",
                group=action.group,
                values=action.values,
                fade=action.fade,
            )
        elif isinstance(action, SetBpmAction):
            self._engine.submit("set_bpm", bpm=action.bpm, source="show")
        elif isinstance(action, LogAction):
            self._engine.submit("log", message=f"[show {self._show.name}] {action.message}")
        elif isinstance(action, WaitAction):
            self._wait = _build_time_wait(action, self._elapsed_seconds, self._clock)
        elif isinstance(action, WaitChaseAction):
            pos_info = self._engine.chase_loop_position(action.chase)
            if pos_info is None:
                # Not running — wait completes immediately, install nothing
                self._wait = None
            else:
                self._wait = _ChaseWait(
                    chase=action.chase,
                    started_at_position=pos_info[0],
                    started_at_monotonic=time.monotonic(),
                )
        elif isinstance(action, WaitGroupAction):
            if not self._engine.is_transitioning_in(action.group):
                self._wait = None
            else:
                self._wait = _GroupWait(selector=action.group)
        elif isinstance(action, LoopAction):
            if action.times > 0:
                self._stack.append(
                    _Frame(actions=list(action.actions), pc=0, iterations_remaining=action.times)
                )
        else:
            self._engine.submit("log", message=f"[show {self._show.name}] unhandled action {type(action).__name__}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_show_length_seconds(show: Show, reference_bpm: float) -> tuple[float, bool]:
    """Total length of `show` assuming a fixed BPM throughout.

    Walks every action, summing wait durations:
    * wait.seconds → seconds directly
    * wait.beats / wait.bars → converted via reference_bpm
    * wait_chase / wait_group → can't be simulated; counted as 0 and
      marks the result as an estimate
    * Loops are unrolled by their declared `times` (top-level
      show.loop = true is treated as 1 — the timeline shows one pass)
    """
    if reference_bpm is None or reference_bpm <= 0:
        reference_bpm = 120.0
    is_estimate = False

    def walk(actions: list[Action]) -> float:
        nonlocal is_estimate
        total = 0.0
        for a in actions:
            if isinstance(a, WaitAction):
                if a.seconds is not None:
                    total += a.seconds
                elif a.beats is not None:
                    total += a.beats * 60.0 / reference_bpm
                elif a.bars is not None:
                    total += a.bars * 4.0 * 60.0 / reference_bpm
            elif isinstance(a, (WaitChaseAction, WaitGroupAction)):
                is_estimate = True
            elif isinstance(a, LoopAction):
                if a.times > 0:
                    total += a.times * walk(list(a.actions))
        return total

    return walk(list(show.script)), is_estimate


def _build_time_wait(
    action: WaitAction, elapsed_seconds: float, clock: BpmClock
) -> _TimeWait:
    if action.seconds is not None:
        return _TimeWait(until_seconds=elapsed_seconds + action.seconds)
    if action.beats is not None:
        return _TimeWait(until_beats=clock.beat_position + action.beats)
    if action.bars is not None:
        # 1 bar = 4 beats (we're not modelling time signatures yet)
        return _TimeWait(until_beats=clock.beat_position + 4.0 * action.bars)
    raise ValueError("wait action has no anchor")


def _describe_action(action: Action) -> str:
    if isinstance(action, SnapSceneAction):
        return f"snap_scene {action.scene}"
    if isinstance(action, StartChaseAction):
        return f"start_chase {action.chase}"
    if isinstance(action, StopChaseAction):
        return f"stop_chase {action.chase}"
    if isinstance(action, StopAllChasesAction):
        return "stop_all_chases"
    if isinstance(action, FireSlotAction):
        return f"fire_slot {action.bank}/{action.slot}"
    if isinstance(action, BlackoutAction):
        return f"blackout{' group' if action.group else ''}"
    if isinstance(action, ReleaseBlackoutAction):
        return "release_blackout"
    if isinstance(action, SetValuesAction):
        return f"set_values {list(action.values.keys())}"
    if isinstance(action, WaitAction):
        if action.seconds is not None:
            return f"wait {action.seconds}s"
        if action.beats is not None:
            return f"wait {action.beats}b"
        if action.bars is not None:
            return f"wait {action.bars}bar"
    if isinstance(action, WaitChaseAction):
        return f"wait_chase {action.chase}"
    if isinstance(action, WaitGroupAction):
        return f"wait_group {action.group.describe()}"
    if isinstance(action, SetBpmAction):
        return f"set_bpm {action.bpm}"
    if isinstance(action, LogAction):
        return f"log {action.message[:40]}"
    if isinstance(action, LoopAction):
        return f"loop ×{action.times}"
    return type(action).__name__
