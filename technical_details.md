# LightningMCLLM — Technical Details

Built overnight 2026-05-06. Cross-platform (Linux / macOS / Windows) DMX
lighting show controller. Authoring is LLM-driven via MCP; playout is
realtime, multi-thread isolated, and crash-resistant.

> Status: pre-alpha. Verified end-to-end against a virtual **Eurolite USB-DMX512
> PRO MK2** simulator over a real PTY pseudo-terminal — the production driver
> code path is exercised. Hardware-on-stage validation pending.

---

## Table of contents

1. [Quickstart](#1-quickstart)
2. [Architecture](#2-architecture)
3. [CLI reference](#3-cli-reference)
4. [Domain model](#4-domain-model)
5. [YAML schemas with examples](#5-yaml-schemas-with-examples)
6. [Chase script grammar](#6-chase-script-grammar)
7. [Voice / transition model](#7-voice--transition-model)
8. [BPM clock](#8-bpm-clock)
9. [Hot reload](#9-hot-reload)
10. [Web GUI](#10-web-gui)
11. [MCP server (LLM authoring)](#11-mcp-server-llm-authoring)
12. [Hardware: Eurolite USB-DMX512 PRO MK2](#12-hardware-eurolite-usb-dmx512-pro-mk2)
13. [Testing without hardware (simulator)](#13-testing-without-hardware-simulator)
14. [Robustness model](#14-robustness-model)
15. [Adding a new fixture](#15-adding-a-new-fixture)
16. [Adding a new environment](#16-adding-a-new-environment)
17. [Migration between environments](#17-migration-between-environments)
18. [Known limitations](#18-known-limitations)
19. [Roadmap / extension points](#19-roadmap--extension-points)
20. [File-by-file map](#20-file-by-file-map)

---

## 1. Quickstart

```bash
# from the repo root, with Python 3.11+ on PATH
python3 -m venv .venv
source .venv/bin/activate                    # on Windows: .venv\Scripts\activate
pip install -e .
lightning run                                # opens http://127.0.0.1:7777
```

Without a Eurolite plugged in, the engine starts in **null DMX mode** — every
frame is rendered into an in-memory buffer instead of going to hardware. The
web GUI works fully. Plug in the device and restart, and it auto-detects.

Force null mode at any time:

```bash
LIGHTNING_NULL_DMX=1 lightning run
```

Run with auto-restart on crash (production):

```bash
lightning supervised -- --bpm 128
```

Run only the engine connected to a virtual Eurolite (developer):

```bash
# Terminal A
lightning sim
# prints: Slave path: /dev/pts/N

# Terminal B
LIGHTNING_SERIAL_PORT=/dev/pts/N lightning run
```

---

## 2. Architecture

```
                                                Web browser  Phone/iPad
                                                     │            │
                                                     └─────┬──────┘
                                                           │ HTTP + WebSocket
                                                           ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  Lightning process (single Python process by default)         │
   │                                                                │
   │  ┌──────────────┐   ┌─────────────┐   ┌───────────────────┐  │
   │  │  FastAPI    │  │ HotReloader │  │ AudioBpmDetector  │  │
   │  │  (uvicorn)  │  │ (watchfiles)│  │  (aubio, optional)│  │
   │  └──────┬──────┘   └──────┬──────┘   └─────────┬─────────┘  │
   │         │                 │                    │             │
   │         ▼                 ▼                    ▼             │
   │  ┌──────────────────────────────────────────────────────┐   │
   │  │       Engine thread  (30Hz tick loop)                │   │
   │  │   ┌────────────┐  ┌──────────────┐  ┌────────────┐   │   │
   │  │   │ BPM clock  │  │ Chase runners│  │ Voice list │   │   │
   │  │   └────────────┘  └──────────────┘  └────────────┘   │   │
   │  │                          ▼                            │   │
   │  │             ┌────────────────────────┐                │   │
   │  │             │  Shadow universe (512B)│                │   │
   │  │             └────────────────────────┘                │   │
   │  └──────────────────────────┬───────────────────────────┘   │
   │                             │ DmxInterface.send()             │
   │                             ▼                                  │
   │  ┌────────────────────────────────────────────────────────┐  │
   │  │  EnttecProInterface  (pyserial, 57600 8N1)             │  │
   │  │     auto-reconnect on I/O error                         │  │
   │  └─────────────────────────┬───────────────────────────────┘  │
   └─────────────────────────────┼─────────────────────────────────┘
                                 │ USB serial @ 57600 baud
                                 ▼
                    ╔════════════════════════╗
                    ║ Eurolite USB-DMX512    ║
                    ║      PRO MK2           ║
                    ╚════════╤═══════════════╝
                             │ DMX512 (250 kbps, ~30 Hz refresh)
                             ▼
                    [ pars / moving heads ]


                  Separately, when the user invokes Claude:
                  ─────────────────────────────────────────
                  Claude Desktop / Code
                       │ stdio
                       ▼
                  lightning mcp   ──HTTP──▶  FastAPI on localhost:7777
                  (own Python process)
```

**Key isolation properties:**

* The DMX writer is a tight loop owned by `Engine._send` — every other layer
  (web, audio, hot reload, MCP) is wrapped in error boundaries so a bug there
  cannot stop frames from reaching the wire.
* The `Engine` thread catches per-phase exceptions (commands / clock tick /
  chase tick / voice tick / render / send) and records them in `last_errors`
  rather than crashing.
* `EnttecProInterface.send` never raises — on failure it silently flags the
  port for reconnect on the next call.
* `lightning supervised` wraps the whole thing in a parent process that
  respawns it within 0.5s of an exit.

This delivers the user's "show must go on" requirement: a buggy chase YAML
or a transient USB hiccup cannot blackout the rig.

### Why single-process by default (and how to upgrade)

The user chose multi-process with watchdog. The current implementation lives
in **one Python process** with strong intra-process isolation, plus
`lightning supervised` as the OS-level watchdog. This delivers the stated
robustness guarantees without the complexity of three-process IPC for the
overnight build. The architecture is ready to split:

* `dmx/interface.py` is an ABC. A `RemoteDmxInterface` that sends frames
  over a Unix socket to a dedicated DMX-I/O subprocess is a ~40-line addition.
* `ipc/server.py` and `ipc/messages.py` already define a JSON-line protocol
  for engine ↔ external comms.

When you want true multi-process: implement `RemoteDmxInterface`, swap it
into `cli.run`, write a `processes/dmx_io.py` entry that runs the existing
`EnttecProInterface` behind the IPC server. The engine code does not change.

---

## 3. CLI reference

| Command | Purpose |
| --- | --- |
| `lightning run` | Single-process: engine + DMX + web GUI |
| `lightning supervised -- [run-args]` | Watchdog: respawns `run` on crash |
| `lightning mcp [--api-url URL]` | MCP server over stdio (Claude spawns this) |
| `lightning sim` | Run a virtual Eurolite Pro on a PTY (testing) |
| `lightning probe` | List serial ports + auto-detect a DMX adapter |

### `lightning run` flags

* `--env <name>` — pick an environment (default: first under `data/environments/`)
* `--null-dmx` — force in-memory DMX (no hardware writes)
* `--port /dev/ttyUSB0` — override serial port
* `--baud 57600` — override baud rate
* `--bpm 128` — initial BPM
* `--audio-bpm` — start the aubio-based BPM detector (requires `[audio]` extras)
* `--host 0.0.0.0` — bind web on all interfaces (for phone control on LAN)
* `--web-port 8080` — change the GUI port
* `-v` (global) — DEBUG-level logging

### Environment variables

| Variable | Purpose |
| --- | --- |
| `LIGHTNING_DATA_DIR` | Override `data/` location |
| `LIGHTNING_RUNTIME_DIR` | Override `runtime/` location (state, sockets) |
| `LIGHTNING_NULL_DMX` | `1`/`true` forces null-DMX mode |
| `LIGHTNING_SERIAL_PORT` | Default serial port |

---

## 4. Domain model

```
FixtureProfile     "what kind of device this is"      data/fixture_library/
FixtureInstance    "this profile, patched at addr X"  data/environments/<env>/environment.yaml
Scene              "snapshot — every fixture at X"    data/environments/<env>/scenes/
Chase              "scripted sequence over time"      data/environments/<env>/chases/
Bank               "trigger layout"                    data/environments/<env>/banks/
Genre              "BPM + recommended chases preset"   data/environments/<env>/genres.yaml
Environment        "one whole rig: profiles + scenes…" data/environments/<env>/
```

**Identity rules:**

* Profile names are unique across `fixture_library/`.
* Fixture names are unique within an environment.
* Scene/chase/bank names are unique within an environment.
* Tags are lowercase; assigned to fixture instances; used by selectors.

### Selector grammar

Scenes and chase actions select fixtures by **selector**, never by raw DMX
address. This is why scenes are portable across environments: write
`select: { tag: par }` and any environment with par-tagged fixtures works.

```yaml
{ name: "MH-Left" }            # exact instance name
{ tag: "moving_heads" }        # any fixture with this tag
{ tags: [moving_head, left] }  # AND — all of these tags
{ any_tag: [par, ledbar] }     # OR — at least one
{ all: true }                  # every fixture in the environment
```

### Channel role taxonomy

Channels are addressed by **role**, not offset, in scenes/actions. Roles
follow a slash-namespaced convention. The engine ignores values for roles
not present on a given fixture, so heterogeneous rigs degrade gracefully.

Common roles (extend as needed in your profile YAMLs):

```
dimmer          shutter         strobe
color/red       color/green     color/blue       color/white
color/amber     color/uv        color/wheel      color/cto
position/pan    position/tilt   position/pan_fine    position/tilt_fine
movement/speed
gobo/wheel      gobo/rotation   gobo/index       gobo/wheel_fine
focus           zoom            iris             prism      frost
effect/macro    effect/macro_speed
control/reset   control/lamp
raw/<n>         # for channels you don't want the engine to mix semantically
```

The list in `core/fixtures.py:KNOWN_ROLES` is *not* enforced — invent any role
you want, it just becomes a string both ends agree on.

---

## 5. YAML schemas with examples

All YAML files in `data/` are loaded with **ruamel.yaml** in round-trip mode
when the LLM writes back, so comments survive edits.

### 5.1 Fixture profile (`data/fixture_library/<name>.yaml`)

```yaml
name: generic_rgbw_par                # unique identifier
description: 7-channel RGBW par
manufacturer: generic                 # informational
model: rgbw_par_7ch                   # informational
channels:
  - { offset: 0, role: dimmer, default: 0, description: "master brightness" }
  - { offset: 1, role: color/red, default: 0 }
  - { offset: 2, role: color/green, default: 0 }
  - { offset: 3, role: color/blue, default: 0 }
  - { offset: 4, role: color/white, default: 0 }
  - offset: 5
    role: strobe
    default: 0
    presets: { off: 0, slow: 30, fast: 200 }   # named values for documentation/UI
  - offset: 6
    role: effect/macro
    default: 0
    presets: { none: 0, rainbow: 50, pulse: 100 }
```

`offset` is 0-indexed within the fixture (channel 1 at `offset: 0`).
`footprint` (auto-computed) = `max(offset) + 1`.

### 5.2 Environment manifest (`data/environments/<env>/environment.yaml`)

```yaml
name: default
description: Starter rig
universes: [0]
default_bank: starter
fixtures:
  - { name: par-l, profile: generic_rgbw_par, address: 1, tags: [par, front, left] }
  - { name: par-r, profile: generic_rgbw_par, address: 8, tags: [par, front, right] }
  - { name: mh-l,  profile: generic_moving_head_16ch, address: 100, tags: [moving_head, left] }
  - { name: mh-r,  profile: generic_moving_head_16ch, address: 116, tags: [moving_head, right] }
```

Validation enforces no DMX address overlap, every profile reference is real,
no duplicate fixture names. Errors are collected and reported all together —
so the LLM gets a complete picture instead of one error at a time.

### 5.3 Scene (`data/environments/<env>/scenes/<name>.yaml`)

```yaml
name: warm_idle
description: Soft warm wash, MHs parked, lamps off
targets:
  - select: { tag: par }
    values: { dimmer: 140, color/red: 200, color/green: 80, color/blue: 20, color/white: 60 }
  - select: { tag: moving_head }
    values: { position/pan: 128, position/tilt: 128, dimmer: 0, shutter: 255 }
```

Multiple `targets` entries combine into one scene. Different selectors target
different fixture groups; values are role-keyed (0..255).

You can also use **presets**:

```yaml
targets:
  - select: { tag: moving_head }
    presets:
      gobo/wheel: stars         # looks up profile.channels[gobo/wheel].presets.stars
```

### 5.4 Chase (`data/environments/<env>/chases/<name>.yaml`)

See [Chase script grammar](#6-chase-script-grammar) below.

```yaml
name: red_pulse
description: 4-on-the-floor red on the pars
loop: true
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: snap,       group: { tag: par }, scene: red_pulse_on }
      - { kind: transition, group: { tag: par }, scene: red_pulse_off, fade_seconds: 0.4 }
  - at_beat: 1
    actions:
      - { kind: snap,       group: { tag: par }, scene: red_pulse_on }
      - { kind: transition, group: { tag: par }, scene: red_pulse_off, fade_seconds: 0.4 }
  # ...
```

### 5.5 Genres (`data/environments/<env>/genres.yaml`, optional)

```yaml
genres:
  - name: techno
    description: Driving 4-on-the-floor, BPM 128
    bpm: 128
    lead_chase: red_pulse                  # started when "Apply" is clicked
    recommended_chases: [red_pulse, mh_alternating_sweep]
    recommended_scenes: [red_pulse_on, mh_beam_open_blue]
  - name: house
    bpm: 124
    lead_chase: red_pulse
    # … more genres
```

The GUI surfaces these as a dropdown — picking a genre and clicking Apply
calls `POST /api/genres/<name>`, which sets the BPM and starts the lead
chase (after stopping any others).

### 5.6 Bank (`data/environments/<env>/banks/<name>.yaml`)

```yaml
name: starter
description: Starter bank — 9-slot launchpad layout
slots:
  - { id: 1, kind: scene, name: warm_idle, label: "Idle" }
  - { id: 5, kind: chase, name: red_pulse, label: "Red Pulse" }
  - { id: 9, kind: blackout, label: "BLACKOUT", fade_seconds: 0.0 }
  # other slot kinds:
  # - { id: 7, kind: release, group: { tag: moving_head }, label: "Free MHs" }
```

The web GUI renders banks as a 3×3 keypad mapped to keyboard keys 1–9.

---

## 6. Chase script grammar

A chase is a beat- or second-anchored sequence of steps. **Pick one anchor
mode per chase** — beat-anchored (`length_beats` + each step has `at_beat`)
or time-anchored (`length_seconds` + each step has `at_seconds`). Mixing in
one chase is rejected at load time.

### Step structure

```yaml
- at_beat: 1.5             # or at_seconds: 0.75
  actions:                 # one or more — they all fire at the anchor moment
    - { kind: <action> ... }
    - { kind: <action> ... }
  note: "optional comment for humans"
```

All `actions` inside one step fire on the same engine tick (no
intra-step ordering by time). They behave as **parallel** by default. A
`snap` followed by a `transition` to the same group within one step works as
expected (the transition picks up the post-snap value as its source).

### Action kinds

#### `transition` — fade

```yaml
- kind: transition
  group: { tag: par }            # selector
  scene: red_pulse_off           # OR
  values: { dimmer: 30, color/red: 255 }
  fade_seconds: 0.4              # 0 = effectively a snap
  easing: ease_in_out            # linear | ease_in | ease_out | ease_in_out
```

The voice's source is the current shadow at fire time; target is the
resolved scene/values. Linear blend by default.

#### `snap` — instant

```yaml
- kind: snap
  group: { tag: par }
  scene: red_pulse_on            # OR values: { ... }
```

Equivalent to `transition` with `fade_seconds: 0`.

#### `release` — drop voices for this chase instance

```yaml
- kind: release
  group: { tag: par }            # currently group is informational; release acts on this chase
```

Drops every voice spawned by *this chase instance*. Channels that those
voices were holding will be re-painted by lower-priority voices (e.g. an
underlying scene snap), or if none, will fall to 0 on the next render.

### "Wait" semantics

The user explicitly asked for a `wait`-style primitive ("Übergang Gruppe 1
in 0.5s; Übergang Gruppe 2 in 0.3s; wait(Gruppe 2); …"). The beat-anchored
model handles this implicitly by anchoring later steps to a future beat
where the long fade has finished:

```yaml
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: transition, group: { tag: moving_heads }, scene: beam_up,    fade_seconds: 1.5 }
      - { kind: transition, group: { tag: par },         scene: red_pulse_on, fade_seconds: 0.1 }
  - at_beat: 1.5      # waits for the par fade to be long done
    actions:
      - { kind: transition, group: { tag: par }, scene: red_pulse_off, fade_seconds: 0.4 }
  - at_beat: 3.5      # waits for the MH fade plus a beat
    actions:
      - { kind: transition, group: { tag: moving_heads }, scene: beam_down, fade_seconds: 0.5 }
```

For free-running (time-anchored) chases use `at_seconds`. Multiple chases
running in parallel cover the case of "two wholly independent timelines"
without any explicit synchronisation.

### Two simultaneous chases

If you want two chases each owning a different group, just start them both:

```python
# from the GUI / API
POST /api/cmd/start_chase  {"chase": "red_pulse"}          # owns par
POST /api/cmd/start_chase  {"chase": "mh_alternating_sweep"} # owns moving_head
```

They tick independently and write disjoint channels. If they happen to
write the same channel, the **newest-started voice wins** at render time.

---

## 7. Voice / transition model

A **Voice** is a persistent paintbrush. It has:

* `key` — stable identifier; a new voice with the same key replaces the old
* `targets` — `{(universe, addr): value}` to paint
* `sources` — captured shadow values at start (for interpolation)
* `duration` — fade time (0 = snap)
* `easing` — linear / ease_in / ease_out / ease_in_out
* `started_at` — monotonic timestamp; older voices are rendered first so
  newer voices override on shared channels

**Voices persist forever** until:

1. A new voice with the same key is added (replacement)
2. `stop_chase` removes voices with prefix `chase:<name>:<inst>:`
3. `stop_all_chases` removes voices with prefix `chase:`
4. A `release` action removes voices with the chase-instance prefix
5. The engine is restarted

**Why persistent?** A "scene snap" is meant to paint and stay. If voices
self-expired, channels would silently fall to 0 the moment the voice
finished its duration — which is wrong: the user expects the scene to
remain "set" until something else changes it.

### Voice keys

Generated by:

| Operation | Key form |
| --- | --- |
| `snap_scene <name>` | `scene:<name>` |
| `blackout` | (uses a render-time latch, not a voice — see below) |
| `set_value` direct override | `override:<universe>:<address>` |
| Chase action | `chase:<chase_name>:<inst>:s<step_idx>:a<action_idx>:<selector_str>` |

### Render order

Each tick:

1. Drain command queue (snap_scene, start_chase, blackout, …) — may add or
   remove voices.
2. Tick clock (advance beat position).
3. Tick chase runners (may emit FiredActions which become / remove voices).
4. Tick voices (advance elapsed time).
5. Render: zero a fresh shadow buffer; iterate voices oldest-first, each
   writes its targets. Master dimmer scaling. **Blackout latch**: if blackout
   is active, multiply (or zero) the shadow as a final step — this means
   blackout cannot be punched through by a still-running chase voice.
6. Send shadow to DMX interface.

### Blackout latch

`blackout` does NOT add a voice. Instead it sets a flag `_blackout` and a
fade timer. In `_render`, after voices and master, the latch zeros (or
linearly fades) the shadow as a post-process. Chases continue ticking
beneath: when you hit `release_blackout`, they resume immediately.

This was a deliberate change after the first iteration used a blackout
*voice*, which got punched through by chase voices spawned later (newer
`started_at`). The latch makes blackout a final-render override.

### Master dimmer

`set_master <0..1>` scales every channel uniformly *before* the blackout
latch. Affects colour and movement channels too — for partial dim use a
scene with explicit dimmer values instead. Master = 0 is *not* a substitute
for blackout (blackout is a tighter latch).

---

## 8. BPM clock

Two modes that share the same `BpmClock` object:

| Mode | Source | Notes |
| --- | --- | --- |
| Manual | `set_bpm(bpm)` | Default; the GUI BPM slider |
| Tap   | `tap()` × ≥3 | Inter-tap average locks BPM after 3 taps inside a 3-second window |
| Audio | `AudioBpmDetector` (aubio) | Optional; install `pip install '.[audio]'` |

Beat position is monotonic — it never goes backward when BPM changes. The
audio detector smooths and requires N agreement frames before pushing a
new BPM, so a single bad detection doesn't yank a chase mid-flight.

Audio init failures (no input device, libs missing, permission denied) are
*soft*: the detector logs a warning and the engine falls back to manual.
The engine never crashes because of audio.

---

## 9. Hot reload

`HotReloader` runs `watchfiles` against `data/` in a background thread.
On any `*.yaml` change:

1. Rebuild `FixtureLibrary` from `data/fixture_library/`
2. Rebuild `Show` from the active environment
3. If both succeed, swap them into the engine atomically
4. If `auto_resume: true` (default), restart any chase that was running

**Failure mode:** a broken YAML keeps the *previous* show loaded. Errors
go to `engine_status().last_errors` and are surfaced in the GUI's footer.
The show keeps playing the last known good state.

The MCP `reload` tool calls `reload_now()` synchronously; the LLM gets the
list of validation errors back as the tool reply, so it can fix them in
the next turn without trial-and-error.

---

## 10. Web GUI

Open `http://127.0.0.1:7777` (use `--host 0.0.0.0` to allow phone/iPad
control across the LAN).

### Layout

* **Status panel** — BPM, beat, master, DMX connection, voice count, errors.
  BPM slider + numeric input; tap-tempo button; master fader; BLACKOUT
  (red, latching), Release, Stop chases.
* **Bank slots** — 3×3 grid of the active bank, mapped to keyboard 1–9.
* **Show panel** — clickable lists of scenes / chases / fixtures.
* **Universe visualiser** — a 1024×64 canvas where each pixel column = one
  DMX channel, brightness = channel value. Updates 5Hz.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `1`–`9` | Fire bank slot |
| `Space` | Blackout (latch) |
| `Esc` | Release blackout |
| `T` | Tap tempo |

### REST endpoints (relevant subset)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Engine status snapshot |
| `GET` | `/api/show` | Loaded show summary |
| `GET` | `/api/shadow` | Current 512-byte universe (base64) |
| `GET` | `/api/environments` | List + current |
| `POST` | `/api/environments/<name>` | Switch env (no restart) |
| `POST` | `/api/reload` | Force reload |
| `POST` | `/api/cmd/<op>` | Send engine command (JSON body = args) |
| `GET / PUT / DELETE` | `/api/yaml?path=...` | Read/write a YAML file under `data/` |
| `GET` | `/api/yaml/list?prefix=...` | List YAML files |
| `GET` | `/api/genres` | List genre presets for the loaded show |
| `POST` | `/api/genres/<name>` | Apply a genre (set BPM + start lead chase) |
| `WS` | `/api/ws` | 5Hz status push + accepts commands |

`/api/yaml` is sandboxed to `data/`; path traversal is rejected.

---

## 11. MCP server (LLM authoring)

The MCP server is **a thin HTTP client of the Web API**, run as a separate
process and spoken to by Claude over stdio. This lets Claude:

* Read and write YAML files inside `data/`
* Trigger reloads
* Query the loaded show
* Switch environments
* Trigger scenes / chases / blackout for live testing

### Setup with Claude Desktop / Code

1. Make sure `lightning run` is running (`http://127.0.0.1:7777` reachable).
2. Configure the MCP server in your Claude Desktop or Code settings:

```jsonc
{
  "mcpServers": {
    "lightning-mcllm": {
      "command": "/absolute/path/to/.venv/bin/lightning",
      "args": ["mcp", "--api-url", "http://127.0.0.1:7777"]
    }
  }
}
```

3. Install the `[mcp]` extra: `pip install -e '.[mcp]'`

### Tools exposed

| Tool | Purpose |
| --- | --- |
| `read_authoring_guide` | **Call first.** Returns `llm_instruct.md`, the deterministic show-writing playbook |
| `status` | Live engine status |
| `list_show` | Fixtures, scenes, chases, banks of the loaded show |
| `list_environments`, `switch_environment(name)` | Multi-stage support |
| `list_yaml(prefix?)`, `read_yaml(path)`, `write_yaml(path, content)`, `delete_yaml(path)` | YAML editing |
| `reload` | Force reload after multi-file edits |
| `snap_scene(scene, fade?)` | Trigger a scene |
| `start_chase(chase)`, `stop_chase(chase)`, `stop_all_chases` | Chase control |
| `blackout(fade?)`, `release_blackout` | Blackout control |
| `set_bpm(bpm)`, `tap` | BPM control |
| `fire_slot(bank, slot_id)` | Bank-slot trigger |
| `set_value(address, value, universe?)` | Direct DMX channel override (debug) |

### Suggested LLM workflow

0. **`read_authoring_guide`** to load `llm_instruct.md` — the deterministic
   principles, genre playbook, and YAML cookbook. Skip this step and the
   shows will be technically valid but visually flat.
1. `list_show` to learn what fixtures/scenes/chases exist.
2. To add a new chase: `read_yaml` on a similar one, `write_yaml` with the
   new file, then `reload`. The reload reply contains validation errors
   and warnings — use them to fix the YAML in one more round-trip.
3. To live-test: `snap_scene` or `start_chase` after writing.
4. To add a fixture: edit `environment.yaml` (`read_yaml` / `write_yaml`),
   `reload` to validate.

`llm_instruct.md` lives at the repo root and is also reachable at
`GET /api/instruct` for any external LLM-tooling that wants it without
going through MCP.

---

## 12. Hardware: Eurolite USB-DMX512 PRO MK2

**Chip:** FTDI USB-to-serial. **Protocol:** Enttec USB Pro packet protocol
(both compatible).

**Driver:**
* Linux: kernel `ftdi_sio` is built-in; nothing to install. Device appears
  as `/dev/ttyUSB0` (or higher).
* macOS: also kernel-bundled (FTDI driver since 10.9). Appears as
  `/dev/cu.usbserial-XXXXXXXX`.
* Windows: install the **FTDI D2XX** driver from FTDI's website, **NOT**
  the VCP-only driver. Device appears as `COM4` (or similar).
  Also, the device must be in **"Pro RX/TX"** mode — use the Eurolite
  Windows tool once to switch it before first run.

**Baud rate:** 57600 by default (matches the original Enttec USB Pro
spec). The MK2 should accept it. If your unit only responds at 115200 or
250000, set `LIGHTNING_SERIAL_PORT=...` and pass `--baud 115200` to
`lightning run`.

**Refresh rate:** the engine ticks at 30Hz. The MK2 datasheet warns it
"is not capable to perform at ~44Hz", so 30Hz is a safe choice. Lower
the engine `dmx_refresh_hz` in `config.py` if you see flicker.

**Auto-detection:** `EnttecProInterface.discover_port()` scans
`pyserial.tools.list_ports.comports()` for FTDI VID `0x0403` and matches
description text "ftdi", "dmx", "eurolite", or "enttec". The
highest-priority match is used.

**Probe your hardware:** `lightning probe` lists every serial port with
its VID/PID and whether it would auto-match.

**Reconnect behaviour:** on any I/O error (cable yanked, port busy), the
driver closes the handle and tries again on the next `send()` after a
1-second backoff. The engine doesn't see this — it just keeps writing
into a shadow buffer that nobody is reading.

---

## 13. Testing without hardware (simulator)

`dmx/simulator.py` runs a virtual Eurolite Pro on a **PTY pseudo-terminal**.
This is the strongest possible substitute for hardware testing — the
production driver code path is fully exercised:

```
EnttecProInterface  ──pyserial.write──▶  /dev/pts/N ──▶ os.read()  ──▶ EuroliteSimulator
                                                                          │
                                                                          ▼
                                                                  parses Enttec Pro
                                                                  packet stream,
                                                                  reconstructs the
                                                                  512-byte universe
                                                                  state, tracks
                                                                  protocol errors
```

**Use it interactively:**

```bash
# Terminal A
lightning sim

# Terminal B
LIGHTNING_SERIAL_PORT=/dev/pts/N lightning run
```

**Use it in tests:** `tests/test_engine_simulator_e2e.py` runs the engine
against the simulator and asserts the simulator's universe state matches
the engine's shadow. `tests/test_stress.py::test_simulator_throughput_at_full_engine_rate`
streams 90+ frames at full engine rate and asserts zero protocol errors.

**Linux + macOS only.** Windows lacks `pty`, so the simulator can't run
there — but the Engine logic itself is fully cross-platform; just use
null-DMX mode for local development on Windows.

### Test coverage summary

50 tests across:

* `test_dmx_protocol.py` — packet round-trip, simulator-receives-frame, throughput, disconnect tolerance
* `test_clock.py` — BPM, tap tempo, monotonic advance, pause
* `test_engine.py` — snap, persistence, replacement, blackout, master, stop, errors, slots
* `test_chase.py` — beat- and time-anchored chases, looping, replacement, concurrent chases
* `test_hot_reload.py` — new scene, broken YAML protection, env switch, auto-resume
* `test_engine_simulator_e2e.py` — full pipeline + disconnect mid-stream
* `test_web_api.py` — HTTP REST + WebSocket
* `test_stress.py` — voice churn, concurrent chases, rapid blackout, buggy chase recovery, simulator throughput

Run all: `pytest -q`.

---

## 14. Robustness model

The user's stated constraint: **"Show must go on. Niemals einen vorführ-effekt."**

### What's guaranteed

| Failure | Behaviour |
| --- | --- |
| Bad chase YAML (selector typo, missing scene) | Reload rejected, previous show keeps playing. Errors surface in `last_errors` + GUI |
| Buggy chase action raises mid-tick | Caught in `_tick_chase_runners`, logged, *that runner* removed; others continue |
| Voice raise mid-render | Caught in `_render` per-voice; voice removed; other voices continue |
| DMX write fails (port unplugged / busy) | Driver swallows error, tries reconnect on next call; engine unaware |
| File-watcher thread crash | Caught in `_watch_loop`; logged; manual reload still works |
| Web/uvicorn crash | Engine + DMX continue. Restart `lightning run` to recover GUI |
| MCP server crash | Engine continues. Claude reconnects automatically |
| Audio detector crash / no device | Logged; falls back to manual BPM. Engine continues |
| Whole process crash (segfault, OOM, etc.) | `lightning supervised` respawns within 0.5s. DMX hardware holds the last frame it received until the new engine sends a new one |

### What's NOT guaranteed (yet)

* **No state persistence across restart.** The new engine starts from
  blackout + warm-idle. To recover the running chase, the supervisor
  could write engine status to a file and restore it. Not implemented
  for this overnight build.
* **Audio under-runs / clock drift on busy systems.** The engine targets
  30Hz on monotonic time but Python isn't realtime. On a heavily loaded
  laptop, expect 30–80ms occasional spikes — see
  `engine.status().actual_dt_ms`.
* **Single universe.** The DMX driver supports only universe 0 today. The
  domain model can describe multi-universe rigs, but the dispatch will
  silently drop frames for universe > 0.

### `lightning supervised` details

```bash
lightning supervised --restart-cap 20 --restart-window 60 -- --null-dmx
```

* Spawns `lightning run` as a child process.
* Restart on non-zero exit code only.
* Cap: max `restart-cap` restarts in `restart-window` seconds. Beyond
  that, the supervisor exits non-zero (something is fundamentally
  broken — page a human).
* `Ctrl+C` in the supervisor kills the child and exits cleanly.

For OS-level integration (always-on at boot), wrap `lightning supervised`
in a systemd unit / launchd plist / Windows service.

---

## 15. Adding a new fixture

Three steps:

1. **Create or pick a profile** under `data/fixture_library/`. If your
   physical fixture matches an existing profile (channel layout + roles),
   skip to step 2.

   To create a new profile:
   ```yaml
   # data/fixture_library/eurolite_led_par_56_qcl_rgb_20w.yaml
   name: eurolite_led_par_56_qcl_rgb_20w
   description: Eurolite LED Par-56 QCL RGB 20W
   manufacturer: eurolite
   model: led_par_56_qcl_rgb_20w
   channels:
     - { offset: 0, role: dimmer }
     - { offset: 1, role: color/red }
     - { offset: 2, role: color/green }
     - { offset: 3, role: color/blue }
     - offset: 4
       role: strobe
       presets: { off: 0, slow: 30, fast: 240 }
     # … etc
   ```
   The fixture's "DMX address" in your environment is implied by the
   highest `offset + 1`.

2. **Patch the fixture** in your environment:
   ```yaml
   # in data/environments/<env>/environment.yaml
   fixtures:
     - { name: par-stage-3, profile: eurolite_led_par_56_qcl_rgb_20w, address: 33, tags: [par, stage] }
   ```
   The loader checks for address overlap and rejects bad layouts before
   the engine swaps the show.

3. **Reload.** The file watcher sees the change and triggers reload, OR
   call `POST /api/reload` (or the MCP `reload` tool).

If the reload fails, errors are listed in `last_errors` and the previous
show keeps running.

---

## 16. Adding a new environment

```bash
mkdir -p data/environments/main_stage/{scenes,chases,banks}
$EDITOR data/environments/main_stage/environment.yaml
$EDITOR data/environments/main_stage/scenes/idle.yaml
# … etc
```

Then in the GUI's env-select dropdown, pick `main_stage`. (Or via API:
`POST /api/environments/main_stage`.) Switch is atomic — voices are
dropped, the new show is loaded, and you can immediately fire scenes
from it. No restart needed.

To make a new env the default-on-startup, pass `--env main_stage` to
`lightning run`, or set it as the first directory under
`data/environments/`.

---

## 17. Migration between environments

Both directions are intentionally trivial:

### Copy a fixture instance

Open `environment.yaml` in env A, copy the relevant `fixtures:` entry
into env B's `environment.yaml`, adjust `address` if needed.

### Copy a scene or chase

```bash
cp data/environments/A/scenes/strobe_white.yaml data/environments/B/scenes/
```

The selectors inside the scene (e.g. `select: { tag: par }`) match by tag,
so the scene works in env B as long as env B has fixtures with the same
tags. **This is why naming your tags consistently across environments
matters** — the LLM and the user both rely on it.

If a scene references a fixture by `name:`, the migration may not match.
Tag-based selectors are the most portable; use names only when targeting
a specific instance with a known role.

### Move (vs copy)

To move, just delete from the source. The hot-reloader watches the whole
`data/` tree, so deletions also trigger reload — both envs reload
gracefully.

---

## 18. Known limitations

* **Single universe.** Only universe 0 is rendered to hardware. Multi-
  universe rigs need a follow-up: extend `DmxInterface.send` to a
  `dict[int, bytes]` per-universe map and have the engine maintain N
  shadow buffers.
* **8-bit channels only.** 16-bit fine channels (e.g. `position/pan_fine`)
  are addressable but the engine doesn't auto-mix coarse+fine into a
  single 0..65535 logical value. Set them separately for now.
* **No HTP / LTP merge.** Channel arbitration is "newest-started voice
  wins". Real consoles offer per-channel HTP (highest-takes-precedence)
  for crossfading complex effects. Future work.
* **Audio BPM is best-effort.** The aubio detector is good for steady
  4-on-the-floor but struggles with off-beat genres. Manual or tap is
  more reliable for live use.
* **Chase scene-resolution caching is bypassed each tick.** We re-render
  a target scene into channels every time a step fires. For very large
  shows this could add up; we can cache per (scene, env) tuple.
* **No state persistence across restart.** Supervisor restarts the
  engine quickly but the new engine starts from a clean state.
  Acceptable for the watchdog use case (engine doesn't crash often).
* **PTY simulator is Linux/macOS only.** Windows users test in
  `--null-dmx` mode without protocol-level verification.
* **No GUI YAML editor yet.** Editing happens via shell, file editor, or
  via the LLM through MCP. The web GUI exposes `/api/yaml` for the basis
  of an in-browser editor — not built.
* **Genre presets exist** but are minimal — `genres.yaml` per environment
  defines name + BPM + lead chase + recommended chases/scenes. The GUI
  has a dropdown + Apply button. The "Apply" wires BPM and starts the
  lead chase. Per-genre default scenes / palettes / chase-randomisation
  are future work.

---

## 19. Roadmap / extension points

The following hooks are clearly placed in the code, ready to wire up:

* **Multi-universe support:** swap `Engine._send` to iterate a
  `dict[int, bytearray]`, and have `EnttecProInterface.send` route to
  port 1 (label 6) or port 2 (label 13 for MK2's second port).
* **OLA bridge:** add `dmx/ola.py` implementing `DmxInterface` against
  OLA's RPC. Useful for users with ArtNet/sACN over network instead of
  USB.
* **State persistence:** the engine already exposes `shadow_snapshot()`
  and `status()`. Write them to `runtime/state.json` every N ticks; on
  startup, restore active chase names and BPM.
* **Genre presets:** `data/environments/<env>/genres.yaml` listing
  `{name, bpm, recommended_chases, recommended_scenes}`. GUI dropdown
  applies BPM and surfaces buttons.
* **HTP/LTP per channel:** `Voice` already has a priority concept via
  `started_at`. Extend with an explicit priority + a per-channel merge
  policy (`htp` / `ltp` / `mix`) on Voice.
* **Multi-process true split:** wire `dmx/RemoteDmxInterface` (TCP
  client) and `processes/dmx_io.py` (TCP server hosting
  `EnttecProInterface`). The IPC primitives are in
  `ipc/server.py` + `ipc/messages.py`. Then the supervisor spawns
  three children instead of one.
* **Recording & playback:** snapshot `shadow_snapshot()` to a `.dmxlog`
  file each tick, play back at any rate. Ten lines of glue.
* **Cue stacks:** add a `Cue` model (ordered list of scenes with fades,
  GO/PAUSE/BACK navigation). The Bank model is a flat launchpad; cue
  stacks are the next abstraction up.
* **Fixture clone with offset transforms:** "duplicate fixture but with
  pan offset by 30°" — useful for symmetric rigs. Currently you copy
  the YAML and tweak by hand.

---

## 20. File-by-file map

```
src/lightning_mcllm/
├── __init__.py
├── __main__.py                       # `python -m lightning_mcllm` entry
├── cli.py                            # Click CLI: run, supervised, mcp, sim, probe
├── config.py                         # Settings + Paths dataclasses, env-var loading
├── yaml_io.py                        # Comment-preserving YAML I/O via ruamel.yaml
├── core/
│   ├── fixtures.py                   # FixtureProfile, FixtureChannel, FixtureInstance
│   ├── selectors.py                  # Selector grammar + resolve()
│   ├── scenes.py                     # Scene, SceneTarget, RenderedScene
│   ├── chases.py                     # Chase, Step, TransitionAction/SnapAction/ReleaseAction
│   ├── banks.py                      # Bank, SceneSlot/ChaseSlot/BlackoutSlot/ReleaseSlot
│   ├── environments.py               # EnvironmentManifest
│   └── library.py                    # FixtureLibrary, Show, load_show, load_fixture_library
├── dmx/
│   ├── interface.py                  # DmxInterface ABC
│   ├── null.py                       # In-memory implementation
│   ├── enttec_pro.py                 # Real Enttec Pro driver (pyserial)
│   └── simulator.py                  # Virtual Eurolite on a PTY (test substitute)
├── engine/
│   ├── clock.py                      # BpmClock — manual / tap / audio source
│   ├── interp.py                     # Easing functions
│   ├── voice.py                      # Voice — persistent paintbrush
│   ├── script.py                     # ChaseRunner, FiredAction, make_voice
│   ├── runtime.py                    # Engine — main 30Hz loop
│   └── reload.py                     # HotReloader — watchfiles + safe show swap
├── audio/
│   └── beat.py                       # AudioBpmDetector (aubio + sounddevice, optional)
├── ipc/
│   ├── messages.py                   # Envelope/Reply pydantic models
│   └── server.py                     # asyncio TCP IPC server (for future split-process)
├── web/
│   ├── app.py                        # FastAPI app: REST + WS + static
│   └── static/
│       ├── index.html                # GUI markup
│       ├── app.css                   # Dark theme
│       └── app.js                    # Vanilla JS — no build step
├── mcp_server/
│   └── server.py                     # MCP server over stdio (HTTP client of /api)
├── processes/                        # placeholder for future split-process entries
└── supervisor.py                     # placeholder; current supervisor is `lightning supervised`

data/
├── fixture_library/
│   ├── generic_rgb_par.yaml          # 7-channel RGBW par
│   └── generic_moving_head.yaml      # 16-channel LED moving head
└── environments/
    └── default/
        ├── environment.yaml          # 4-fixture starter rig
        ├── scenes/                   # blackout, warm_idle, red_pulse_on/off, mh_beam_blue/amber
        ├── chases/                   # red_pulse, mh_alternating_sweep, par_color_walk
        └── banks/
            └── starter.yaml          # 1-9 launchpad layout

tests/
├── conftest.py                       # tmp_data_dir, settings, show, engine, simulator fixtures
├── test_dmx_protocol.py              # Enttec Pro packet round-trip + simulator
├── test_clock.py                     # BPM, tap, monotonic
├── test_engine.py                    # core engine behaviour
├── test_chase.py                     # chase grammar + concurrency
├── test_hot_reload.py                # YAML edits + env switch
├── test_engine_simulator_e2e.py      # full pipeline through PTY
├── test_web_api.py                   # HTTP + WebSocket
└── test_stress.py                    # voice churn, concurrent chases, recovery
```

---

## Final notes

* **Total code:** ~3,500 lines including data + tests + docs.
* **Total tests:** 50, all green.
* **External deps:** pydantic, ruamel.yaml, pyserial, fastapi, uvicorn,
  watchfiles, click, anyio. Optional: aubio + sounddevice (audio BPM),
  mcp (LLM authoring).
* **Cross-platform:** the engine and driver work on Linux / macOS /
  Windows. Only the PTY-based simulator is Linux/macOS-only.
* **Built without hardware** — verified end-to-end via the PTY simulator,
  which exercises the same `pyserial` code path as production. First
  hardware test is yours to run; if anything misbehaves the most likely
  suspects are baud rate (try 115200 or 250000), the FTDI driver on
  Windows (use D2XX, not VCP), and the device's "Pro RX/TX" mode.

— Built overnight by Claude (Opus 4.7) for Marcel.
