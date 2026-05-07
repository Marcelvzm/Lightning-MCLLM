# Programmieren mit LightningMCLLM

*Technisches Komplett-Manual für das Schreiben von Scenes, Chases, Banks,
Palettes und Shows. Erklärt jede Schema-Form, jedes Verhalten zur Laufzeit,
jede Stolperfalle.*

> Dieses Dokument behandelt **WIE** geschrieben wird — Syntax, Semantik,
> Voice-Modell, Hot-Reload, Auflösungs-Regeln. Für **WAS** geschrieben wird —
> Design-Prinzipien, Genre-Playbooks, Anti-Patterns — siehe
> [`llm_instruct.md`](llm_instruct.md).

---

## Inhaltsverzeichnis

1. [Mentales Modell](#1-mentales-modell)
2. [Verzeichnis-Layout](#2-verzeichnis-layout)
3. [Fixture-Profile](#3-fixture-profile)
4. [Environment + Fixture-Instanzen](#4-environment--fixture-instanzen)
5. [Selektoren](#5-selektoren)
6. [Rollen-Taxonomie](#6-rollen-taxonomie)
7. [Scenes](#7-scenes)
8. [Chases](#8-chases)
9. [Banks](#9-banks)
10. [Palettes](#10-palettes)
11. [Parameter und `${...}`-Platzhalter](#11-parameter-und-platzhalter)
12. [Shows (skriptbasierte Choreografien)](#12-shows)
13. [Voice- und Render-Modell](#13-voice--und-render-modell)
14. [Hot-Reload](#14-hot-reload)
15. [Trigger-Schnittstellen](#15-trigger-schnittstellen)
16. [Cookbook — konkrete Patterns](#16-cookbook)
17. [Stolperfallen](#17-stolperfallen)
18. [Quick-Reference](#18-quick-reference)

---

## 1. Mentales Modell

LightningMCLLM trennt **strikt zwei Ebenen**:

```
AUTHORING (du bzw. der LLM)            PLAYOUT (die Engine, 25-30Hz)
─────────────────────────────         ─────────────────────────────
YAML-Dateien in data/                 Voices → Shadow-Universe → DMX
- darf falsch sein                    - darf nie crashen
- darf langsam editiert werden        - läuft in Echtzeit
- LLM-/User-bearbeitbar               - tickt deterministisch
                                      
Hot-Reload-Watcher überwacht          Validation-then-Swap:
data/, baut bei Änderung neu auf       fehlerhafte YAML-Sets werden
und tauscht atomar in die Engine       NICHT in die laufende Engine
                                      übernommen — die letzte gültige
                                      Show läuft einfach weiter
```

Du editierst nur YAML. Die Engine konsumiert die geladene Stage-Repräsentation
(siehe Punkt 2). Wenn dein YAML kaputt ist, fällt einfach nichts kaputt — die
Engine ignoriert den Reload und sagt dir was fehlerhaft war.

**Render-Pipeline pro Tick** (z.B. 30× pro Sekunde):

1. Commands abarbeiten (snap_scene, start_chase, blackout, …)
2. BPM-Clock weiterticken
3. Aktive Chase-Runner ticken — feuern Step-Aktionen wenn ihr Anker erreicht ist
4. Voices ticken — interpolieren Fade-Zeiten
5. Render: frischer 512-Byte-Shadow, Voices schreiben *oldest-first* drauf,
   neuere Voices überschreiben ältere bei Konflikten. Master-Dimmer skaliert,
   dann Blackout-Latch
6. Send: Shadow → DMX-Driver → Hardware

---

## 2. Verzeichnis-Layout

```
data/
├── fixture_library/                Profile (geräte-typ-spezifisch)
│   └── eurolite_tmh_bar_s120_head.yaml
│   └── varytec_pad_5_fourty.yaml
│   └── …
└── environments/<env>/             EIN gesamtes Rig
    ├── environment.yaml            Patching: welches Profil wo, mit welchen Tags
    ├── palettes.yaml               (optional) Cross-Fixture-Farb-Definitionen
    ├── scenes/
    │   └── *.yaml                  benannte Standbilder
    ├── chases/
    │   └── *.yaml                  zeitliche Aktions-Sequenzen
    ├── banks/
    │   └── *.yaml                  Launchpad-Layout (9er-Grid)
    └── shows/
        └── *.yaml                  (optional) skriptierte Choreografien
```

Eine `Stage` (Engine-Container) lädt **alles** aus einem Environment-Ordner.
Mehrere Environments leben nebeneinander; man wechselt zwischen ihnen via
GUI-Dropdown oder API.

---

## 3. Fixture-Profile

Ein **Profil** beschreibt einen Geräte-Typ. Ein Profil pro Modell / Mode-
Kombination. Liegt in `data/fixture_library/`. Wird über mehrere
Environments geteilt.

### Schema

```yaml
name: eurolite_tmh_bar_s120_head           # eindeutig in der gesamten library
description: Single moving head...
manufacturer: eurolite                     # informativ
model: led_tmh_bar_s120                    # informativ

channels:
  - { offset: 0, role: position/pan, default: 128, description: "..." }
  - { offset: 1, role: position/pan_fine, default: 0 }
  - offset: 5
    role: color/wheel
    default: 0
    description: "Indexed color wheel"
    presets:                               # optional — benannte Werte für UI / Doku
      white: 0
      red: 14
      green: 24
```

**Felder pro Channel:**

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `offset` | ✓ | 0-indexiert. Channel 1 des Geräts = offset 0. |
| `role` | ✓ | Semantischer Name. **Slash-namespaced** (siehe §6). |
| `default` | – | DMX-Wert beim Initialisieren des Profils (informativ; die Engine setzt nicht aktiv auf default). |
| `description` | – | Freitext. |
| `presets` | – | `{ name: int }`-Map für Comfort-Lookups (z.B. `gobo/wheel.gobo1: 14`). |

**`footprint`** (Channel-Anzahl) wird automatisch aus `max(offset)+1` berechnet.

### Validierung

- Offsets müssen pro Profil eindeutig sein.
- `name` muss in der ganzen library eindeutig sein.
- Offsets liegen zwischen 0 und 511.

### Der Mode-Frage

Hat ein Gerät mehrere DMX-Modes (z.B. 3CH/5CH/7CH), schreibe **pro Mode ein
eigenes Profil-File**. Das Hardware-Setting muss am Gerät zum Profil
passen — sonst verschiebt sich die Belegung.

Beispiel: Cameo Flat 1 TRI 3W IR hat 6CH-Mode → ein Profil
`cameo_flat_par_tri_3w_ir.yaml` für 6CH. Wenn der User den Mode auf 3CH
umstellt, wird ein neues Profil `cameo_flat_par_tri_3w_ir_3ch.yaml`
geschrieben und die Environment-Patch-Zeile referenziert das neue.

---

## 4. Environment + Fixture-Instanzen

Das Environment-Manifest (`environment.yaml`) sagt: **welche Fixtures stehen
auf welcher DMX-Adresse, mit welchen Tags**.

```yaml
name: stolz                                 # eindeutig pro environments/-Ordner
description: ...
universes: [0]                              # nur Universe 0 wird aktuell auf Hardware ausgegeben
default_bank: main                          # Bank, die beim Stage-Load als aktiv gilt

fixtures:
  - name: head-1                            # eindeutig im Environment
    profile: eurolite_tmh_bar_s120_head     # Verweis auf data/fixture_library/<name>.yaml
    address: 1                              # 1-512 (1-indexiert!)
    universe: 0
    tags: [moving_head, bar, head-1, left, outer]

  - name: cameo-1
    profile: cameo_flat_par_tri_3w_ir
    address: 112
    universe: 0
    tags: [par, flat, cameo, front]
```

### Validierung beim Load

- DMX-Adressen-Overlap wird abgefangen (zwei Fixtures dürfen sich nicht
  Channels teilen). Errors werden kollektiv gesammelt — du siehst alle
  Konflikte in einem Reload-Output, nicht nur den ersten.
- Profile-Verweise müssen existieren.
- Fixture-Namen sind eindeutig pro Environment.
- `address + footprint - 1` darf 512 nicht überschreiten.

### Tags — die Brücke zur Authoring-Schicht

Tags sind willkürliche Labels (lowercase). Sie sind **die Brücke zwischen
Hardware und Show-Logik**. Scenes selektieren nach Tags, nicht nach Adressen
— heißt: dieselbe Scene funktioniert in jedem Environment, das die richtigen
Tags vergibt.

**Empfohlene Tag-Konvention:**

| Achse | Beispiele |
|---|---|
| Geräte-Typ | `par`, `moving_head`, `effect`, `beam_bar`, `strobe`, `blinder` |
| Hardware-Familie | `cameo`, `showtec`, `bar` (für Bar-Heads) |
| Räumliche Position | `front`, `back`, `left`, `right`, `center`, `inner`, `outer` |
| Rolle in der Show | `lead`, `rhythm`, `atmosphere`, `accent` |
| Identität (selten) | `head-1`, `head-2` (eindeutige Identifikation eines Heads in einer Bar) |

Konsistenz über Environments hinweg = **Scenes bleiben portabel**.

---

## 5. Selektoren

Ein Selektor wählt eine Untermenge der Fixtures aus. **Pro Block exakt eine
Form** — die Validierung lehnt gemischte Selektoren ab.

```yaml
{ name: "head-1" }         # exakte Instanz (eindeutiger Name im Environment)
{ tag: "par" }             # alle Fixtures, die das Tag haben
{ tags: [moving_head, left] }   # AND — alle diese Tags müssen vorhanden sein
{ any_tag: [par, ledbar] }      # OR — mindestens eines dieser Tags
{ all: true }              # JEDE Fixture im Environment
```

### Auflösungs-Reihenfolge (innerhalb des Selektors)

`name` > `tag` > `tags` > `any_tag` > `all`. Aber wie gesagt: nur eine Form
gleichzeitig.

### Was geht NICHT (v1)

- **Negation**: "alle pars AUSSER cameos" geht nicht direkt. Workaround:
  vergibst spezifische Tags (z.B. `[par, varytec]` exklusiv für die Varytec)
  und selektierst dann nach diesem.
- **Kombination AND zwischen verschiedenen Achsen**: `tag: par AND name: head-1`
  geht nicht. Wenn du das brauchst, vergebe einen kombinierten Tag.

---

## 6. Rollen-Taxonomie

Channel-Werte werden über **Rollen** angesprochen, nicht über Offsets. Das
ist warum Scenes portabel sind: ein Cameo's `color/red` (Channel 3) und
ein Showtec's `color/red` (Channel 1) werden vom selben Scene-Statement
korrekt adressiert.

### Konvention: slash-namespaced

```
dimmer                  shutter                strobe
color/red               color/green            color/blue
color/white             color/amber            color/uv
color/wheel             color/cto
position/pan            position/pan_fine
position/tilt           position/tilt_fine
movement/speed
gobo/wheel              gobo/wheel_fine        gobo/rotation
gobo/index
focus                   zoom                   iris
prism                   frost
effect/macro            effect/macro_speed
control/reset           control/lamp
raw/<n>                 # für nicht-semantische Channels
```

**Nicht erzwungen**. Frei erfindbar. `core/fixtures.py:KNOWN_ROLES` listet
die etablierten — neue Rollen (z.B. `effect/laser_pattern`) sind erlaubt,
müssen nur über alle Profile hinweg konsistent benannt werden.

### Engine-Verhalten bei fehlenden Rollen

Wenn ein Scene-Target eine Rolle schreibt, die das Fixture-Profil nicht hat
(z.B. `color/white: 100` auf einem Showtec, der nur RGB hat) → der Engine
**ignoriert den Schreibvorgang** stillschweigend. **Du schreibst einmal
"color/white" und es klappt auf jedem Fixture, das whites hat — auf den
anderen passiert einfach nichts.**

Das macht Scenes radikal komponierbar.

### Wert-Range

Alle Werte: **0..255 (8-bit DMX)**. Andere Werte werden beim Render
gerundet/geklemmt. Ungültige Werte (z.B. `300`) werden bei Schema-
Validierung abgelehnt.

---

## 7. Scenes

Eine **Scene** ist ein benanntes Standbild. Pro Scene eine YAML-Datei in
`scenes/`.

### Vollständiges Schema

```yaml
name: warm_idle                     # eindeutig pro Environment
description: Warmer Wash für ruhige Sektionen.

# (optional, siehe §11) — typed parameters mit Defaults
parameters:
  intensity: { type: int, default: 140, min: 0, max: 255 }

# Liste von Targets — jedes selektiert Fixtures + setzt Werte.
# Mehrere Targets werden in Reihenfolge angewendet, last-wins bei Role-Konflikten
# innerhalb desselben Fixtures.
targets:
  - select: { tag: par }
    # (optional, siehe §10) palette+facet referenzieren
    palette: { name: "rot", facet: rgb }
    # explizite values überschreiben palette-values bei Konflikten
    values:
      dimmer: "${intensity}"        # Parameter-Platzhalter (siehe §11)
      strobe: 0
      effect/macro: 0
    # (optional) Profil-Presets benutzen (z.B. gobo benannt)
    presets:
      gobo/wheel: gobo1

  - select: { tag: moving_head }
    values:
      position/pan: 128
      position/tilt: 110
      dimmer: 0
      shutter: 255
```

### Felder

| Feld | Pflicht | Inhalt |
|---|---|---|
| `name` | ✓ | string, eindeutig pro Environment |
| `description` | – | Freitext-Beschreibung |
| `parameters` | – | Parameter-Deklarationen (§11) |
| `targets` | – | Liste von Targets (siehe unten) |

### Target-Felder

| Feld | Pflicht | Inhalt |
|---|---|---|
| `select` | ✓ | Selektor (§5) |
| `values` | – | `{ rolle: int_or_placeholder }`. Werte 0..255. Strings müssen `${name}`-Platzhalter sein. |
| `presets` | – | `{ rolle: preset_name }` — Lookup über Profile.channels[role].presets |
| `palette` | – | `{ name: <palette>, facet: <facet> }` — siehe §10 |

### Was passiert beim Snap

```python
snap_scene("warm_idle")              # ohne args — Defaults werden benutzt
snap_scene("warm_idle", args={"intensity": 50})   # mit Override
```

Der Engine:
1. Validiert `args` gegen `parameters` (unbekannte → Error, fehlende → Default)
2. Iteriert die Targets in Reihenfolge
3. Pro Target: Selektor → Fixtures, dann pro Fixture die Rolle→Offset-
   Auflösung, schreibt `values`/`palette`-Werte in den Shadow
4. Erzeugt **eine Voice** mit Key `scene:<name>`. Diese Voice persistiert
   bis sie ersetzt oder gelöscht wird (siehe §13).

### Multiple Targets vs. mehrere Snaps

Du kannst entweder:
- **Eine Scene** mit mehreren Targets schreiben → atomarer Snap, eine Voice
- **Mehrere Scenes** nacheinander snappen → mehrere Voices die layern
  (Newer-wins bei Konflikten)

Single-Scene-Multi-Target ist üblicher; Multi-Snap-Layering ist sinnvoll
wenn du komponierbare Atom-Scenes haben willst die du in verschiedenen
Kontexten kombinierst.

---

## 8. Chases

Ein **Chase** ist eine *zeitliche Abfolge von Aktionen*. Liegt in
`chases/`. Loopt standardmäßig.

### Beat-anchored vs. Time-anchored

**Pro Chase EINE der beiden Modes** — Mischen wird beim Load abgelehnt.

```yaml
# Beat-anchored — skaliert mit der BPM-Clock
length_beats: 4
steps:
  - at_beat: 0
    actions: [...]
  - at_beat: 1
    actions: [...]
```

```yaml
# Time-anchored — unabhängig von BPM
length_seconds: 16
steps:
  - at_seconds: 0
    actions: [...]
  - at_seconds: 8
    actions: [...]
```

Beat-anchored: für musiksynchrone Sachen. Bei BPM 120 ist 1 Beat = 0.5 s.
Time-anchored: für ambient / atmosphärische Sachen, die nicht auf Beats
springen sollen.

### Vollständiges Schema

```yaml
name: red_pulse
description: 4-on-the-floor red pulse on the pars.
loop: true                          # default true; false = einmal durchlaufen, dann stop
length_beats: 4

# (optional) Parameter (§11)
parameters:
  fade: { type: float, default: 0.4, min: 0, max: 5 }

steps:
  - at_beat: 0
    note: "first beat — humans-only comment"
    actions:
      - kind: snap
        group: { tag: par }
        scene: red_pulse_on
      - kind: transition
        group: { tag: par }
        scene: red_pulse_off
        fade_seconds: "${fade}"
        easing: ease_in_out

  - at_beat: 1
    actions: [...]
```

### Step-Felder

| Feld | Pflicht | Inhalt |
|---|---|---|
| `at_beat` ODER `at_seconds` | ✓ (genau einer) | float ≥ 0, < length |
| `actions` | ✓ | Liste von ≥1 Action |
| `note` | – | Kommentar (wird nicht gerendert, nur Doku) |

### Action-Typen

#### `snap` — sofort

```yaml
- kind: snap
  group: { tag: par }                # Selektor
  scene: red_pulse_on                # ENTWEDER scene-Verweis ODER values, nicht beides
  # values: { color/red: 255, dimmer: 255 }
```

Erzeugt eine Voice mit `duration: 0`. Wert wird beim Fire sofort geschrieben
und gehalten.

#### `transition` — fade

```yaml
- kind: transition
  group: { tag: par }
  scene: red_pulse_off
  fade_seconds: 0.4                  # 0 entspricht snap
  easing: ease_in_out                # linear|ease_in|ease_out|ease_in_out
```

Erzeugt eine Voice mit `duration > 0`. Der Engine erfasst den **Source**-Wert
beim Fire (= aktueller Shadow-Stand auf den Ziel-Channels) und interpoliert
über `fade_seconds` zum Target-Wert.

`fade_seconds` darf ein `${...}`-Platzhalter sein. `at_beat` hingegen ist
**immer literal float** — Anker werden zur Load-Zeit gegen `length_beats`
validiert, da geht keine Substitution.

#### `release` — Voices droppen

```yaml
- kind: release
  group: { tag: par }
```

Lässt die Voices, die DIESE Chase-Instanz erzeugt hat, fallen. Die Channels
fallen dann auf 0 zurück (oder lassen darunter liegende Voices durch).

### Targets: scene-Verweis vs. inline values

```yaml
# Variante A: Scene-Verweis
- kind: snap
  group: { tag: par }
  scene: warm_idle                   # Scene wird gerendert + auf den Selektor gefiltert

# Variante B: Inline values
- kind: snap
  group: { tag: par }
  values:
    color/red: 255
    dimmer: 200
```

**Nicht beides gleichzeitig** — Schema lehnt das ab.

**Wichtige Asymmetrie zu Scene-Args** (v1-Limitierung):

- Inline `values:` einer Chase-Action sehen die Chase-Args (`${...}` wird
  aufgelöst).
- `scene: <name>`-Verweise einer Chase-Action **propagieren die Chase-Args
  NICHT** an die Scene. Die Scene wird mit ihren eigenen Defaults
  gerendert.

Wenn du eine Scene parametrisiert haben willst und sie aus einem Chase
heraus mit Override fahren willst → schreibe stattdessen `inline values`
mit `${...}`-Platzhaltern auf Chase-Ebene. Oder warte auf v2.

### Loop-Verhalten

`loop: true` (Default): nach `length_beats` (oder `length_seconds`) startet
der Chase wieder bei Position 0. Voices, die über den Loop-Boundary hinaus
fade'n, laufen ungeniert weiter — sie werden erst durch eine neue Voice mit
demselben Key ersetzt.

`loop: false`: der Chase läuft einmal durch, dann wird der Runner gedroppt.
Voices bleiben aber.

### Wrap-Logik beim Steppen

Wenn Position von z.B. 3.9 auf 0.1 wraps (loop length = 4): Steps die in
(3.9, 4.0) ODER [0.0, 0.1] liegen, feuern beide. Du verlierst nichts.

---

## 9. Banks

Eine **Bank** ist ein 9-Slot-Launchpad-Layout für die GUI. Die Tasten 1-9
mappen auf Slots. Mehrere Banks pro Environment möglich; eine ist
"default" (siehe `environment.yaml: default_bank`).

### Schema

```yaml
name: main
description: Live-Pad fürs Gig.

slots:
  - { id: 1, kind: scene, name: warm_idle, label: "Idle" }
  - { id: 2, kind: scene, name: red_full, label: "Red", fade_seconds: 0.0 }
  - id: 5
    kind: chase
    name: mh_drift_blinks
    label: "MH Drift Rot"
  # Mit args-Override (siehe §11) — derselbe Chase, andere Variante
  - id: 6
    kind: chase
    name: mh_drift_blinks
    label: "MH Drift Blau"
    args: { baseline_wheel: 34, baseline_dim: 80 }
  - { id: 8, kind: release, group: { tag: bar }, label: "Free MHs" }
  - { id: 9, kind: blackout, label: "BLACKOUT", fade_seconds: 0.0 }
```

### Slot-Kinds

| Kind | Felder | Verhalten |
|---|---|---|
| `scene` | `name`, `label?`, `fade_seconds?`, `args?` | Snap der Scene (mit optionalem Fade-In) |
| `chase` | `name`, `label?`, `args?` | Start des Chase (oder Replace falls schon laufend) |
| `blackout` | `label?`, `fade_seconds?` | Globaler Blackout-Latch (siehe §13) |
| `release` | `group`, `label?` | Voices auf den Selektor-Channels droppen |

### Slot-IDs

`id` ist 1-9 (Tastatur-Slot). Bank-Validation lehnt Duplikate ab. Lücken
sind erlaubt — die GUI rendert die fehlenden Slots leer.

### `args` pro Slot

Slot-Args werden beim Fire an die Scene/Chase weitergegeben. Heißt: derselbe
Scene-File kann mehrfach in der Bank auftauchen, mit verschiedenen
Parameter-Werten. Siehe §11 für Details.

---

## 10. Palettes

Eine **Palette** ist eine *benannte, fixture-übergreifende Farbdefinition*.
Eine Palette `rot` weiß, was "rot" für jedes Fixture-Profil heißt. Siehe
`palettes.yaml` per Environment.

### Schema

```yaml
# data/environments/<env>/palettes.yaml
palettes:
  - name: rot
    description: Sattes Bühnenrot.
    facets:
      rgb:    { color/red: 255, color/green: 0,   color/blue: 0,   color/white: 0 }
      wheel:  { color/wheel: 14 }
      cameo:  { color/red: 255, color/green: 0,   color/blue: 0,   effect/macro: 10 }
      rx350:  { effect/macro: 11 }

  - name: blau
    facets:
      rgb:    { color/red: 0,   color/green: 0,   color/blue: 255, color/white: 0 }
      wheel:  { color/wheel: 34 }
      cameo:  { color/red: 0,   color/green: 0,   color/blue: 255, effect/macro: 32 }
      rx350:  { effect/macro: 57 }
```

### Was sind Facets?

Ein **Facet** ist ein Werte-Bundle für **eine Steuerungsmodell-Familie**. Du
brauchst pro Fixture-Profil-Typ in deinem Rig ein Facet:

| Facet (Beispiele) | Wofür | Was setzt das Facet |
|---|---|---|
| `rgb` | direkt-RGB-Pars (Showtec/PAR-64/Varytec) | `color/red, /green, /blue, /white` |
| `wheel` | indexed Color-Wheel (Bar S120, viele Moving Heads) | `color/wheel` |
| `cameo` | RGB + Macro-Override (Cameo Flat, weil ch6=0=Blackout) | `color/red, ..., effect/macro` |
| `rx350` | nur Macro-Channel (Involight RX350 in 2CH) | `effect/macro` |

**Du wählst die Facet-Namen.** Konvention im stolz-Env ist oben — bei
anderen Rigs mache neue Facet-Namen, wenn die Fixture-Mischung anders ist.

### Palette in einer Scene-Target verwenden

```yaml
targets:
  - select: { tag: bar }
    palette: { name: rot, facet: wheel }
    values: { dimmer: 255 }              # explizite values überschreiben palette-values bei Role-Konflikten

  - select: { tag: cameo }
    palette: { name: rot, facet: cameo }

  - select: { name: rx350 }
    palette: { name: rot, facet: rx350 }
```

Beim Render holt der Engine `palettes["rot"].facets["wheel"]` →
`{color/wheel: 14}`, merged mit `target.values` → schreibt für jedes Fixture,
das den Selektor matched.

### Mit Parametern: dynamische Palette pro Snap

```yaml
parameters:
  col: { type: str, default: rot, options: [rot, blau, gruen] }

targets:
  - select: { tag: bar }
    palette: { name: "${col}", facet: wheel }    # ← MUSS gequotet werden in flow-mapping!
```

Snap-Aufrufe:

```python
snap_scene("all_color")                   # default: rot
snap_scene("all_color", args={"col": "blau"})    # blau
```

### Validierung beim Stage-Load

- Literale Palette-Namen werden gegen die geladene Palette-Library geprüft.
  Falsche Namen → Load-Error.
- `${...}`-Platzhalter werden zur Load-Zeit übersprungen (deferred), zur
  Render-Zeit aufgelöst.
- Facet-Existenz wird nur für literale Namen geprüft.

### Palette vs. mehrere targets

Vor Palettes hättest du eine Multi-Target-Scene `all_red` geschrieben mit
hardcoded RGB-Werten pro Selector. Dann eine zweite `all_blue` als Copy
mit anderen Werten. Bei 5 Farben = 5 Files mit ~80% identischem Code.

Mit Palettes: **eine** Scene `all_color` mit `col`-Parameter, `palettes.yaml`
mit allen Farben. Eine Änderung an `rot.cameo` propagiert in alle Bank-
Slots, alle Shows, alle Chases die "rot" benutzen.

---

## 11. Parameter und Platzhalter

Scenes und Chases können **Parameter** deklarieren. Ein Parameter hat
einen Namen, einen Typ, einen Default-Wert und optionale Constraints.
Beim Trigger (snap_scene / start_chase) können diese Defaults überschrieben
werden.

### Deklaration

```yaml
parameters:
  intensity:
    type: int
    default: 200
    min: 0
    max: 255
    description: "Master-Dimmer-Wert."
  fade:
    type: float
    default: 0.5
    min: 0
    max: 30
  col:
    type: str
    default: rot
    options: [rot, blau, gruen, weiss]
  motion:
    type: bool
    default: true
```

### Typen

| Typ | Akzeptierte Default-Werte | Constraints |
|---|---|---|
| `int` | int | `min`, `max` |
| `float` | int oder float | `min`, `max` |
| `str` | string | `options` (Liste erlaubter Werte, Whitelist) |
| `bool` | true/false | – |

### Verwendung im YAML: `${name}`-Platzhalter

In **numerischen Feldern**:

```yaml
values:
  dimmer: "${intensity}"
  color/red: 255
fade_seconds: "${fade}"
```

In **Palette-Namen**:

```yaml
palette: { name: "${col}", facet: wheel }
```

### Substitutions-Regel: WHOLE-STRING

Nur "string ist exakt `${name}`" oder "string ist exakt `$name`" wird
ersetzt. Mixing wie `"prefix${name}suffix"` wird **NICHT** ersetzt — der
ganze String bleibt unverändert (und wird höchstwahrscheinlich an einer
späteren Stelle als invalide rejected).

Heißt: für numerische Werte ist das natürlich, weil du keine
Stringkonkatenation brauchst.

### YAML-Quoting-Regel

⚠️ **Wichtige Stolperfalle.** YAML's *Flow-Mapping*-Parser (geschweifte
Klammern in einer Zeile) frisst `${...}` nicht ohne Quotes:

```yaml
# KAPUTT — YAML parse error
palette: { name: ${col}, facet: wheel }

# OK — mit Quotes
palette: { name: "${col}", facet: wheel }

# OK — block-style mapping (mit Einrückung statt Klammern)
palette:
  name: ${col}
  facet: wheel
```

Faustregel: **wenn du `${...}` in eine Zeile mit `{` und `}` schreibst,
quote es als String**.

### Trigger mit Args

```python
# Python / API
snap_scene("warm_idle", args={"intensity": 100, "fade": 1.5})
start_chase("mh_drift_blinks", args={"baseline_wheel": 34})
```

```jsonc
// HTTP API
POST /api/cmd/snap_scene
{ "scene": "warm_idle", "args": { "intensity": 100 } }
```

```yaml
# Bank-Slot
- id: 5
  kind: chase
  name: mh_drift_blinks
  args: { baseline_wheel: 34, drift_seconds: 6.0 }
```

### Validierungs-Regeln zur Trigger-Zeit

- Args, die NICHT in `parameters` deklariert sind → Error
- Args, die in `parameters` deklariert sind aber im Aufruf fehlen → Default
  wird benutzt
- Out-of-range → Error
- `options`-Verletzung → Error
- Type-Mismatch (z.B. string übergeben wo int erwartet) → Error

Errors landen in `engine.status().last_errors` + werden in der GUI
angezeigt. Die Engine läuft weiter.

### Was NICHT geht (v1)

- **Chase-Args propagieren NICHT in referenzierte Scenes**. Chase-Inline-
  `values:` sehen Chase-Args, `scene: <name>`-Refs nicht. Workaround: alle
  Color-Werte inline statt über referenzierte Scenes.
- **`when:`-Bedingungen** für conditional Step-Execution gibt's nicht.
  Workaround: `fade_seconds: 0` für no-op-Transitions, oder zwei Chases
  schreiben.
- **Hot-Reload-Resume verliert Args**: ein Reload startet aktive Chases
  mit Defaults neu, die ursprünglich übergebenen Args sind weg.

---

## 12. Shows

Eine **Show** ist eine *skriptbasierte Choreografie*. Liegt in `shows/`. Sie
fährt Scenes/Chases/Blackouts in einer Reihenfolge mit Wait-Punkten. Der
**ShowRunner** spielt das Skript ab.

### Schema

```yaml
name: techno_minimal
description: Smoke-Test der ShowRunner-Action-Grammatik.
bpm: 128                            # ShowRunner setzt BPM beim Start
loop: false                         # einmal durch, dann stop

# (optional) Tasten-Bindings für Live-Play während die Show läuft
keybindings:
  "1": { kind: scene, name: warm_idle, label: "Idle" }
  "2": { kind: chase, name: red_pulse }
  "B": { kind: blackout }
  "R": { kind: release_blackout }

# Skript wird sequenziell abgearbeitet — async-Aktionen (start_chase) blocken nicht
script:
  - { do: log, message: "intro" }
  - { do: snap_scene, scene: warm_idle, fade: 0.5 }
  - { do: wait, seconds: 2 }

  - { do: start_chase, chase: red_pulse }
  - { do: wait, bars: 4 }                # bei BPM 128 = 16 Beats = ~7.5s

  - { do: blackout, fade: 0.0 }
  - { do: wait, beats: 1 }
  - { do: release_blackout }

  - { do: wait_chase, chase: red_pulse }   # wartet bis red_pulse einen Loop fertig hat

  - do: loop
    times: 4
    actions:
      - { do: snap_scene, scene: red_full }
      - { do: wait, seconds: 0.5 }
      - { do: snap_scene, scene: red_dim }
      - { do: wait, seconds: 0.5 }

  - { do: stop_all_chases }
  - { do: snap_scene, scene: warm_idle, fade: 2.0 }
  - { do: log, message: "done" }
```

### Action-Typen im Show-Script

| `do` | Felder | Verhalten |
|---|---|---|
| `snap_scene` | `scene`, `fade?` | Wie API-Call snap_scene |
| `start_chase` / `stop_chase` / `stop_all_chases` | `chase` | Wie API-Calls |
| `fire_slot` | `bank`, `slot` | Wie GUI-Slot-Klick |
| `blackout` | `group?`, `fade?` | Mit `group`: per-Fixture-Blackout. Ohne: globaler Latch |
| `release_blackout` | – | Latch lösen |
| `set_values` | `group`, `values`, `fade?` | Inline-Werte auf Selektor anwenden |
| `set_bpm` | `bpm` | BPM-Clock setzen |
| `wait` | exakt einer von `seconds` / `beats` / `bars` | Skript pausieren |
| `wait_chase` | `chase` | Bis ein laufender Chase einen Loop-Durchlauf fertig hat |
| `wait_group` | `group` | Bis alle Voices auf den Selektor-Channels zu Ende gefadet sind |
| `log` | `message` | Eintrag in `engine.last_errors` (Debugging) |
| `loop` | `times`, `actions` | Sub-Block N-mal ausführen. `times: 0` = no-op (defensiv) |

### Show vs. Chase — wann was?

| Brauchst du… | Nimm |
|---|---|
| eine wiederholende Pattern, beat-locked | Chase |
| eine sequenzielle Sektion mit Wait/Build/Drop/Reset | Show |
| einen statischen Zustand | Scene |
| Live-Play mit Tasten-Triggern | Scene + Chase + Bank |
| eine ganze 60-Min-Set-Choreografie | Show |

Show-Steuerung: `POST /api/show/<name>/play`, `pause`, `resume`, `stop`,
`reset`. Im Pause-State werden Wait-Aktionen eingefroren.

---

## 13. Voice- und Render-Modell

Das Voice-Modell ist das Kernkonzept der Engine. Verstehen → kannst du das
ganze Verhalten (Layering, Replacement, Persistence, Render-Ordnung)
ableiten.

### Eine Voice ist ein "persistenter Pinsel"

```python
@dataclass
class Voice:
    key: str                                  # stable identifier
    targets: dict[(universe, addr), int]      # Ziel-Werte
    sources: dict[(universe, addr), int]      # bei Fade: Start-Werte (Snapshot)
    duration: float                           # 0 = snap, >0 = Fade-Dauer
    easing: str
    started_at: float                         # monotonic time
    elapsed: float                            # Zeit seit Start
```

Pro Tick schreibt die Voice ihre interpolated Werte (zwischen `sources` und
`targets`, eased) in den Shadow.

### Voice-Persistenz

Voices verschwinden **NICHT automatisch** wenn ihre Fade-Zeit zu Ende ist.
Sie bleiben, schreiben ihren `targets`-Wert weiter, bis:

1. Eine **neue Voice mit demselben Key** sie ersetzt
2. **`stop_chase`** entfernt Voices mit Prefix `chase:<name>:<inst>:`
3. **`stop_all_chases`** entfernt alle `chase:`-Prefix-Voices
4. Eine **`release`-Action** des Chase entfernt seine eigenen Voices
5. Engine-Restart

**Konsequenz:** snap_scene("warm_idle") "malt und bleibt". Solange keine
andere Voice die selben Channels überschreibt, ist warm_idle sichtbar.

### Voice-Keys (wer ersetzt wen)

| Aktion | Key-Form |
|---|---|
| `snap_scene <name>` | `scene:<name>` |
| Chase-Action | `chase:<chase_name>:<inst>:s<step_idx>:a<action_idx>:<selector_str>` |
| `set_value` (Direkt-Override) | `override:<universe>:<address>` |
| `blackout_group` | `blackout_group:<selector_str>` |
| Show-Runner snap_scene | derselbe Key wie API-snap |

**Same key + new voice → replacement.** Wenn du `snap_scene("warm_idle")`
zweimal hintereinander rufst, gibt es nur EINE Voice — die zweite ersetzt
die erste (mit ggf. anderen `targets` falls die Scene editiert wurde).

### Render-Reihenfolge

```python
new_shadow = bytearray(512)
for v in sorted(voices, key=lambda v: v.started_at):     # ÄLTESTE ZUERST
    v.write_to(new_shadow)
# master dimmer * scale
# blackout latch (overrides everything)
# send to DMX
```

**Newer-wins** auf shared Channels. Heißt: wenn zwei Voices auf Channel 5
schreiben — die jüngere überschreibt am Ende.

### Layering-Beispiel

```
T=0:   snap_scene("warm_idle")           # Voice A: key=scene:warm_idle, targets={ch1: 140, ch2: 200, ...}
T=2s:  snap_scene("red_flash")           # Voice B: key=scene:red_flash, targets={ch2: 255}
                                           # (red_flash setzt nur color/red, sonst nichts)
```

Render-Ergebnis ab T=2s: ch1 = 140 (von A), ch2 = 255 (von B, jünger), Rest
wie A.

→ red_flash hat warm_idle nicht überschrieben — es hat nur color/red
übermalt. Das ist absichtlich und macht Komposition möglich.

### Blackout

`blackout` erzeugt **KEINE** Voice. Stattdessen wird ein Engine-Flag
`_blackout = True` gesetzt. Im Render — **nach** den Voices, **vor** dem
Send — wird der Shadow auf 0 gesetzt (oder linear gefadet falls
`blackout_fade > 0`).

Das ist absichtlich so: ein laufender Chase, der während Blackout fired,
würde sonst durchpunchen (newer voice). Der Render-Latch ignoriert alles
davor.

`release_blackout` setzt das Flag zurück. Voices darunter werden wieder
sichtbar.

### Master-Dimmer

`set_master <0..1>` skaliert alle Channels uniform vor dem Blackout-Latch.
Auch Color- und Pan/Tilt-Channels werden skaliert (semantisch falsch, aber
in der Praxis nur relevant wenn man master < 1 fährt — und wenn doch, dann
geht's eh in Richtung Blackout).

### Source-Capture beim Snap-then-Fade-Pattern

```yaml
# Step in einem Chase
actions:
  - { kind: snap, group: { name: head-1 }, values: { color/wheel: 0 } }      # → ch6 = 0 (white)
  - { kind: transition, group: { name: head-1 }, values: { color/wheel: 14 }, fade_seconds: 0.2 }
                                                                              # ← source = 0 (post-snap), target = 14
```

Beide Aktionen in **demselben Step** feuern auf demselben Tick. Der Engine
wendet die Snap-Action zuerst auf das Tick-Shadow-Snapshot an, dann erfasst
die Transition-Action die `sources` aus dem **post-snap-Snapshot**. Heißt
die Transition fadet von 0 → 14 statt vom alten Wert. Klassisches
"Blitz-then-Fade-back"-Pattern.

---

## 14. Hot-Reload

Der `HotReloader` läuft in einem Hintergrund-Thread mit `watchfiles` über
`data/`. Bei jeder `*.yaml`-Änderung:

1. **FixtureLibrary** rebuilden aus `data/fixture_library/`
2. **Stage** rebuilden aus dem aktiven Environment-Ordner
3. Wenn beide ohne Errors gebaut wurden: **atomar** in die Engine swapen
4. Wenn `auto_resume: true` (Default): die Chases die VORHER aktiv waren,
   neu starten — mit ihren Namen, **aber Defaults statt der ursprünglichen
   Args**

### Failure-Mode

Wenn der neue Stage-Build fehlschlägt (Validation-Errors): **die alte Stage
bleibt aktiv**. Errors landen in `engine.status().last_errors` und werden in
der GUI rot dargestellt.

→ Du kannst zehnmal kaputtes YAML schreiben, ohne dass ein einziger DMX-
Frame ausfällt.

### MCP / API: Force-Reload

`POST /api/reload` triggert ein synchrones Reload (für nach Multi-File-Edits
ohne auf den File-Watcher zu warten). Returned Liste der Errors/Warnings.

### Was Voices beim Reload passiert

Die Voices selbst werden NICHT gedroppt — ihre `targets`-Dicts sind plain
ints und überleben den Stage-Swap. Aber:

- Chase-Runner werden gedroppt (ihre Stage-Referenzen sind veraltet)
- Bei `auto_resume: true`: Chases mit denselben Namen werden neu gestartet
- Die Voice-Werte werden für 1-2 Frames gerendert bis ein neuer Chase-Tick
  sie überschreibt

→ Reload ist visuell **fast unsichtbar**. Maximal ein Frame Lücke an dem
Übergang.

---

## 15. Trigger-Schnittstellen

### Direkt aus der API

```bash
# REST
curl -X POST http://127.0.0.1:7777/api/cmd/snap_scene \
     -H "Content-Type: application/json" \
     -d '{"scene": "all_color", "args": {"col": "blau"}}'

curl -X POST http://127.0.0.1:7777/api/cmd/start_chase \
     -d '{"chase": "mh_drift_blinks", "args": {"baseline_wheel": 34}}'

curl -X POST http://127.0.0.1:7777/api/cmd/blackout
curl -X POST http://127.0.0.1:7777/api/cmd/release_blackout
curl -X POST http://127.0.0.1:7777/api/cmd/stop_all_chases

# Show-Steuerung
curl -X POST http://127.0.0.1:7777/api/show/techno_minimal/play
curl -X POST http://127.0.0.1:7777/api/show/pause
```

### MCP-Tools (für Claude / andere LLMs)

```
read_authoring_guide      → llm_instruct.md
list_show / list_environments / list_yaml(prefix?)
read_yaml(path) / write_yaml(path, content) / delete_yaml(path)
reload                   → erzwingt sofortigen Reload
snap_scene / start_chase / stop_chase / stop_all_chases
fire_slot(bank, slot_id)
blackout / release_blackout
set_bpm
set_value(address, value)   # Direkt-Channel-Override (Debug)
```

### GUI

- 9er-Pad triggert Slots (Tasten 1-9 oder Klick)
- Chases-Liste: Klick togglet start/stop
- Scenes-Liste: Klick = snap
- BPM-Slider, Master-Slider, Tap-Tempo-Button (T-Taste)
- Blackout (Leertaste, latcht), Release (Esc)

---

## 16. Cookbook

### 16.1 Static Wash

```yaml
# scenes/warm_idle.yaml
name: warm_idle
targets:
  - select: { tag: par }
    values:
      dimmer: 140
      color/red: 200
      color/green: 80
      color/blue: 20
  - select: { tag: moving_head }
    values:
      position/pan: 128
      position/tilt: 110
      dimmer: 0
```

### 16.2 4-on-the-Floor Pulse

```yaml
# chases/red_pulse.yaml — snap-then-fade pattern
name: red_pulse
loop: true
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: snap, group: { tag: par }, scene: red_full }
      - { kind: transition, group: { tag: par }, scene: red_dim, fade_seconds: 0.4 }
  - at_beat: 1
    actions:
      - { kind: snap, group: { tag: par }, scene: red_full }
      - { kind: transition, group: { tag: par }, scene: red_dim, fade_seconds: 0.4 }
  # ... at_beat 2, 3
```

### 16.3 Phasen-versetzter Sweep über zwei MH-Gruppen

```yaml
name: mh_phase_sweep
loop: true
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: transition, group: { tag: left },  scene: mh_beam_open_blue, fade_seconds: 0.8, easing: ease_in_out }
  - at_beat: 0.5             # 0.5 beats später (= ~250ms bei BPM 120)
    actions:
      - { kind: transition, group: { tag: right }, scene: mh_beam_open_blue, fade_seconds: 0.8 }
  - at_beat: 2
    actions:
      - { kind: transition, group: { tag: left },  scene: mh_park_dark, fade_seconds: 0.8 }
  - at_beat: 2.5
    actions:
      - { kind: transition, group: { tag: right }, scene: mh_park_dark, fade_seconds: 0.8 }
```

Phase-Shift = der Trick fürs "alive aber organized"-Gefühl.

### 16.4 Asymmetrischer Per-Head-Blink

```yaml
# Wenn jeder Head zu unterschiedlichen Beat-Bruchteilen blinkt → wirkt zufällig
name: random_blinks
loop: true
length_beats: 24
steps:
  - at_beat: 1.3
    actions:
      - { kind: snap, group: { name: head-1 }, values: { color/wheel: 0, dimmer: 255 } }
      - { kind: transition, group: { name: head-1 }, values: { color/wheel: 14, dimmer: 100 }, fade_seconds: 0.15 }
  - at_beat: 2.8
    actions:
      - { kind: snap, group: { name: head-2 }, values: { color/wheel: 0, dimmer: 255 } }
      - { kind: transition, group: { name: head-2 }, values: { color/wheel: 14, dimmer: 100 }, fade_seconds: 0.18 }
  # ... weitere Heads zu krummen at_beat-Werten 4.1, 5.7, 7.6, 9.4, 10.5 ...
```

Krumme `at_beat`-Werte (1.3, 2.8, 4.1, 5.7, …) statt Bruchteile von 0.25
oder 0.5 lassen es zufällig aussehen — das menschliche Hörzentrum erkennt
Patterns auf Vielfachen von 0.25/0.5 sofort, krumme Werte bleiben unter
der Wahrnehmungsgrenze für "regelmäßig".

### 16.5 Parametrisierte Color-Scene mit Palette

```yaml
# scenes/all_color.yaml
name: all_color
parameters:
  col: { type: str, default: rot, options: [rot, blau, gruen, weiss] }

targets:
  - select: { tag: bar }
    palette: { name: "${col}", facet: wheel }
    values: { dimmer: 255 }
  - select: { tag: cameo }
    palette: { name: "${col}", facet: cameo }
    values: { dimmer: 255 }
  - select: { tag: par, any_tag: [showtec, varytec] }
    palette: { name: "${col}", facet: rgb }
    values: { dimmer: 255 }
```

Bank-Slots:

```yaml
slots:
  - { id: 1, kind: scene, name: all_color, label: "Rot",  args: { col: rot } }
  - { id: 2, kind: scene, name: all_color, label: "Blau", args: { col: blau } }
  - { id: 3, kind: scene, name: all_color, label: "Grün", args: { col: gruen } }
```

Eine Scene-Datei + eine `palettes.yaml` = beliebig viele Color-Variants
ohne Code-Duplikation.

### 16.6 Show-Skript mit Build → Drop → Reset

```yaml
# shows/build_drop_reset.yaml
name: build_drop_reset
bpm: 130
loop: false

script:
  # 16-Bar build
  - { do: snap_scene, scene: warm_idle, fade: 1.0 }
  - { do: start_chase, chase: par_kick_pulse }
  - { do: wait, bars: 8 }

  # Build phase 2 — strobing addiert
  - { do: start_chase, chase: build_strobe }
  - { do: wait, bars: 4 }

  # Anticipation halt — alles auf einer Farbe einfrieren
  - { do: stop_all_chases }
  - { do: snap_scene, scene: red_full }
  - { do: wait, bars: 2 }

  # DROP
  - { do: snap_scene, scene: white_hit }
  - { do: wait, beats: 1 }
  - { do: start_chase, chase: peak_chaos }
  - { do: wait, bars: 16 }

  # Reset
  - { do: stop_all_chases }
  - { do: snap_scene, scene: warm_idle, fade: 4.0 }
  - { do: wait, seconds: 4 }
```

### 16.7 Chase mit "Bewegung an/aus" via drift_seconds

Da `when:`-Conditionals nicht existieren, simuliere "Bewegung an/aus" über
den Drift-Parameter:

```yaml
parameters:
  drift_seconds: { type: float, default: 3.5, min: 0, max: 30 }
```

Aufruf mit `args: { drift_seconds: 0 }` → Bewegungs-Transitions sind sofort
(snap), heißt Heads bleiben effektiv stehen. Aufruf mit `drift_seconds: 8`
→ langsame, sichtbare Drift.

---

## 17. Stolperfallen

### 17.1 `${...}` ohne Quotes in Flow-Mappings

```yaml
# KAPUTT
palette: { name: ${col}, facet: wheel }
# OK
palette: { name: "${col}", facet: wheel }
```

### 17.2 Snap-then-Fade im selben Step

Zwei Aktionen im selben Step feuern auf demselben Tick. Wenn Action 1 ein
Snap auf Channel X ist, sieht Action 2 (Transition) den **post-snap-Wert**
als Source. Das ist gewollt — aber wenn du das nicht weißt, denkst du der
Source sei der vorherige Wert.

### 17.3 Voices persistieren — auch nach Fade-Ende

Eine Transition-Voice fadet bis Fade-End und HÄLT dann ihren Target-Wert
**für immer**. Wenn du nicht willst, dass eine Scene "haftet", musst du
sie explizit überschreiben oder droppen.

### 17.4 Chase-Args propagieren nicht in referenzierte Scenes

```yaml
# Chase mit color-Parameter
parameters: { col: { type: int, default: 14 } }
steps:
  - at_beat: 0
    actions:
      - { kind: snap, group: { tag: bar }, scene: bar_red }   # ← bar_red wird mit IHREN defaults gerendert, NICHT mit ${col}
```

Wenn Color parametrisierbar sein soll, schreibe inline:

```yaml
- kind: snap
  group: { tag: bar }
  values: { color/wheel: "${col}", dimmer: 255 }
```

### 17.5 macro=0 = Blackout auf Cameos

Auf der Cameo Flat 1 TRI 3W IR ist Channel 6 (`effect/macro`) **bei Wert
0-4** als "Blackout" dokumentiert — überschreibt die direkten RGB-Channels.
Die Profil-Notes warnen davor.

Workaround: `effect/macro: 10` (red preset) oder ein anderer Wert ≥5 in
Scenes die das Cameo addressieren. Das `cameo`-Facet in `palettes.yaml`
macht das automatisch.

### 17.6 Master-Dimmer-Position auf Eurolite PAR-64

Der Eurolite LED PAR-64 RGB Spot hat den Master-Dimmer auf **Channel 4**,
nicht Channel 1. RGB sitzt auf Channel 1-3. Heißt: ohne Dimmer ≥ 1 ist
nichts zu sehen, egal wie hoch RGB sind. Bei Scenes also immer
`dimmer: 255` (oder einen sichtbaren Wert) mitschreiben.

### 17.7 Geräte im Auto-/Sound-Mode

Wenn ein Fixture nicht reagiert, ist die häufigste Ursache: **es ist nicht
im DMX-Mode**. Das Display zeigt dann irgendwas anderes als `d.xxx` oder
`A001` (Adresse). Stattdessen `AUT1`, `So.xx`, `SLav` etc.

DMX-Setting variiert pro Fixture. Bei den Geräten in `stolz`:

| Gerät | DMX-Mode-Indikator |
|---|---|
| TMH Bar S120 | Display zeigt `Addr` + Adresse |
| Pad 5 Fourty | Display zeigt `A100` (= DMX-Adresse 100, das `A` ist Display-Format!) |
| RX350 | Display zeigt `d.xxx` |
| Cameo Flat | Display zeigt `Add` + Adresse, plus `dr.6` (= 6CH-Mode) |

### 17.8 DMX-Termination

Bei längeren DMX-Ketten (besonders mit billigen Adaptern wie dem Eurolite
Pro MK2) → Terminator (120Ω zwischen Pin 2 und 3 in einem XLR-Stecker)
am letzten Gerät der Kette. Sonst: Reflexionen, Bit-Fehler, sporadisches
Flackern auf den hinteren Adressen.

### 17.9 Refresh-Rate-Cap

Der Eurolite USB-DMX512 PRO MK2 schafft 44Hz (DMX-Standard) NICHT
zuverlässig — siehe QLC+ Forum und Belegung der Hardware. Bei Flickern:
`lightning run --refresh-hz 25` (oder runter bis es stabil ist).

### 17.10 Scene-Werte == 0 löschen NICHT

Eine Scene mit `dimmer: 0` schreibt **aktiv** den Wert 0 in den Channel —
sie löscht NICHT die Voice einer früher gestarteten Scene. Wenn du eine
Scene "wirklich aus" haben willst, brauchst du entweder eine Blackout-
Action oder muss eine spätere Voice mit höherem Dimmer drüber.

---

## 18. Quick-Reference

### Files

| Pfad | Inhalt |
|---|---|
| `data/fixture_library/<name>.yaml` | Fixture-Profile (geräte-typen) |
| `data/environments/<env>/environment.yaml` | Patching: Profile + Adressen + Tags |
| `data/environments/<env>/palettes.yaml` | (optional) Cross-Fixture-Farb-Definitionen |
| `data/environments/<env>/scenes/<name>.yaml` | Eine Scene pro File |
| `data/environments/<env>/chases/<name>.yaml` | Ein Chase pro File |
| `data/environments/<env>/banks/<name>.yaml` | 9-Slot-Layouts |
| `data/environments/<env>/shows/<name>.yaml` | Skriptierte Choreografien |

### Selektor-Formen

```yaml
{ name: "head-1" }           # exakt
{ tag: "par" }               # ein Tag
{ tags: [par, front] }       # AND
{ any_tag: [par, ledbar] }   # OR
{ all: true }                # alle
```

### Action-Kinds (Chase)

```yaml
- { kind: snap, group: <selector>, scene: <name> }                     # oder values: {...}
- { kind: transition, group: <selector>, scene: <name>, fade_seconds: <float> }
- { kind: release, group: <selector> }
```

### Show-Action-Verbs

```
snap_scene  start_chase  stop_chase  stop_all_chases
fire_slot   blackout  release_blackout  set_values
set_bpm  log
wait  wait_chase  wait_group  loop
```

### Parameter-Typen

| Typ | Constraints |
|---|---|
| `int` | min, max |
| `float` | min, max |
| `str` | options (Whitelist) |
| `bool` | – |

### Wo Platzhalter erlaubt sind

| Stelle | Form | Beispiel |
|---|---|---|
| `values:` Werte (numerisch) | `"${name}"` | `dimmer: "${dim}"` |
| `fade_seconds` (Chase action) | `"${name}"` oder literal | `fade_seconds: "${fade}"` |
| `palette.name` | `"${name}"` | `palette: { name: "${col}", facet: wheel }` |

### Wo Platzhalter NICHT funktionieren (v1)

- `at_beat` / `at_seconds` (literal float erforderlich, Schema-Validation
  prüft gegen `length_*`)
- `length_beats` / `length_seconds`
- Selektor-Felder (`tag`, `name`)
- `palette.facet` (immer literal — Facet hängt vom Fixture-Typ ab)
- Scene-Refs in Chase-Actions (`scene: <name>` braucht literalen Namen)

### YAML-Quoting-Pflicht

`${...}` in **Flow-Mappings** (`{ ... }` einzeilig) → quoten:
```yaml
{ key: "${name}" }
```
In Block-Mappings (mit Einrückung) → optional:
```yaml
key:
  inner: ${name}    # geht
```

### Trigger-Forms

```python
# API-Calls oder MCP-Tools
snap_scene(scene_name, args={...}, fade=0.0)
start_chase(chase_name, args={...})
fire_slot(bank_name, slot_id)
```

```yaml
# Bank-Slot
- id: 5
  kind: scene
  name: <scene_name>
  args: {...}
```

```bash
# HTTP
curl -X POST http://127.0.0.1:7777/api/cmd/<op> \
     -H "Content-Type: application/json" \
     -d '{"scene": "...", "args": {...}}'
```

---

## Anhang A: Validierungs-Errors verstehen

Wenn `reload` Errors zurückgibt, liest du sie wie folgt:

**Pydantic-Validation-Error**:
```
data/environments/stolz/scenes/foo.yaml: validation errors:
  - targets.0.values.color/red: must be 0..255 (got 300)
```
→ Datei `foo.yaml`, im ersten target im values-Dict, der Wert 300 für
`color/red` ist out-of-range. Fix: zwischen 0 und 255.

**Cross-Reference-Error**:
```
chase 'red_pulse': step 0 action 1 references unknown scene 'red_dim'
```
→ Scene `red_dim` existiert nicht. Entweder die Scene anlegen oder den
Chase fixen.

**Palette-Resolve-Error**:
```
scene 'all_color' target 0: unknown palette 'rot'
```
→ Palette nicht in `palettes.yaml` — dort hinzufügen oder Scene-Ref ändern.

Errors werden **kollektiv** gesammelt — du siehst alles auf einmal, nicht
nur den ersten Fehler. Beim Reload wird der ganze Block angezeigt; nichts
wird in die laufende Engine übernommen, solange auch nur ein Error besteht.

---

*Dieses Dokument ist die technische Grund-Referenz fürs Programmieren mit
LightningMCLLM. Wenn du Show-Design-Prinzipien suchst — wie man eine
"gute" Show schreibt — siehe [`llm_instruct.md`](llm_instruct.md). Für
Architektur-Überblick: [`ARCHITEKTUR.md`](ARCHITEKTUR.md).*
