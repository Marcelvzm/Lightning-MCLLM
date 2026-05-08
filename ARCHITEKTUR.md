# ARCHITEKTUR — Wie eine Show programmiert wird

Dieses Dokument erklärt die *Authoring-Mechanik*: aus welchen Bausteinen
eine Show besteht, wie sie aufeinander aufbauen, wie das Timing
funktioniert. Für die System-Architektur (Prozesse, Watchdog, IPC,
Robustheit) siehe [`technical_details.md`](technical_details.md).

---

## Die zwei Ebenen

Die zentrale Designentscheidung ist eine **harte Trennung in zwei
Ebenen**. Sie ist die Antwort auf das Spannungsfeld aus zwei
Anforderungen:

> "Hochgradig robust, absolut absturzsicher" + "Soll von einem LLM live
> verändert werden können."

Diese Forderungen widersprechen sich, wenn das LLM im Realtime-Pfad
sitzt. Die Auflösung: **das LLM sitzt nie im Realtime-Pfad.**

```
┌───────────────────────────────────────┐
│  AUTHORING PLANE                      │   ← darf langsam sein
│  - YAML-Dateien in data/              │   ← darf abstürzen
│  - LLM editiert via MCP               │   ← darf falsche Inputs haben
│  - Mensch editiert per Editor / GUI   │
│  - Validation-then-swap               │
└──────────────┬────────────────────────┘
               │  Hot-Reload (file-watch oder MCP signal)
               ▼
┌───────────────────────────────────────┐
│  PLAYOUT PLANE                        │   ← muss in Echtzeit laufen
│  - 30Hz Engine-Tick                   │   ← muss niemals abstürzen
│  - Voices, Chases, Shadow-Universe    │
│  - DMX-Driver (Eurolite)              │
└───────────────────────────────────────┘
```

Alles, was der LLM macht, passiert oben. Das Schreiben einer YAML-Datei
kann fehlschlagen, Validierungsfehler haben, semantisch Quatsch
enthalten. Die Engine unten läuft weiter und spielt **die letzte gültige
Show** ab. Erst wenn ein neues YAML-Set vollständig validiert ist, wird
es atomar in die laufende Engine eingeswapt.

**Konsequenz:** Der LLM kann zehnmal kaputtes YAML schreiben, ohne dass
ein einziger DMX-Frame ausgesetzt wird.

---

## Warum Dateien als Source of Truth

Der zentrale Zustand sind **YAML-Dateien**, nicht eine API mit
In-Memory-State. Drei Gründe:

1. **Reproduzierbarkeit.** Eine Show ist ein Set von YAML-Dateien. Du
   kannst sie in git committen, zwischen Rechnern kopieren, einer
   anderen Person geben. Das geht nicht, wenn die Show "im Speicher der
   Engine" lebt.
2. **Editierbarkeit ohne MCP.** Du oder ein anderer Mensch kann die
   Files direkt mit einem Editor bearbeiten. Das LLM ist *eine*
   Möglichkeit, nicht die einzige.
3. **Kommentar-Erhalt.** Mit `ruamel.yaml` im Round-Trip-Modus überlebt
   jeder von Hand eingefügte Kommentar einen LLM-Edit. Wissen, das du
   reinschreibst (`# nur bei BPM 128+ verwenden`), bleibt erhalten.

---

## Die sechs Bausteine

Die Domänenobjekte bauen aufeinander auf — von hardware-nah zu
künstlerisch:

```
Fixture-Profile  (was für ein Gerät)            }  hardware-nah
    ↓
Fixture-Instance (wo gepatcht, welche Tags)     }
    ↓
Scene            (Snapshot — Werte je Rolle)    }  künstlerisch
    ↓
Chase            (Phrase — wiederholendes Muster)
    ↓
Bank             (Trigger-Layout für die GUI)
    ↓
Show             (Skript — choreographierte Komposition über Minuten/Stunden)
```

Alles davon zusammen lebt als **Stage** im Engine-Speicher — der
Laufzeit-Container, der ein Environment vollständig geladen
repräsentiert.

