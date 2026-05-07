# GUI-Bedienung

Die GUI ist auf einem Bildschirm (Laptop, Tablet, Phone) bedienbar.
Browser auf `http://localhost:7777` nach `lightning run`. Sechs Bereiche
plus Tastatur-Shortcuts.

---

## Header

```
LightningMCLLM    ● env: default  [default ▼]  [Reload]
```

* **Grüner / roter Punkt**: WebSocket-Status. Grün = Live-Status fließt
  rein. Rot = Verbindung weg (sollte automatisch nach 1 Sek wieder grün
  werden).
* **`env: …` + Dropdown**: aktuelle Umgebung. Dropdown wechseln →
  atomarer Switch zur anderen Umgebung. Voices werden gedroppt, neuer
  Stage wird geladen, kein Engine-Neustart.
* **`Reload`**: forciert Re-Read von `data/`. Brauchst du nur, wenn du
  außerhalb des Watchers (z. B. `git checkout`) Files geändert hast —
  File-Watcher reloadet sonst automatisch.

---

## Status-Panel

```
BPM: 128.0    Source: manual    Beat: 18847.45    Master: 1.00
DMX: ✓ null   Voices: 3         NonZero ch: 16    Tick: 33.3 ms / 30 Hz
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

Drunter:

* **BPM-Reihe**: Slider, Zahlenfeld, **`Tap`** (Tastatur: `T`) — drei
  oder mehr Mal im Beat klopfen, ab dem dritten Tap lockt die BPM.
* **Master-Reihe**: Master-Slider, **`BLACKOUT`** (rot, Tastatur:
  Leertaste), **`Release`** (Tastatur: Esc), **`Stop chases`**.
* **Errors-Bereich**: zeigt die letzten 8 Engine-Errors in Rot.

---

## Show-Panel

Hier liegt die Hauptaktion: scripted Auto-Shows starten und steuern.

```
Show  [techno_60min ▼]  [▶ Play] [⏸] [▶ Resume] [↺ Reset] [■ Stop]
[ Play Mode: OFF ]   When ON, the show's keybindings drive the keyboard.
┌──────────────────────────────────────────────────────────────┐
│ RUNNING  techno_60min  elapsed: 12:34.5  action: wait 30s   │
└──────────────────────────────────────────────────────────────┘
```

* **Show-Dropdown**: alle in `data/environments/<env>/shows/*.yaml`
  definierten Shows. Auswahl bestimmt nur, was beim Klick auf Play läuft
  und welche Keybindings im Play-Mode aktiv sind.
* **▶ Play**: startet die ausgewählte Show **von vorn** (resettet
  internen State).
* **⏸ Pause**: pausiert das Skript. Laufende Chases laufen weiter.
* **▶ Resume**: läuft pausiertes Skript weiter.
* **↺ Reset**: setzt das Skript auf den Anfang und läuft weiter.
* **■ Stop**: stoppt das Skript komplett. Chases bleiben weiter laufen.
* **Play Mode Toggle**: umschalten zwischen Default-Tastatur und
  Show-Keybindings (siehe Tastatur-Shortcuts).
* **Status-Box** unten zeigt `RUNNING/PAUSED/COMPLETED`, Show-Name,
  Skript-Position (verstrichene Sekunden), aktuelle Action,
  Wait-Beschreibung.

---

## Triggers-Panel — drei scrollbare Listen

Replaces the old 3×3 bank pad. Scrollbare Listen, weil bei einer großen
Show schnell 30+ Chases und 50+ Scenes existieren können.

```
[ filter… ]                      click = fire · click chase again = stop
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Scenes (12) │  │ Chases (8)   │  │ Fixtures (4) │
├─────────────┤  ├──────────────┤  ├──────────────┤
│ blackout    │  │ red_pulse    │  │ par-l        │
│ warm_idle   │  │ mh_sweep     │  │ par-r        │
│ red_full    │  │ par_walk     │  │ mh-l         │
│ ...         │  │ ...          │  │ mh-r         │
└─────────────┘  └──────────────┘  └──────────────┘
```

* **Filter-Feld** oben: Live-Suche über alle drei Listen
* **Scenes**: Klick = `snap_scene`
* **Chases**: Klick togglet **start ↔ stop**. Aktive Chases werden gelb
  hinterlegt.
* **Fixtures**: readonly, zeigt Name, DMX-Adresse, Footprint, Tags
* Wenn **Play Mode** aktiv ist: jedes Listen-Item, das in den
  Keybindings der laufenden Show vorkommt, bekommt ein
  **Tasten-Badge** ([ K ]) eingeblendet

---

## Banks-Panel

Banks bleiben erhalten, aber als Sekundär-UI: dropdown + horizontale
Reihe mit allen Slots der ausgewählten Bank.

```
Bank: [starter ▼]   [1 Idle] [5 Red Pulse] [9 BLACKOUT]
```

Klick = Slot feuern. Im **Default-Modus** (Play Mode aus) feuert
Tastatur `1`–`9` die ersten neun Slots der ausgewählten Bank.

---

## Universe-Visualizer

Unverändert. 1024×64-Canvas, 512 Channels nebeneinander, Helligkeit =
Channel-Wert. Updated 5×/Sek.

---

## Tastatur-Shortcuts

### Default-Modus (Play Mode AUS)

| Taste | Aktion |
| --- | --- |
| `1` … `9` | Bank-Slot 1–9 der aktiven Bank feuern |
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

Tastendruck löst die zugewiesene Aktion aus. Default-Tasten (1-9 für
Bank-Slots, T für Tap) **sind deaktiviert** — du hast die Show-eigene
Tastenbelegung explizit gewählt.

**Universelle Sicherheit funktioniert immer**:

* `Leertaste` → Blackout
* `Esc` → Release Blackout

(Damit du in jeder Situation einen Notaus hast, auch wenn die
Show-Bindings keine Blackout-Taste definieren.)

Wenn ein Input-Feld fokussiert ist, sind Shortcuts deaktiviert — du
kannst also normal in BPM-Zahlen tippen.

---

## Typischer Live-Ablauf

### Vor der Party (Aufbau / Setup)

1. Engine starten: `lightning run --host 0.0.0.0`
2. Browser auf `http://<rechner-ip>:7777` (Phone als Backup-Steuerung)
3. Im Show-Dropdown die Show wählen, die du programmiert hast
4. ▶ Play
5. Play Mode an
6. Bier holen — die Show läuft autonom, du kannst per Keybindings
   Akzente setzen

### Während der Party

Du arbeitest mit Keybindings (laut Show-YAML), feuerst zwischendurch
Scenes/Chases manuell aus den Listen, oder lässt einfach die Show
laufen.

* Track passt nicht zur Show? → ⏸ Pause, neue Show wählen, ▶ Play
* DJ hat einen Drop angekündigt? → manuell entweder mit dem Show-Key
  oder per Klick auf den Chase in der Liste feuern
* Es wird zu hektisch? → BLACKOUT (Leertaste), nach 1 Bar Esc

### Vom Phone / iPad

`lightning run --host 0.0.0.0` bindet auf alle Interfaces. Layout
faltet bei <800 px in eine Spalte.
