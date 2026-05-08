# GUI-Bedienung

Die GUI ist auf einem Bildschirm (Laptop, Tablet, Phone) bedienbar.
Browser auf `http://localhost:7777` nach `lightning run`. Die Panels
folgen einander in der Seite — alles Live-State, kein Refresh nötig.

---

## Header

```
LightningMCLLM    ● env: stolz  [stolz ▼]  [Reload]
```

* **Grüner / roter Punkt**: WebSocket-Status. Grün = Live-Status fließt
  rein. Rot = Verbindung weg (sollte automatisch nach 1 Sek wieder grün
  werden).
* **`env: …` + Dropdown**: aktuelle Umgebung. Dropdown wechseln →
  atomarer Switch, Voices werden gedroppt, neuer Stage geladen, kein
  Engine-Neustart.
* **`Reload`**: forciert Re-Read von `data/`. File-Watcher reloadet
  sonst automatisch sobald du eine YAML speicherst.

---

## Status-Panel

```
BPM: 165.0    Source: audio       Beat: 1218.42       Master: 1.00
DMX: ✓ enttec_pro(/dev/cu...)    Voices: 8       NonZero: 32       Tick: 33.0 ms / 30 Hz
```

| Feld | Bedeutung |
| --- | --- |
| **BPM** | Aktuelles Tempo |
| **Source** | `manual` / `tap` / `audio` / `audio (silent)` / `show` |
| **Beat** | Beat-Position seit Clock-Start. **Rot** wenn Clock pausiert oder Audio stumm. |
| **Master** | Globaler Dimmer 0…1 |
| **DMX** | Hardware-Verbindungs-Status |
| **Voices** | Aktive Paintbrushes |
| **NonZero ch** | Wie viele Channels gerade > 0 sind |
| **Tick** | Frame-Zeit. Sollte ~33 ms (30 Hz) sein |

### BPM-Reihe

```
BPM   [—————●—————]   165   [Tap]   [🎵 Audio (ON)]   [hardtekk (150-180) ▾]   ☑ pause on silence
```

* **Slider + Zahlenfeld**: 40 - 300 BPM. Setzt manuelle BPM und startet
  die Clock auch wenn sie gerade gestoppt war.
* **Tap** (Tastatur `T`): drei oder mehr Mal im Beat klopfen, ab Tap
  drei lockt die BPM. Reset der Clock-Pause.
* **🎵 Audio**: toggelt Audio-BPM-Detection (aubio + Mikrofon).
  Goldenes Highlight wenn aktiv. In Stille wird die Clock pausiert
  (außer das `pause on silence`-Häkchen ist aus).
* **Genre-Dropdown**: parsed aus `genre_concepts/*.md`-Headers (`BPM
  X-Y`). Setzt einen Plausibilitätsbereich, der aubio's Half-Time- /
  Double-Time-Locks korrigiert. Mit `hardtekk (150-180)` wird ein roher
  detect von 75 BPM automatisch zu 150 verdoppelt.
* **pause on silence**: an = Standard (Clock pausiert nach 2s Stille).
  Aus = Lichtshow läuft auf der letzten BPM weiter, auch wenn der DJ
  gerade silenced. Sicher zwischen Songs.

### Audio-Diagnose

Wenn Audio an ist, erscheint unter der BPM-Reihe eine Zeile:

```
RMS: 0.0073 / thr 0.002    Conf: 5.90 / thr 0.15    raw BPM: 73.6 → 147.2 (×2)    range [150-180]    ▶ tracking
```

* **RMS**: Mic-Pegel; rot wenn unter Stille-Schwelle (0.002).
* **Conf**: aubio's Confidence; rot wenn unter 0.15.
* **raw BPM**: was aubio aktuell liefert. Die `→ ... (×N)`-Angabe
  zeigt, wenn der Genre-Multiplier greift. Bei `✗ outside range`
  hat keine Octave gepasst — die Clock behält ihren letzten guten Wert.
* **range**: aktuell aktiver Plausibilitätsbereich (oder `—`).
* **▶ tracking** / **⏸ silent**: aktueller Stille-Status.

### Master-Reihe

```
Master  [——————————●]    [BLACKOUT]   [Release]   [Stop chases]   [SET ZERO]
```

* **Master-Slider** (Tastatur — keine): globaler Dimmer.
* **BLACKOUT** (Leertaste): rot, latcht. Zieht alle Channels auf 0.
* **Release** (Esc): hebt den Blackout-Latch.
* **Stop chases**: dropt alle Chase-Voices, lässt Scene-Voices stehen.
* **SET ZERO**: Panik-Knopf. Cleart Voices, Chases, Blackout-Latch und
  setzt Master auf 1.0 zurück. Genau das was du willst, wenn die Bühne
  rot stehen bleibt obwohl du eine Blackout-Scene gesnapped hast.

---

## Show-Panel

Hier liegt die Hauptaktion: scripted Auto-Shows starten und steuern.