Jede Ebene **referenziert nur die Ebene direkt darunter** — nicht
hardware-Details. Eine Scene schreibt `select: { tag: par }`, nicht
`address: 1`. Tags abstrahieren weg von der Hardware.

---

### 1. Fixture-Profil — "was für ein Gerät"

Pro Geräte-Typ einmal definiert, wiederverwendbar. Liegt in
`data/fixture_library/`.

```yaml
name: generic_rgbw_par
channels:
  - { offset: 0, role: dimmer }
  - { offset: 1, role: color/red }
  - { offset: 2, role: color/green }
  - { offset: 3, role: color/blue }
  - { offset: 4, role: color/white }
```

Die `role` ist das Wichtige — semantischer Name (`color/red`), kein
DMX-Offset.

### 2. Environment — "wo gepatcht, wie getaggt"

Der Bühnenplan. Welches Profil sitzt auf welcher DMX-Adresse, welche
Tags gehören dazu.

```yaml
fixtures:
  - { name: par-l, profile: generic_rgbw_par, address: 1,   tags: [par, front, left] }
  - { name: par-r, profile: generic_rgbw_par, address: 8,   tags: [par, front, right] }
  - { name: mh-l,  profile: moving_head_16ch, address: 100, tags: [moving_head, left] }
  - { name: mh-r,  profile: moving_head_16ch, address: 116, tags: [moving_head, right] }
```

Ab hier wird die Hardware nicht mehr erwähnt. Du sprichst über **Tags,
nicht über Adressen**.

### 3. Scene — "Snapshot, wie sieht's aus"

Eine Scene ist *ein Standbild*. "Alle Pars warm, MHs dunkel."

```yaml
name: warm_idle
targets:
  - select: { tag: par }
    values: { dimmer: 140, color/red: 200, color/green: 80, color/blue: 20 }
  - select: { tag: moving_head }
    values: { dimmer: 0, position/tilt: 128, shutter: 255 }
```

Die Engine löst beim Anwenden auf:

* "Selektiere alle Fixtures mit Tag `par`" → par-l und par-r
* "Schreibe für jedes deren `color/red`-Kanal den Wert 200" → bei par-l
  ist das DMX-Adresse 2, bei par-r DMX-Adresse 9
* usw.

Du schreibst Scenes also **abstrakt**. Die Engine macht das Patching.

### 4. Chase — "wie bewegt sich's"

Ein Chase ist eine *zeitliche Abfolge von Aktionen*. Hier passiert die
ganze Programmlogik. Das System hat zwei Anker-Modi.

#### Beat-anchored (musiksynchron)

```yaml
name: red_pulse
loop: true
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: snap,       group: { tag: par }, scene: red_pulse_on }
      - { kind: transition, group: { tag: par }, scene: red_pulse_off, fade_seconds: 0.4 }
  - at_beat: 1
    actions: [ { kind: snap, ... }, { kind: transition, ... } ]
  - at_beat: 2
    actions: [ ... ]
  - at_beat: 3
    actions: [ ... ]
```

Was passiert hier:

* Auf Beat 0: snap zu hellem Rot (sofort), gleichzeitig wird ein
  0.4-Sekunden-Fade zu dunklem Rot gestartet
* Auf Beat 1: dasselbe nochmal
* Bei BPM 120 = 0.5 Sek/Beat ist das ein klassisches 4-on-the-floor

#### Time-anchored (nicht beatgebunden)

```yaml
name: ambient_drift
loop: true
length_seconds: 16
steps:
  - at_seconds: 0
    actions: [ { kind: transition, group: { tag: par }, scene: deep_blue,  fade_seconds: 8.0 } ]
  - at_seconds: 8
    actions: [ { kind: transition, group: { tag: par }, scene: warm_amber, fade_seconds: 8.0 } ]
```

Beat-anchored Chases skalieren mit BPM. Time-anchored laufen unabhängig
von Tempo.

#### Action-Typen

* `transition` — fade von aktuellem Wert zu Ziel über `fade_seconds`
* `snap` — sofort setzen (transition mit Dauer 0)
* `release` — Voices dieses Chase droppen, Channels halten letzten Wert

