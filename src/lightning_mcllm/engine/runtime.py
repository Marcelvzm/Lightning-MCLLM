"""Engine main loop.

Runs in its own thread. Owns:

    * active voices
    * active chase runners
    * the shadow universe (the only authoritative DMX state)
    * master dimmer + blackout latch

Single render path: each tick all voices write into the shadow, master is
applied, the result is handed to the DMX interface. Every external mutation
(start chase, snap scene, blackout, set BPM…) goes through a thread-safe
command queue so the render loop never holds a mutex during DMX I/O.

Crash policy: bad chase YAML / scene resolution errors are caught per-action.
A single broken chase cannot stop the engine. Errors are logged and surfaced
in `engine_status()`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from lightning_mcllm.core.banks import BlackoutSlot, ChaseSlot, ReleaseSlot, SceneSlot
from lightning_mcllm.core.library import Stage
from lightning_mcllm.core.selectors import Selector
from lightning_mcllm.dmx.interface import UNIVERSE_SIZE, DmxInterface
from lightning_mcllm.engine.clock import BpmClock, ClockSnapshot
from lightning_mcllm.engine.script import ChaseRunner, FiredAction, make_voice
from lightning_mcllm.engine.voice import Voice

log = logging.getLogger(__name__)

UNIVERSE = 0  # single-universe build for now


def _coerce_selector(value: Any) -> Selector:
    """Accept a Selector, a dict, or a JSON-deserialised dict from IPC and
    return a Selector. Used at the dispatch boundary so external callers can
    pass either form."""
    if isinstance(value, Selector):
        return value
    if isinstance(value, dict):
        return Selector.model_validate(value)
    raise ValueError(f"cannot coerce {value!r} to Selector")


# ---------------------------------------------------------------------------
# Commands (external -> engine)
# ---------------------------------------------------------------------------


@dataclass
class _Cmd:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Status snapshot (engine -> external readers)
# ---------------------------------------------------------------------------


@dataclass
class EngineStatus:
    running: bool
    stage_name: str | None
    bpm: float
    bpm_source: str
    beat_position: float
    master: float
    blackout: bool
    active_chases: list[str]
    active_voice_count: int
    last_frame_nonzero: int
    dmx_connected: bool
    dmx_description: str
    last_errors: list[str]
    tick_rate_hz: float
    actual_dt_ms: float
    show: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine:
    def __init__(
        self,
        stage: Stage | None,
        dmx: DmxInterface,
        clock: BpmClock,
        *,
        refresh_hz: int = 30,
    ):
        self._stage = stage
        self._dmx = dmx
        self._clock = clock
        self._refresh_hz = refresh_hz
        self._period = 1.0 / refresh_hz
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cmd_queue: "queue.Queue[_Cmd]" = queue.Queue()
        # State
        self._voices: list[Voice] = []
        self._chase_runners: dict[str, ChaseRunner] = {}
        self._chase_counter: int = 0
        self._shadow = bytearray(UNIVERSE_SIZE)  # only universe 0 for now
        self._master: float = 1.0
        self._blackout: bool = False
        self._blackout_fade_seconds: float = 0.0
        self._blackout_started_at: float = 0.0
        self._last_errors: list[str] = []
        self._max_errors: int = 16
        self._actual_dt_ms: float = 0.0
        # Lock guards self._stage swap during hot reload
        self._stage_lock = threading.Lock()
        # ShowRunner — at most one show at a time; None means no script active
        self._show_runner = None  # type: ignore[var-annotated]

    # ----------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Engine", daemon=True)
        self._thread.start()
        log.info("engine started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        log.info("engine stopped")

    # ------------------------------------------------------------------- stage

    def replace_stage(self, stage: Stage | None) -> None:
        with self._stage_lock:
            self._stage = stage
            # Drop chase runners; their stage reference is stale.
            self._chase_runners.clear()
            # Drop any active show — its action references may be stale.
            self._show_runner = None
            # Voices keep their captured targets — they'll fade out naturally.

    def stage(self) -> Stage | None:
        with self._stage_lock:
            return self._stage

    # --------------------------------------------------------------- commands

    def submit(self, name: str, **args: Any) -> None:
        self._cmd_queue.put(_Cmd(name, args))

    # ---------------------------------------------------------------- status

    def status(self) -> EngineStatus:
        with self._stage_lock:
            stage = self._stage
            stage_name = stage.name if stage else None
        nonzero = sum(1 for b in self._shadow if b)
        snap: ClockSnapshot = self._clock.snapshot()
        # Show-runner state, if any
        runner = self._show_runner
        if runner is not None:
            show_state = {
                "name": runner.show_name,
                "state": runner.state,
                "elapsed_seconds": runner.elapsed_seconds,
                "current_action": runner.current_action_description,
                "waiting": runner.waiting_description,
            }
        else:
            show_state = None
        return EngineStatus(
            running=self._thread is not None and self._thread.is_alive(),
            stage_name=stage_name,
            bpm=snap.bpm,
            bpm_source=snap.source,
            beat_position=snap.beat_position,
            master=self._master,
            blackout=self._blackout,
            active_chases=list(self._chase_runners.keys()),
            active_voice_count=len(self._voices),
            last_frame_nonzero=nonzero,
            dmx_connected=self._dmx.connected,
            dmx_description=self._dmx.description,
            last_errors=list(self._last_errors[-8:]),
            tick_rate_hz=self._refresh_hz,
            actual_dt_ms=self._actual_dt_ms,
            show=show_state,
        )

    def shadow_snapshot(self) -> bytes:
        return bytes(self._shadow)

    # -------------------------------------------------------------- main loop

    def _run(self) -> None:
        next_tick = time.monotonic()
        last_t = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            dt = now - last_t
            last_t = now
            self._actual_dt_ms = dt * 1000.0
            try:
                self._process_commands()
            except Exception as e:  # noqa: BLE001
                self._record_error(f"command processing: {e}")

            try:
                self._clock.tick()
            except Exception as e:  # noqa: BLE001
                self._record_error(f"clock tick: {e}")

            try:
                self._tick_show_runner(dt)
            except Exception as e:  # noqa: BLE001
                self._record_error(f"show tick: {e}")

            try:
                self._tick_chase_runners(dt)
            except Exception as e:  # noqa: BLE001
                self._record_error(f"chase tick: {e}")

            try:
                self._tick_voices(dt)
            except Exception as e:  # noqa: BLE001
                self._record_error(f"voice tick: {e}")

            try:
                self._render()
            except Exception as e:  # noqa: BLE001
                self._record_error(f"render: {e}")

            try:
                self._send()
            except Exception as e:  # noqa: BLE001
                self._record_error(f"DMX send: {e}")

            # Sleep until next tick, accounting for drift
            next_tick += self._period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                # Use Event.wait so stop() unblocks instantly
                if self._stop.wait(sleep_for):
                    break
            else:
                # We're behind — skip catch-up to avoid runaway
                next_tick = time.monotonic()

    # ---------------------------------------------------------------- commands

    def _process_commands(self) -> None:
        # Drain queue without blocking
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._dispatch(cmd)
            except Exception as e:  # noqa: BLE001
                self._record_error(f"cmd {cmd.name}: {e}")

    def _dispatch(self, cmd: _Cmd) -> None:
        name = cmd.name
        a = cmd.args
        if name == "snap_scene":
            self._cmd_snap_scene(a["scene"], fade=a.get("fade", 0.0), args=a.get("args"))
        elif name == "blackout":
            # With `group`, per-fixture blackout (snap selected channels to 0).
            # Without, global blackout latch (overrides everything in render).
            if a.get("group") is not None:
                self._cmd_blackout_group(_coerce_selector(a["group"]), fade=a.get("fade", 0.0))
            else:
                self._cmd_blackout(fade=a.get("fade", 0.0))
        elif name == "release_blackout":
            self._blackout = False
            self._blackout_fade_seconds = 0.0
        elif name == "start_chase":
            self._cmd_start_chase(a["chase"], args=a.get("args"))
        elif name == "stop_chase":
            self._cmd_stop_chase(a["chase"])
        elif name == "stop_all_chases":
            self._chase_runners.clear()
            self._voices = [v for v in self._voices if not v.key.startswith("chase:")]
        elif name == "set_master":
            self._master = max(0.0, min(1.0, float(a.get("value", 1.0))))
        elif name == "set_bpm":
            self._clock.set_bpm(a["bpm"], source=a.get("source", "manual"))
        elif name == "tap":
            self._clock.tap()
        elif name == "fire_slot":
            self._cmd_fire_slot(a["bank"], a["slot_id"])
        elif name == "set_value":
            uni = int(a.get("universe", 0))
            addr = int(a["address"])
            val = int(a["value"])
            self._add_voice(
                Voice(
                    key=f"override:{uni}:{addr}",
                    targets={(uni, addr - 1): val},
                    duration=0.0,
                )
            )
        elif name == "set_values_group":
            self._cmd_set_values_group(
                _coerce_selector(a["group"]),
                values=a["values"],
                fade=float(a.get("fade", 0.0)),
            )
        elif name == "play_show":
            self._cmd_play_show(a["show"])
        elif name == "pause_show":
            if self._show_runner is not None:
                self._show_runner.pause()
        elif name == "resume_show":
            if self._show_runner is not None:
                self._show_runner.resume()
        elif name == "reset_show":
            if self._show_runner is not None:
                self._show_runner.reset()
        elif name == "stop_show":
            # Drop the runner AND everything it spawned. Just nulling the
            # runner left chase voices ticking forever — confusing UX (user
            # presses Stop, nothing visible changes). Stop chases + release
            # blackout latch + drop the runner. Scene voices are left
            # alone so the last snapped state stays visible until the user
            # explicitly blackouts.
            self._show_runner = None
            self._chase_runners.clear()
            self._voices = [v for v in self._voices if not v.key.startswith("chase:")]
            self._blackout = False
            self._blackout_fade_seconds = 0.0
        elif name == "log":
            self._record_error(str(a.get("message", "")))
        else:
            self._record_error(f"unknown command {name!r}")

    def _cmd_snap_scene(
        self,
        scene_name: str,
        *,
        fade: float = 0.0,
        args: dict[str, Any] | None = None,
    ) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        scene = stage.scenes.get(scene_name)
        if scene is None:
            self._record_error(f"snap_scene: unknown scene {scene_name!r}")
            return
        try:
            rendered = stage.render_scene(scene, args=args)
        except (ValueError, KeyError) as e:
            self._record_error(f"snap_scene {scene_name!r}: {e}")
            return
        v = Voice(
            key=f"scene:{scene_name}",
            targets=dict(rendered.values),
            duration=max(0.0, fade),
        )
        self._add_voice(v)

    def _cmd_blackout_group(self, selector: Selector, *, fade: float = 0.0) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        targets = {ch: 0 for ch in stage.channels_for(selector)}
        if not targets:
            return
        self._add_voice(
            Voice(
                key=f"blackout_group:{selector.describe()}",
                targets=targets,
                duration=max(0.0, fade),
            )
        )

    def _cmd_set_values_group(
        self, selector: Selector, *, values: dict[str, int], fade: float
    ) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        targets = stage.render_inline_values(selector, values)
        if not targets:
            return
        roles_key = ",".join(sorted(values.keys()))
        self._add_voice(
            Voice(
                key=f"set_values:{selector.describe()}:{roles_key}",
                targets=targets,
                duration=max(0.0, fade),
            )
        )

    def _cmd_play_show(self, show_name: str) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        show = stage.shows.get(show_name)
        if show is None:
            self._record_error(f"play_show: unknown show {show_name!r}")
            return
        # Lazy import to avoid circular dependency
        from lightning_mcllm.engine.show_runner import ShowRunner

        # Replace any previous runner — a fresh play resets state
        self._show_runner = ShowRunner(show=show, engine=self, clock=self._clock)
        self._show_runner.play()

    def _cmd_blackout(self, *, fade: float = 0.0) -> None:
        # Use a render-time latch instead of a voice. A voice can be overridden
        # by any newer voice (incl. an active chase that fires while blacked-out
        # — a long-running 4-on-the-floor would punch through). The latch is
        # checked AFTER all voices in render, so chases stay running silently
        # underneath and resume immediately on release_blackout.
        self._blackout = True
        self._blackout_fade_seconds = max(0.0, fade)
        self._blackout_started_at = time.monotonic()

    def _cmd_start_chase(
        self, name: str, *, args: dict[str, Any] | None = None
    ) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        chase = stage.chases.get(name)
        if chase is None:
            self._record_error(f"start_chase: unknown chase {name!r}")
            return
        self._chase_counter += 1
        instance_id = f"chase:{name}:{self._chase_counter}"
        # Stop any previous instance with the same chase name (and clean its voices)
        old_prefixes: list[str] = []
        for k in list(self._chase_runners):
            if k.startswith(f"chase:{name}:"):
                old_prefixes.append(k)
                del self._chase_runners[k]
        if old_prefixes:
            self._voices = [
                v for v in self._voices
                if not any(v.key.startswith(p) for p in old_prefixes)
            ]
        try:
            runner = ChaseRunner(
                chase=chase, stage=stage, instance_id=instance_id, args=args or {}
            )
        except ValueError as e:
            self._record_error(f"start_chase {name!r}: {e}")
            return
        self._chase_runners[instance_id] = runner

    def _cmd_stop_chase(self, name: str) -> None:
        prefixes_dropped: list[str] = []
        for k in list(self._chase_runners):
            if k == name or k.startswith(f"chase:{name}:"):
                prefixes_dropped.append(k)
                del self._chase_runners[k]
        # Remove voices spawned by these chase instances
        if prefixes_dropped:
            self._voices = [
                v for v in self._voices
                if not any(v.key.startswith(p) for p in prefixes_dropped)
            ]

    def _cmd_fire_slot(self, bank_name: str, slot_id: int) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        bank = stage.banks.get(bank_name)
        if bank is None:
            self._record_error(f"fire_slot: unknown bank {bank_name!r}")
            return
        slot = next((s for s in bank.slots if s.id == slot_id), None)
        if slot is None:
            self._record_error(f"fire_slot: bank {bank_name!r} has no slot {slot_id}")
            return
        if isinstance(slot, SceneSlot):
            self._cmd_snap_scene(
                slot.name, fade=slot.fade_seconds, args=slot.args or None
            )
        elif isinstance(slot, ChaseSlot):
            self._cmd_start_chase(slot.name, args=slot.args or None)
        elif isinstance(slot, BlackoutSlot):
            self._cmd_blackout(fade=slot.fade_seconds)
        elif isinstance(slot, ReleaseSlot):
            self._release_voices_for(slot.group)

    # ----------------------------------------------------------------- voices

    def _add_voice(self, voice: Voice) -> None:
        # Replace any voice with the same key (latest wins)
        self._voices = [v for v in self._voices if v.key != voice.key]
        # Capture source values from current shadow
        for key in voice.targets:
            univ, addr = key
            if univ == UNIVERSE and 0 <= addr < UNIVERSE_SIZE:
                voice.sources.setdefault(key, self._shadow[addr])
        self._voices.append(voice)

    def _release_voices_for(self, selector: Selector) -> None:
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return
        affected = stage.channels_for(selector)
        # Drop voices whose targets are entirely within `affected`.
        # Voices touching other channels too are kept (rare edge case; keep simple).
        keep: list[Voice] = []
        for v in self._voices:
            if v.targets.keys() <= affected:
                continue
            keep.append(v)
        self._voices = keep

    def _tick_voices(self, dt: float) -> None:
        # Voices PERSIST after their duration ends: they keep writing their
        # target value each render until they're explicitly replaced (same key)
        # or released (stop_chase / blackout / release action). This matches the
        # mental model of "scenes paint and stay until repainted".
        for v in self._voices:
            v.tick(dt)

    def _tick_show_runner(self, dt: float) -> None:
        if self._show_runner is None:
            return
        try:
            self._show_runner.tick(dt)
        except Exception as e:  # noqa: BLE001
            self._record_error(f"show runner: {e}")
            self._show_runner = None

    # ----------------------------------------------------------- show helpers
    # Used by ShowRunner to evaluate wait_chase / wait_group conditions.

    def chase_loop_position(self, chase_name: str) -> tuple[float, float] | None:
        """Return (current_position_in_loop, total_length) for a running chase
        instance, or None if no chase by that name is active."""
        for key, runner in self._chase_runners.items():
            if not key.startswith(f"chase:{chase_name}:"):
                continue
            length = (
                runner.chase.length_beats
                if runner.chase.beat_anchored
                else runner.chase.length_seconds
            ) or 1.0
            return runner.last_position, float(length)
        return None

    def is_transitioning_in(self, selector: Selector) -> bool:
        """Whether any voice currently in active transition (progress < 1, duration > 0)
        writes channels owned by `selector`. False if no such voice."""
        with self._stage_lock:
            stage = self._stage
        if stage is None:
            return False
        affected = stage.channels_for(selector)
        if not affected:
            return False
        for v in self._voices:
            if v.duration <= 0 or v.elapsed >= v.duration:
                continue
            if any(k in affected for k in v.targets):
                return True
        return False

    # ---------------------------------------------------------- chase runners

    def _tick_chase_runners(self, dt: float) -> None:
        if not self._chase_runners:
            return
        # We need a snapshot of the current shadow to capture sources for new voices
        shadow_snapshot: dict[tuple[int, int], int] = {
            (UNIVERSE, i): self._shadow[i] for i in range(UNIVERSE_SIZE)
        }
        completed: list[str] = []
        for instance_id, runner in self._chase_runners.items():
            try:
                fired, _pos = runner.tick(dt, self._clock)
            except Exception as e:  # noqa: BLE001
                self._record_error(f"chase {instance_id}: {e}")
                completed.append(instance_id)
                continue
            for action in fired:
                self._apply_fired(action, shadow_snapshot)
            if runner.completed:
                completed.append(instance_id)
        for cid in completed:
            self._chase_runners.pop(cid, None)

    def _apply_fired(self, action: FiredAction, shadow_snapshot: dict) -> None:
        if action.release:
            # Drop any voice whose key starts with the release's voice_key
            # (used to release all voices from a chase instance at once).
            self._voices = [v for v in self._voices if not v.key.startswith(action.voice_key)]
            return
        if not action.targets:
            return
        voice = make_voice(action, shadow_snapshot)
        self._add_voice(voice)
        # If this is a snap (zero duration), update the in-tick shadow snapshot
        # so a *subsequent* action in the same step (e.g. fade-from-snap) captures
        # the post-snap value as its source — not the pre-snap state.
        if action.duration <= 0:
            for k, v in action.targets.items():
                shadow_snapshot[k] = int(v)

    # ----------------------------------------------------------------- render

    def _render(self) -> None:
        # Reset shadow each tick — voices are re-evaluated every frame.
        # If we kept the shadow across ticks, voices that finished would never
        # release their channels. Voices "owning" a channel write it every frame.
        new_shadow = bytearray(UNIVERSE_SIZE)
        # Order voices oldest-first so newer voices overwrite older for shared channels
        for v in sorted(self._voices, key=lambda v: v.started_at):
            v.write_to(new_shadow, universe=UNIVERSE)
        # Master dimmer scales all channels uniformly. NOTE: this is a stage-wide
        # gain knob — it scales colour channels, pan/tilt etc. uniformly, which
        # is "wrong" semantically for non-brightness channels. In practice that
        # only matters when master < 1, and if you're rolling master down you're
        # heading toward blackout anyway. Keep it simple.
        if self._master < 1.0:
            scale = self._master
            for i in range(UNIVERSE_SIZE):
                new_shadow[i] = int(new_shadow[i] * scale)
        # Blackout latch — applied AFTER voices so even running chases get
        # silenced. If a fade was requested, ramp the multiplier from 1->0
        # over fade_seconds so chases continue running underneath.
        if self._blackout:
            if self._blackout_fade_seconds > 0:
                t = (time.monotonic() - self._blackout_started_at) / self._blackout_fade_seconds
                if t >= 1.0:
                    new_shadow = bytearray(UNIVERSE_SIZE)
                else:
                    scale = max(0.0, 1.0 - t)
                    for i in range(UNIVERSE_SIZE):
                        new_shadow[i] = int(new_shadow[i] * scale)
            else:
                new_shadow = bytearray(UNIVERSE_SIZE)
        self._shadow = new_shadow

    def _send(self) -> None:
        self._dmx.send(UNIVERSE, bytes(self._shadow))

    # ---------------------------------------------------------------- errors

    def _record_error(self, msg: str) -> None:
        log.warning("engine: %s", msg)
        self._last_errors.append(msg)
        if len(self._last_errors) > self._max_errors:
            self._last_errors = self._last_errors[-self._max_errors :]