```
Show  [stolz_hardtekk ▼]  [▶ Play] [⏸] [▶ Resume] [↺ Reset] [■ Stop] [↻ Reload]
[ Play Mode: OFF ]   When ON, the show's keybindings drive the keyboard.
┌──────────────────────────────────────────────────────────────┐
│ RUNNING  stolz_hardtekk  1:23.4 / 4:57.5    action: …        │
└──────────────────────────────────────────────────────────────┘
Timeline:  [—————●———————————————————]   1:23.4 / 4:57.5
Ref BPM:   [165]   show contains wait_chase / wait_group — total is approximate
```

* **Show-Dropdown**: alle in `data/environments/<env>/shows/*.yaml`
  definierten Shows.
* **▶ Play**: startet die ausgewählte Show **von vorn** (resettet
  internen State).
* **⏸ Pause / ▶ Resume / ↺ Reset / ■ Stop**: wie erwartet.
* **↻ Reload**: re-liest die Show-YAMLs von Disk und startet die
  laufende Show automatisch wieder ab Beat 0 — kein erneutes Play
  drücken nötig. Auch der File-Watcher tut das automatisch sobald du
  eine Show-YAML speicherst.
* **Status-Box**: `state · name · elapsed/total · current action`. Wird
  rot bei `wait_chase`/`wait_group`-Shows mit `(est.)`-Suffix bei der
  Total-Zeit, weil die Laufzeit dieser Waits vom Runtime abhängt.

### Timeline-Scrubber

* **Drag** den Slider an die gewünschte Position → die Show **spult
  fast-forward** dorthin (alle `snap_scene`/`start_chase`/`set_bpm`
  cumulativ angewandt, Wartezeiten übersprungen). Beim Loslassen läuft
  die Show ab dort normal weiter.
* `wait_chase` / `wait_group` werden während Seek als Instant
  behandelt — sie können nicht simuliert werden.

### Ref BPM

* Fixe BPM, die zur **Längen-Berechnung** und **Seek** angenommen wird.
  Unabhängig von der Live-Clock — d.h. du kannst die Lichtshow auf
  165 BPM modellieren, auch wenn die Live-BPM gerade vom Audio woandes
  liegt.
* Beat-basierte Waits (`wait beats: 4`) werden über diese Ref-BPM in
  Sekunden umgerechnet.

---

## Triggers-Panel

```
[ filter… ]   Bank: [All ▼]   click = fire · click chase again = stop
┌──────────────────────────┐  ┌──────────────────────────┐  ┌─────────────────┐
│ Scenes (62/62)          │  │ Chases (53/53)          │  │ Fixtures (8)    │
├──────────────────────────┤  ├──────────────────────────┤  ├─────────────────┤
│ all_color ⚙   farb-snap │  │ chaos_strobe ⚙ palette │  │ head-1 @001+9   │
│ all_off                  │  │ red_pulse              │  │ head-2 @010+9   │
│ ambient_drift            │  │ mh_sweep               │  │ ...             │
└──────────────────────────┘  └──────────────────────────┘  └─────────────────┘
```

* **Filter-Feld**: Live-Suche über Scenes/Chases/Fixtures.
* **Bank-Filter**: schränkt Scenes+Chases-Listen auf Einträge ein, die
  als Slot in der gewählten Bank vorkommen. **All** = unfiltered.
* **`⚙`-Marker** rechts neben dem Namen: Scene/Chase hat
  Parameter (`parameters:`-Block in der YAML). Klick öffnet einen
  **Parameter-Dialog** mit einem Eingabefeld pro Parameter (Defaults
  vorausgefüllt, options:[…] werden zu Dropdowns, type:bool zu
  Checkbox). Enter / Fire feuert, Esc / Cancel schließt.
* **Notes** (rechte Spalte, kursiv-gedimmed): per-Scene/Chase
  editierbarer Kommentar, persisted in
  `data/environments/<env>/notes.yaml`. Klick auf den Notes-Bereich
  macht ihn editierbar; Enter speichert, Esc verwirft, leer = löschen.
  Falls keine User-Note existiert wird die `description:` aus der YAML
  als Fallback gezeigt.
* **Counts** zeigen `visible/total` an, sodass man sofort sieht, was
  rausgefiltert wurde.
* **Aktive Chases** sind orange hinterlegt.
* **Im Play Mode** bekommt jedes Item, das in den Show-Keybindings
  vorkommt, ein Tasten-Badge.

---

## Banks-Panel

```
Bank: [main ▼]    [1 1 Rot] [2 2 Blau] [3 3 Grün] ... [9 9 Halt] [10 0 White Hit] [11 Q Pulse]
```

* **Bank-Dropdown**: wählt die aktive Bank.
* **Slots-Reihe**: jeder Slot zeigt Slot-ID, Tastenkürzel (falls
  gemappt), und Label. Klick = feuern.
* **Aktive Chase-Slots** sind orange hinterlegt; Blackout-Slots
  haben rote Border.
* **Slot-Anzahl unbegrenzt** — Tastatur-Map (siehe unten) deckt 1-36
  ab; alles darüber ist klickbar. Banks sind nicht 9-Slot-Pads, sie
  sind nur eine Sortierung.