Ziel pro Action ist entweder **eine Scene** (`scene: <name>`) oder
**inline values** (`values: { color/red: 255 }`). Nicht beides.

#### Parallelität und "wait"

Du hattest gefragt: *"Übergang Gruppe 1 in 0.5 s, Übergang Gruppe 2 in
0.3 s, wait(Gruppe 2), …"*

Im Beat-anchored-Modus wird das **implizit** gelöst — ohne explizites
`wait`:

```yaml
length_beats: 4
steps:
  - at_beat: 0
    actions:
      # Beide starten gleichzeitig auf Beat 0:
      - { kind: transition, group: { tag: moving_head }, scene: beam_up, fade_seconds: 1.5 }
      - { kind: transition, group: { tag: par },        scene: red_full, fade_seconds: 0.1 }
  - at_beat: 1                                        # ≈0.5 s später bei 120 BPM
    actions:
      # Par hat seinen Fade längst beendet; nächste Aktion auf Par:
      - { kind: transition, group: { tag: par }, scene: red_dim, fade_seconds: 0.4 }
  - at_beat: 3                                        # ≈1.5 s nach Beat 0
    actions:
      # Erst hier ist der MH-Fade fertig (1.5 s = 3 Beats); nächste MH-Aktion:
      - { kind: transition, group: { tag: moving_head }, scene: beam_down, fade_seconds: 0.5 }
```

Die "wait"-Logik ist also: **du wartest, indem du den nächsten Step
ans nächsten passenden Beat anhängst.** Wenn Gruppe A einen 1.5-Sek-Fade
hat, packst du die nächste Aktion für A einfach 1.5 Sek später (= 3
Beats bei 120 BPM). Gruppe B agiert unabhängig dazwischen.

Steps gehen also **parallel über Gruppen, sequenziell über Zeit.**

Wenn zwei Voices den selben Channel beschreiben, gewinnt die jüngere
(last-writer-wins).

### 5. Bank — "wie triggerst du's"

Eine Bank ist ein 9er-Pad-Layout für die GUI:

```yaml
name: starter
slots:
  - { id: 1, kind: scene,    name: warm_idle, label: "Idle" }
  - { id: 5, kind: chase,    name: red_pulse, label: "Red Pulse" }
  - { id: 9, kind: blackout,                  label: "BLACKOUT" }
```

In der GUI sind die als Tasten 1–9 gemappt. Drückst du `5`, startet
`red_pulse`. Drückst du `9`, blackout.

### 6. Show — choreographierte Komposition

Ein **Show** ist die Top-Ebene: ein YAML-Skript, das Scenes, Chases und
Banks **über die Zeit orchestriert**. Damit baut man echte Sets — eine
einminütige Demo bis hin zu einer 60-Minuten-Auto-Show. Lebt unter
`data/environments/<env>/shows/*.yaml`.

```yaml
name: techno_60min
description: Hour-long techno set
bpm: 128
loop: true                     # nach Skript-Ende von vorn

keybindings:                   # für GUI-Play-Mode
  "1": { kind: scene, name: warm_idle, label: "Idle" }
  "2": { kind: chase, name: red_pulse, label: "Pulse" }
  "B": { kind: blackout,                 label: "Blackout" }
  ...

script:
  - { do: snap_scene, scene: warm_idle, fade: 4.0 }
  - { do: wait, seconds: 300 }              # 5 min
  - { do: start_chase, chase: red_pulse }   # async — läuft weiter
  - { do: wait, bars: 32 }                  # bar-anchored
  - { do: blackout, fade: 0.0 }             # globaler Latch
  - { do: wait, beats: 1 }
  - { do: release_blackout }
  - do: loop                                # Sub-Block
    times: 4
    actions:
      - { do: snap_scene, scene: red_pulse_on }
      - { do: wait, seconds: 0.5 }
      - { do: snap_scene, scene: red_pulse_off }
      - { do: wait, seconds: 0.5 }
  - { do: wait_chase, chase: red_pulse }    # bis Chase einen Loop voll hat
  - { do: blackout, group: { tag: par }, fade: 0.5 }   # gruppen-blackout
  - { do: stop_all_chases }
```

