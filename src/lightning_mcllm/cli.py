"""Command-line entry points.

    lightning run         single-process: engine + DMX + web GUI in one Python process
    lightning supervised  watchdog wrapper that respawns `lightning run` on crash
    lightning mcp         MCP server over stdio (spawned by Claude Desktop / Code)
    lightning sim         run a virtual Eurolite Pro on a PTY (for testing)
    lightning probe       scan serial ports and try to identify a DMX adapter

Sane defaults: if no Eurolite is plugged in, we use a NullInterface so the
engine still runs end-to-end (good for development on the laptop without
hardware). Set LIGHTNING_NULL_DMX=1 to force-null even if a device is found.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

import click

from lightning_mcllm.config import load_settings
from lightning_mcllm.core.library import (
    list_environments,
    load_fixture_library,
    load_stage,
)
from lightning_mcllm.dmx.enttec_pro import EnttecProInterface, discover_port
from lightning_mcllm.dmx.interface import DmxInterface
from lightning_mcllm.dmx.null import NullInterface
from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.reload import HotReloader
from lightning_mcllm.engine.runtime import Engine

log = logging.getLogger("lightning")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _pick_dmx(force_null: bool, port_override: str | None, baud: int) -> DmxInterface:
    if force_null:
        log.info("LIGHTNING_NULL_DMX set or --null-dmx passed — using NullInterface")
        return NullInterface()
    chosen = port_override or discover_port()
    if chosen is None:
        log.warning("no DMX adapter detected — falling back to NullInterface")
        return NullInterface()
    try:
        iface = EnttecProInterface(chosen, baudrate=baud)
        iface.open()
        if not iface.connected:
            log.warning("could not open %s — falling back to NullInterface", chosen)
            return NullInterface()
        log.info("DMX adapter ready: %s", iface.description)
        return iface
    except Exception as e:  # noqa: BLE001
        log.warning("DMX adapter init failed (%s) — using NullInterface", e)
        return NullInterface()


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="DEBUG-level logging")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """LightningMCLLM — LLM-authored DMX lighting show controller."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)


@main.command()
@click.option("--env", default=None, help="Environment to load (default: first)")
@click.option("--null-dmx", is_flag=True, help="Force NullInterface even if a device is present")
@click.option("--port", default=None, help="Serial port override (e.g. /dev/ttyUSB0, COM4)")
@click.option("--baud", default=None, type=int, help="Serial baud rate (default 250000)")
@click.option("--host", default=None, help="Web bind host")
@click.option("--web-port", default=None, type=int, help="Web port (default 7777)")
@click.option("--bpm", default=120.0, type=float, help="Initial BPM")
@click.option("--audio-bpm", is_flag=True, help="Enable audio-input BPM detection (requires [audio] extras)")
@click.option(
    "--refresh-hz",
    default=None,
    type=int,
    help="DMX frame refresh rate (default 30). Lower (e.g. 20) helps with flaky "
         "Eurolite USB-DMX512 Pro MK2 adapters that flicker at full rate — see "
         "QLC+ forum t=10855.",
)
def run(
    env: str | None,
    null_dmx: bool,
    port: str | None,
    baud: int | None,
    host: str | None,
    web_port: int | None,
    bpm: float,
    audio_bpm: bool,
    refresh_hz: int | None,
) -> None:
    """Single-process: start engine + web GUI."""
    import uvicorn  # noqa: WPS433 — defer import for fast `lightning --help`

    from lightning_mcllm.web.app import create_app

    settings = load_settings()
    bind_host = host or settings.web_host
    bind_port = web_port or settings.web_port
    chosen_baud = baud or settings.serial_baudrate

    envs = list_environments(settings.paths.environments)
    if not envs:
        click.echo(f"No environments found in {settings.paths.environments}", err=True)
        sys.exit(2)
    env_name = env or envs[0]
    if env_name not in envs:
        click.echo(f"Environment {env_name!r} not found. Available: {envs}", err=True)
        sys.exit(2)

    # Load show
    lib, lib_issues = load_fixture_library(settings.paths.fixture_library)
    for w in lib_issues.warnings:
        log.warning("fixture lib: %s", w)
    if lib_issues.errors:
        click.echo("Fixture library errors:", err=True)
        for e in lib_issues.errors:
            click.echo(f"  {e}", err=True)
        sys.exit(2)

    stage, stage_issues = load_stage(settings.paths.environments / env_name, lib)
    for w in stage_issues.warnings:
        log.warning("stage: %s", w)
    if stage is None:
        click.echo(f"Environment {env_name!r} failed to load:", err=True)
        for e in stage_issues.errors:
            click.echo(f"  {e}", err=True)
        sys.exit(2)

    # DMX
    force_null = null_dmx or settings.force_null_dmx
    dmx = _pick_dmx(force_null, port or settings.serial_port, chosen_baud)

    # Engine + clock + hot reload
    clock = BpmClock(bpm=bpm)
    chosen_refresh_hz = refresh_hz or settings.dmx_refresh_hz
    engine = Engine(stage=stage, dmx=dmx, clock=clock, refresh_hz=chosen_refresh_hz)
    engine.start()
    reloader = HotReloader(engine, settings, env_name)
    reloader.start()

    audio_detector = None
    if audio_bpm:
        from lightning_mcllm.audio.beat import AudioBpmDetector
        audio_detector = AudioBpmDetector(clock)
        audio_detector.start()
        if audio_detector.error:
            log.warning("audio BPM disabled: %s", audio_detector.error)

    # Web app
    app = create_app(engine, reloader, settings)

    def _shutdown(*_args) -> None:  # type: ignore[no-untyped-def]
        log.info("shutting down")
        if audio_detector is not None:
            try:
                audio_detector.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            reloader.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            engine.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            dmx.close()
        except Exception:  # noqa: BLE001
            pass

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        uvicorn.run(app, host=bind_host, port=bind_port, log_level="warning", access_log=False)
    finally:
        _shutdown()