---

## Stage Preview

Live-Visualisierung des Rigs aus dem DMX-Shadow:

```
┌─ Stage Preview ──────────────────────────────────────────┐
│        ●        ●        ●        ●                      │
│      head-1   head-2   head-3   head-4                   │
│                                                          │
│              [ ● ● ● ● ]                                 │
│              rx350 · m=149                               │
│                                                          │
│        ●           ●           ●                         │
│      cameo-1     cameo-2     cameo-3                     │
└──────────────────────────────────────────────────────────┘
```

* **Moving Heads** als Kreise mit:
  - Farbe aus `color/wheel`-Wert (Wheel-Tabelle aus dem Profile)
  - Glow skaliert mit Dimmer-Wert
  - Weißer **Pointer** zeigt Pan/Tilt-Richtung
  - **`g42`-Badge** oben rechts = aktueller Gobo-Wert
* **Pars** (Cameo): RGB-Mix aus `color/red,green,blue` × Dimmer.
* **RX350** als horizontaler 4-LED-Bar; jede der 12 macro-Modi liefert
  eine andere Farben-Belegung der LEDs (Modi 6-11 splitten zwei
  Farben über die 4 LEDs). Label zeigt den raw-macro-Wert.
* **Strobe** wird als Blink-Overlay auf der Linse gerendert.
* Macro=0 auf Cameo → Blackout (Vendor-Quirk).

---

## Universe-Visualizer

1024×64-Canvas, 512 Channels nebeneinander, Helligkeit = Channel-Wert.
Updated mit dem Status-Tick.

---

## Tastatur-Shortcuts

### Default-Modus (Play Mode AUS)

Bank-Slots werden über drei Tastatur-Reihen gemappt — einmalig nach
nicht-deutschem Layout (Y/Z swapped):

| Tasten | Slots |
| --- | --- |
| `1` `2` `3` `4` `5` `6` `7` `8` `9` | 1 - 9 |
| `0` | 10 |
| `Q W E R T Z U I O P` | 11 - 20 |
| `A S D F G H J K L` | 21 - 29 |
| `Y X C V B N M` | 30 - 36 |

| Andere Tasten | Aktion |
| --- | --- |
| `Leertaste` | BLACKOUT (latcht) |
| `Esc` | Blackout lösen |
| `T` | Tap-Tempo |

### Play Mode AN

Aus dem **YAML der laufenden Show** werden die Keybindings angewendet:

```yaml
keybindings:
  "1": { kind: chase, name: red_pulse,    label: "Pulse" }
  "Q": { kind: scene, name: warm_idle,    label: "Idle" }
  "B": { kind: blackout,                  label: "Blackout" }
```

Tastendruck löst die zugewiesene Aktion aus. Default-Tasten
(Bank-Slots, Tap) **sind deaktiviert** — du hast die Show-eigene
Tastenbelegung explizit gewählt.

**Universelle Sicherheit funktioniert immer**:

* `Leertaste` → Blackout
* `Esc` → Release Blackout

(Damit du in jeder Situation einen Notaus hast, auch wenn die
Show-Bindings keine Blackout-Taste definieren.)

Wenn ein Input-Feld fokussiert ist, sind Shortcuts deaktiviert.

---

## Typischer Live-Ablauf

### Vor der Party (Aufbau / Setup)

1. Engine starten: `lightning run --env stolz --host 0.0.0.0`
2. Browser auf `http://<rechner-ip>:7777` (Phone als Backup-Steuerung)
3. Im Show-Dropdown die Show wählen + Ref BPM setzen
4. Genre passend wählen (z.B. `hardtekk`) bevor Audio an
5. ▶ Play
6. Play Mode an
7. Bier holen — die Show läuft autonom, du kannst per Keybindings
   Akzente setzen

### Während der Party

* Track passt nicht zur Show? → ⏸ Pause, neue Show wählen, ▶ Play
* Drop angekündigt? → manuell mit dem Show-Key oder Klick auf den
  Chase
* Es wird zu hektisch? → BLACKOUT (Leertaste), nach 1 Bar Esc
* Bühne bleibt komisch stehen? → SET ZERO
* Audio-Mode lockt half-time? → richtiges Genre im Dropdown
* DJ wechselt zu langsamerem Track? → Audio aus, Tap-Tempo neu
* YAML mitten im Set anpassen? → speichern, Show läuft per
  Auto-Reload selbst neu von Beat 0 los; alternativ ↻ Reload-Button
* In der Show eine Stelle finden? → Timeline-Slider draggen
* Eine Scene/Chase mit Argument testen? → Klick auf das ⚙-Item,
  Argumente eintragen, Fire

### Vom Phone / iPad

`lightning run --host 0.0.0.0` bindet auf alle Interfaces. Layout
faltet bei <800 px in eine Spalte.

### Notes als Cheatsheet

Während du Setlists durchgehst, kannst du dir auf jede Scene/Chase
einen Kommentar schreiben (Klick auf den rechten Bereich, Enter). Beim
nächsten Set siehst du sofort warum du das damals so geprobt hast.