#### Action-Typen im Skript

| Action | Effekt |
| --- | --- |
| `snap_scene { scene, fade? }` | Wendet eine Scene an (sofort oder mit Fade) |
| `start_chase { chase }` | Startet Chase (async; Skript läuft weiter) |
| `stop_chase { chase }` | Stoppt Chase |
| `stop_all_chases` | Alle Chases stoppen |
| `fire_slot { bank, slot }` | Bank-Slot auslösen |
| `blackout { group?, fade? }` | Ohne `group` = globaler Latch. Mit `group` = Selector-Channels auf 0 (kein Latch). |
| `release_blackout` | Globalen Latch lösen |
| `set_values { group, values, fade? }` | Inline-Werte auf Selektor schreiben |
| `set_bpm { bpm }` | BPM ändern |
| `wait { seconds | beats | bars }` | Genau eines davon. Beats/Bars folgen der BPM-Clock. |
| `wait_chase { chase }` | Wartet bis Chase einen Loop-Iteration komplett hat |
| `wait_group { group }` | Wartet bis keine Voice mehr im Übergang auf Selektor-Channels ist |
| `loop { times, actions }` | Sub-Block N-mal wiederholen (Verschachtelung erlaubt) |
| `log { message }` | Schreibt ins `last_errors`-Log (Debug) |

#### Wie das ausgeführt wird

Ein **`ShowRunner`** läuft im Engine-Tick (30 Hz, dieselbe Schleife wie
Chases). Pro Tick werden Actions sequentiell abgearbeitet, bis eine
Wait-Action installiert wird oder das per-Tick-Budget (default 200
Actions) erschöpft ist. Async-Actions (`start_chase`, `set_values` mit
fade) blockieren nicht — sie feuern und das Skript läuft weiter.

#### Steuerung

Die Engine kennt fünf Show-Commands:

* `play_show` — Skript von vorn starten (Reset + Play)
* `pause_show` — Skript einfrieren (laufende Chases gehen weiter)
* `resume_show` — Pause aufheben
* `reset_show` — auf Anfang setzen + weiterlaufen
* `stop_show` — Skript stoppen + Runner droppen

In der GUI als `▶ Play / ⏸ / ▶ Resume / ↺ Reset / ■ Stop` Buttons
exponiert. Über MCP über die gleichnamigen Tools.

#### Keybindings + Play-Mode

Eine Show definiert optional `keybindings: { "K": { kind, name, label } }`.
Wenn der **Play-Mode** in der GUI aktiviert ist, mappt die Tastatur
direkt auf diese Bindings (statt auf Default-Bank-Slots). Mehrere Shows
können unterschiedliche Bindings haben — jede Show kommt mit ihrer
eigenen "Tastatur-Belegung" für den Live-Operator.

Universelle Sicherheits-Shortcuts (Leertaste = Blackout, Esc = Release)
funktionieren immer, auch im Play-Mode.

---

## Wie das Zusammenspiel aussieht

Eine fertige Mini-Show:

```
data/environments/my_set/
├── environment.yaml          # 1 Datei: das Patching
├── scenes/
│   ├── idle.yaml             # ~5–10 Scenes:
│   ├── peak_white.yaml       #   die "Vokabeln" der Show
│   ├── red_full.yaml
│   ├── red_dim.yaml
│   ├── beam_up.yaml
│   └── beam_down.yaml
├── chases/
│   ├── pulse_4otf.yaml       # ~3–6 Chases:
│   ├── mh_sweep.yaml         #   die "Sätze"
│   └── build_strobe.yaml
├── banks/
│   └── live.yaml             # 1 Datei: das Trigger-Layout
└── shows/
    ├── live_60min.yaml       # die Choreographie für ein Set
    └── ambient_warmup.yaml
```

Die Engine spielt dabei nicht *eine* Sache, sondern **stapelt** alles,
was gerade aktiv ist:

* Du startest `pulse_4otf` (läuft).
* Du startest *zusätzlich* `mh_sweep` (läuft auch).
* Du snappst die Scene `peak_white` für 1 Sekunde.

Alle drei laufen parallel auf jeweils unterschiedlichen Channels (per
Tags getrennt). Wenn sie sich überschneiden, gewinnt die jüngste Voice.

---

## Voice-Modell (warum Live-Editing während der Show geht)

Eine **Voice** ist ein "persistenter Pinsel": einmal gestartet, malt sie
ihre Channels jeden Frame ins Shadow-Universe — bis sie ersetzt wird.

Der entscheidende Trick:

* Snap-Aktionen erzeugen Voices mit Dauer 0 — sie schreiben sofort den
  Zielwert und **halten ihn** bis ein neuer Voice ihn überschreibt.
* Transition-Aktionen erzeugen Voices mit Dauer N Sekunden — sie
  interpolieren von Source zu Target und halten dann das Target.
* Voices verschwinden NICHT automatisch nach ihrer Dauer. Sie bleiben
  "an", bis:
  - Eine neue Voice mit demselben Key sie ersetzt
  - Ein expliziter Release sie droppt
  - Stop_chase oder stop_all_chases sie entfernt
  - Engine-Restart

**Konsequenz fürs Live-Editing:** wenn ein Reload passiert, werden die
Chase-*Runner* gedroppt (ihre Show-Referenzen sind alt), aber die
*Voices* schreiben kurz noch ihre letzten Werte ins Shadow, bis ein neuer
Chase-Tick kommt. Mit `auto_resume=True` startet der Reload den Chase
mit demselben Namen sofort neu — dann mit dem neuen YAML.

Effekt: ein Reload mitten im Set ist **nicht spürbar**. Maximal ein
Frame, in dem der Übergang stattfindet.

---

## Render-Reihenfolge pro Tick

Was die Engine 30× pro Sekunde tut:

1. **Commands abarbeiten** (snap_scene, start_chase, blackout, …)
2. **Clock ticken** (Beat-Position vorrücken)
3. **Chase-Runner ticken** — die feuern Step-Aktionen, wenn sie ihren
   Anker überschreiten. Gefeuerte Aktionen werden zu neuen Voices.
4. **Voices ticken** — jede Voice rückt ihre `elapsed`-Zeit vor
5. **Render** — frisches Shadow-Buffer, dann iteriere alle Voices
   *oldest-first* und lass jede ihre Werte schreiben. Newer-wins für
   geteilte Channels. Master-Dimmer skalieren. Blackout-Latch zuletzt
   anwenden.
6. **Send** — Shadow → DMX-Driver → Eurolite

Per-Phase try/except: ein kaputtes Chase-YAML kann nicht die ganze
Engine stoppen. Voice-Bugs landen im `last_errors`-Log.

---

## BPM-Clock und Audio-Modus

Die Clock kennt drei Quellen:

* **manual** — Slider in der GUI oder API-Aufruf `set_bpm`
* **tap** — drei oder mehr Taps auf den Tap-Button in der GUI
  (durchschnittliches Inter-Tap-Intervall → BPM)
* **audio** — `aubio`-basierte Detektion vom Audio-Input
  (`--audio-bpm` Flag beim Start)

Beat-anchored Chases nutzen `clock.beat_position` (monoton wachsend).
Time-anchored Chases ignorieren die Clock und nutzen ihre eigene
`elapsed_seconds`.

### Stille im Audio-Modus

Die Audio-Detektion erkennt Stille auf zwei Wegen:

* RMS unter `silence_rms_threshold` (0.002 default — der Raum ist
  tatsächlich leise)
* aubio-Confidence unter `confidence_threshold` (0.15 default — kein
  klarer Beat erkennbar)

Bei sustained Stille (`> silence_pause_after_seconds`, default 2.0 s)
wird die Clock auto-pausiert: `set_running(False)` + Source-Label
wechselt auf `audio (silent)`. Beat-anchored Chases frieren ein, weil
`beat_position` nicht mehr vorrückt.