@main.command()
@click.option("--restart-cap", default=20, help="Max restarts in --restart-window")
@click.option("--restart-window", default=60.0, help="Window (s) for restart cap")
@click.argument("run_args", nargs=-1)
def supervised(restart_cap: int, restart_window: float, run_args: tuple[str, ...]) -> None:
    """Watchdog wrapper: run `lightning run` as a child, restart on exit.

    Forwards extra arguments after `--` to the child:
        lightning supervised -- --null-dmx --bpm 128
    """
    import subprocess

    cmd = [sys.executable, "-m", "lightning_mcllm.cli", "run", *run_args]
    log.info("supervisor starting: %s", " ".join(cmd))
    history: list[float] = []
    while True:
        proc = subprocess.Popen(cmd)
        try:
            ret = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info("supervisor: child terminated by user")
            return
        log.warning("supervisor: child exited code=%d", ret)
        # If clean exit (code 0), don't restart — the user asked for it.
        if ret == 0:
            log.info("supervisor: child exited cleanly, not restarting")
            return
        now = time.monotonic()
        history.append(now)
        history = [t for t in history if now - t < restart_window]
        if len(history) > restart_cap:
            log.error("supervisor: %d restarts in %.0fs — giving up", len(history), restart_window)
            sys.exit(1)
        log.info("supervisor: restart in 0.5s (%d/%d in %.0fs)",
                 len(history), restart_cap, restart_window)
        time.sleep(0.5)


@main.command()
@click.option("--port", default=None, help="Serial port (default: auto-discover)")
@click.option("--baud", default=None, type=int, help="Baud rate (default 250000)")
def probe(port: str | None, baud: int | None) -> None:
    """Probe serial ports for likely DMX adapters."""
    try:
        from serial.tools import list_ports  # type: ignore[import]
    except ImportError:
        click.echo("pyserial not installed", err=True)
        sys.exit(2)

    ports = list(list_ports.comports())
    if not ports:
        click.echo("No serial ports found.")
        return
    click.echo(f"Found {len(ports)} serial port(s):\n")
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid else "—"
        pid = f"{p.pid:04X}" if p.pid else "—"
        click.echo(f"  {p.device}")
        click.echo(f"    description: {p.description}")
        click.echo(f"    manufacturer: {p.manufacturer or '—'}")
        click.echo(f"    VID:PID:     {vid}:{pid}")
        click.echo(f"    serial:      {p.serial_number or '—'}")
        click.echo()
    chosen = port or discover_port()
    if chosen:
        click.echo(f"Auto-selected: {chosen}")
    else:
        click.echo("No DMX-likely port matched.")


@main.command()
def sim() -> None:
    """Run a virtual Eurolite Pro on a PTY — useful to verify wiring without hardware."""
    from lightning_mcllm.dmx.simulator import EuroliteSimulator

    s = EuroliteSimulator()
    s.start()
    click.echo(f"Virtual Eurolite running. Slave path: {s.slave_path}")
    click.echo("Run another shell with:")
    click.echo(f"    LIGHTNING_SERIAL_PORT={s.slave_path} lightning run")
    click.echo("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
            click.echo(
                f"  frames={s.frames_received}  bytes={s.bytes_received}  "
                f"errors={s.protocol_errors}  last_label={s.last_label}"
            )
    except KeyboardInterrupt:
        click.echo("\nstopping…")
    finally:
        s.stop()


@main.command()
@click.option("--api-url", default="http://127.0.0.1:7777", help="Engine HTTP API base URL")
def mcp(api_url: str) -> None:
    """Run the MCP server (stdio). Spawned by Claude Desktop / Code."""
    from lightning_mcllm.mcp_server.server import run_stdio

    run_stdio(api_url)


if __name__ == "__main__":
    main()
