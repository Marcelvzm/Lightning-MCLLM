# LightningMCLLM

LLM-authored DMX lighting show controller for live performance.

## What it is

A robust, cross-platform (Linux / macOS / Windows) lighting show engine that:

- Plays DMX lightshows out a **Eurolite USB-DMX512 PRO MK2** (or any Enttec-Pro-compatible USB-DMX interface).
- Lets an LLM (Claude) **author and live-edit** shows via MCP — fixtures, scenes, chases, banks — while the show is running.
- Survives crashes by isolating the realtime DMX I/O in its own process. Engine restarts in <500ms; DMX hardware never sees a gap.
- Has a web GUI (open it in any browser on the same network — laptop, phone, iPad) to pick environments, trigger scenes, drive BPM manually or from audio input.

## Architecture

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ supervisor       │──┬──▶│ dmx_io           │──────▶ Eurolite USB-DMX │
│ (parent process) │  │   │ (realtime, slim) │   serial @ 250kbaud
│                  │  ├──▶│ engine           │
│ restarts crashed │  │   │ (scenes, chases) │
│ children in      │  │   └──────────────────┘
│ <500ms           │  └──▶│ web (FastAPI)    │◀── browser GUI
└──────────────────┘      │  + MCP server    │◀── Claude (LLM editor)
                          └──────────────────┘
```

Authoring is file-based (YAML, comments preserved). LLM edits files; engine hot-reloads without dropping output.

## Status

Pre-alpha. Initial build overnight 2026-05-06; major Show-script refactor 2026-05-07. **68/68 tests green**, including a full end-to-end pipeline against a virtual Eurolite Pro on a PTY pseudo-terminal — same `pyserial` code path as production. First hardware-on-stage test is yours to run.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate                    # Windows: .venv\Scripts\activate
pip install -e .
lightning run                                # http://localhost:7777
```

Without hardware connected, the engine runs against an in-memory null DMX adapter; the web GUI works fully. Plug in your Eurolite USB-DMX512 PRO MK2, restart `lightning run`, and the driver auto-detects via FTDI VID 0x0403.

For the watchdog/auto-restart variant: `lightning supervised -- --bpm 128`.

To wire Claude as the LLM editor, install the `[mcp]` extra and configure
Claude Desktop / Code to launch `lightning mcp`. See `technical_details.md`
section 11 for the exact JSON.

## Read this first

* **[`ARCHITEKTUR.md`](ARCHITEKTUR.md)** — wie eine Show programmiert
  wird. Bausteine (Profile → Environment → Scenes → Chases → Banks),
  Voice-Modell, Authoring-Loop, BPM-Clock-Verhalten.
* **[`gui_manual.md`](gui_manual.md)** — wie man die Web-GUI live
  bedient. Bank-Pad, Tastatur-Shortcuts, Chase-Liste, BPM-Tap.
* **[`technical_details.md`](technical_details.md)** — architecture, YAML
  schemas, chase grammar, hardware-setup notes, testing strategy, roadmap.
* **[`llm_instruct.md`](llm_instruct.md)** — authoring guide for any LLM
  (Claude or otherwise) tasked with writing shows through MCP. Reachable
  at runtime via `GET /api/instruct` and via the MCP tool `read_authoring_guide`.
* **[`genre_concepts/`](genre_concepts/)** — per-genre deep-dive design
  proposals (techno, hardtekk, hardstyle, rap_trap, dnb, ambient).
  Reachable at runtime via `GET /api/genre_concept/{name}` and the MCP
  tool `read_genre_concept`.