Sobald wieder Audio kommt, läuft die Clock automatisch weiter und der
Chase setzt da fort, wo er aufgehört hat.

In den manuellen Modi (manual / tap) gibt es **keine** Auto-Pause —
wenn du eine BPM gesetzt hast, ist das deine Entscheidung.

---

## GUI-Display: Beat-Position

`beat_position` wächst monoton (Beats seit Clock-Start, gebraucht für
Loop-Modulo-Berechnungen in Chases). Bei pausierter Clock —
Audio-Stille oder manuelle Pause via `set_running(False)` — wird der
Wert in der GUI **rot** dargestellt. Sofortige visuelle Bestätigung,
dass die Clock steht.

---

## Der Authoring-Loop (LLM-Sicht)

So arbeitet der LLM, wenn du sagst "schreib mir was für Techno":

```
1. read_authoring_guide          → llm_instruct.md (Prinzipien)
2. read_genre_concept("techno")  → tiefes Genre-Konzept
3. list_show                     → welche Fixtures, welche Tags
4. read_yaml(...)                → Pattern-Vorlagen aus existierenden Files
5. (denken)                      → Entropie-Kurve, Palette, Hierarchie
6. write_yaml(...) × N           → neue Scenes/Chases/Banks
7. reload                        → Engine validiert, swap-or-keep-old
       ↓
   wenn Fehler: Liste der Errors zurück → fix → reload
       ↓
   wenn ok:
8. snap_scene(...)               → live testen
9. start_chase(...)              → live testen
10. status                       → was passiert gerade
11. iterieren bis es passt
```

Schritt 7 ist die kritische Stelle:

* Erst wird das ganze neue YAML-Set in einen frischen `Show`-Container
  geladen
* Wenn beim Laden auch nur EIN Fehler auftritt, bleibt der alte `Show`
  aktiv
* Erst wenn der neue `Show` *vollständig validiert* ist, wird er atomar
  reingeswapt

Die Engine sieht nie einen halb-aufgelösten Zustand.

---

## Was du konkret damit machst

* **Vor der Show**: dem LLM sagen "schreib mir ein Set für Techno bei
  130 BPM" → er erzeugt 5–15 Scenes + 3–8 Chases + 1 Bank + 1
  Genre-Eintrag.
* **Während der Show**: "der Drop-Bereich war zu wenig — pack mehr
  Strobes rein" → der LLM editiert die entsprechenden Chase-YAMLs, ruft
  `reload`, im nächsten Drop läuft der überarbeitete Chase. **Ohne
  Lichtaussetzer.**
* **Zwischen Sets**: "schreib das gleiche Set, aber für Hardtekk" → er
  kopiert Strukturen, swapt Paletten und Tempo-Multiplikatoren, neue
  Files in 30 Sekunden.
* **Du selbst**: kannst jederzeit per Editor in die YAMLs reingehen und
  Werte tweaken. File-Watcher reloadet automatisch.

Das System ist ein **Doppel-Operator-Setup**: du am physischen Pad
(GUI / Banks / Tap-Tempo), der LLM im Hintergrund als Komponist, der die
Cues schreibt, die du triggerst.

---

## Warum das LLM nicht direkt steuert

Die Alternative wäre: der LLM bekommt einen `set_dmx(channel, value)`
und steuert die Lichter direkt. Das ist **bewusst nicht gebaut**:

1. **Latenz.** Ein LLM-Roundtrip dauert hunderte Millisekunden bis
   Sekunden. Eine 30 Hz-Engine braucht 33 ms pro Frame. Ein Live-LLM
   kann unmöglich rechtzeitig reagieren.
2. **Persistenz.** Ein Live-LLM-Pfad muss die ganze Zeit "an" sein. Das
   ist teuer (Token-Kosten) und fragil (jede Verbindungspause = Ausfall).
3. **Falsche Aufgabenteilung.** Echtzeit-DMX ist ein deterministisches
   Problem (interpolieren zwischen Werten in N ms). Genau dafür ist die
   Engine da. Das LLM ist gut in *Komposition* — also in Authoring.

**Der LLM komponiert. Die Engine spielt.** Wie ein Komponist und ein
Player Piano: der Komponist übergibt eine Notenrolle, der Player Piano
spielt sie ab. Der Komponist kann eine neue Rolle reichen, während die
alte noch läuft.

---

## Offene Punkte

Was *nicht* gelöst ist: **wie der LLM weiß, ob seine Show gut aussieht.**
Er kann `snap_scene` und `start_chase` aufrufen, sieht im Status, dass
Voices laufen — aber er sieht nicht, was visuell passiert. Der
Universe-Visualizer in der GUI hilft dir, hilft dem LLM nicht.

Mögliche Erweiterung: ein Tool `render_preview(chase, duration)` das
einen Frame-für-Frame-Snapshot zurückgibt, den der LLM analysieren kann.
Steht auf der Roadmap. Für jetzt ist der Loop "der LLM schreibt, du
sagst ihm, ob's gut war" der pragmatische Weg.

---

## Erweiterungen (Live-Operations-Layer)

Die ursprüngliche Architektur (Voices, Chases, Stage, Show) ist
unverändert. Was später dazukam, sind ausschließlich **Operator-seitige
Komfort-Features** — keine davon ändert das Engine-Modell.

### Audio-BPM-Detection mit Genre-Range

`audio/beat.py` liest das System-Mic mit `sounddevice` und detektiert
BPM via `aubio`. Architektur:

* Detector läuft im Hintergrund-Thread, schreibt BPM nur wenn
  `agreement_frames=3` Werte innerhalb 4 BPM Spread liegen — Smoothing
  0.4. Engine blockiert nie auf Audio.
* **Range-Provider-Callback** (gesetzt aus `Engine._bpm_range`): User
  wählt im GUI ein Genre-Preset, daraus eine Plausibilitäts-Range
  (parsed aus `genre_concepts/*.md`-Headers `BPM X-Y`). Der Detector
  multipliziert raw BPM mit `{1, 2, 0.5, 4, 0.25}` und nimmt den Wert,
  der in der Range landet (zentralster gewinnt). Beseitigt aubio's
  Half-Time/Double-Time-Locks.
* **Padding ±6 BPM** an den Range-Grenzen, weil Genre-Header oft etwas
  konservativ sind (Hardtekk-Range 150-180 nimmt 144 = 72×2 sinnvoll an).
* **Drop-Implausible**: bei keinem Octave-Fit wird das Frame komplett
  verworfen, **nicht** rohes BPM gepusht. Clock behält letzten guten
  Wert.
* **Pause-on-Silence-Provider-Callback** (`Engine._pause_on_silence`):
  Default true → Clock pausiert nach 2s Mic-Stille. Off → Clock läuft
  weiter mit letzter BPM.
* **Source-Label-Symmetry**: Source-Wechsel `audio (silent) → audio`
  jetzt auf jeder Non-Silent-Frame, nicht erst beim nächsten BPM-Push.

Engine-Ops dazu: `start_audio`, `stop_audio`, `set_bpm_range`,
`set_pause_on_silence`. Live-Diagnose (rms, confidence, raw vs
corrected BPM, multiplier, range, silent-flag) im Status-Block.

### Show-Timeline + Seek

`show_runner.compute_show_length_seconds(show, ref_bpm)` walkt das
Script und summiert Wait-Durations. Beat-Waits werden per Ref-BPM
linearisiert. `wait_chase`/`wait_group` werden als 0 gezählt und
markieren das Resultat als Schätzwert.

`ShowRunner.seek(target, ref_bpm)`:

1. Reset zu Anfang
2. Walk forward ohne real time: Wait-Durations werden zu einem
   `accumulated`-Counter addiert; alle anderen Actions (snap_scene,
   start_chase, set_bpm) werden via `engine.submit` an den
   Command-Queue übergeben — kumulativer State-Aufbau.
3. Wenn ein Wait `accumulated` über `target` schiebt, wird der
   **Remainder** als Live-Wait installiert. Der Tick-Loop nimmt von
   dort die Show wieder auf.

User gibt im GUI eine **Reference BPM** ein — unabhängig von der
Live-Clock. Beat-Waits werden gegen die Ref konvertiert; der
Live-Detect wird nicht beeinflusst.

### Hot-Reload preserves running show

`Engine.replace_stage` cleart den Show-Runner wie immer. **Aber**: der
Show-Name wird vorher gemerkt; nach dem Stage-Swap submited der Engine
ein `play_show` mit dem gleichen Namen falls die Show im neuen Stage
existiert. Ergebnis: YAML speichern → Show läuft auto von Beat 0
weiter. Kein erneutes Play-Drücken nötig.

### Healing-Pfade an der BPM-Clock

Vorher konnte die Clock im Zustand `running=False` hängen, wenn der
Audio-Detector während Stille pausiert hatte und der User Audio
ausschaltete bevor wieder Sound kam. Jetzt:

* `stop_audio` ruft am Ende `set_running(True)`
* `set_bpm` setzt `_running=True`
* `tap` setzt `_running=True`
* Neuer expliziter Op `set_clock_running({running: bool})` für
  externe Steuerung

### Stage Preview (visuelle Sim)

`web/sim.py` ist eine pure Funktion über `(stage, shadow) → fixtures`.
Pro Fixture wird:

* `kind` aus den Channel-Roles inferred (moving_head wenn `position/pan`
  + `position/tilt`; rgb_par wenn `color/r,g,b`; wheel_par wenn
  `color/wheel`; effect_bar wenn nur `effect/macro`)
* `color` resolved: RGB direkt; sonst Wheel-Lookup (Bar S120
  Wheel-Tabelle hardcoded); sonst Macro-Lookup (RX350 12-mode-Tabelle
  hardcoded); sonst neutral grey
* `intensity` aus `dimmer`-Channel; oder 1.0 wenn Color > 0
* Pan/Tilt/Gobo/raw_macro durchgereicht für UI-Render

Endpoint `/api/sim_state`. Die GUI rendert ein Canvas-Layout: Heads
oben, RX350 mitte (4-LED-Bar), Pars unten. Pan/Tilt als
Pointer-Linie; Gobo als kleines Badge oben rechts; Strobe als
Flash-Overlay.

### Scene/Chase Notes

Editierbare Kommentare per Trigger, persisted in
`<env>/notes.yaml`. Separat von der `description:` aus der YAML — der
Operator kann live annotieren ohne authored YAMLs zu touchen. GET/PUT
unter `/api/notes`. GUI: Inline-Edit am rechten Listen-Item-Rand.

### Parameter-Modal

`/api/stage` liefert Scenes/Chases als Objects mit `parameters:`-Block
(type/default/min/max/options/description). GUI rendert für jedes
Parameter den passenden Input-Type. Argumente werden mit der `args`-
Map durchgereicht — gleicher Pfad wie der LLM bei MCP-Calls.

### Reference-BPM für Shows ist ein Engine-State

`Engine._show_reference_bpm`. Wird **nicht** zwischen Engine-Restarts
persistiert — beim Boot 120 BPM. Ändert sich pro
`set_show_reference_bpm`-Call. Rein für Längen-/Seek-Berechnung; live
BPM bleibt unberührt.

### Banks sind nicht 9-Pads

Slot-IDs haben kein Modell-Limit. Tastatur-Map deckt 1-36 ab (Zahlen
1-9, dann 0=10, dann QWERTZ-, ASDF-, YXCV-Reihen). Slots > 36 sind im
GUI klickbar, nur ohne Tastenkürzel.

### SET ZERO als Panik-Op

`all_off` ist die nukleare Variante: cleart alle Voices, alle
Chase-Runner, hebt den Blackout-Latch, setzt Master auf 1.0 zurück.
Wichtig: Dies ist kein "ich hab was vergessen-Recovery" — es ist
"Bühne ist im falschen Zustand und ich brauche jetzt sofort
sauberen Reset". `stop_show` macht jetzt das gleiche, weil der alte
`stop_show` Chases nicht mit gestoppt hat.
