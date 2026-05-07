# GUI-Bedienung

Die GUI ist auf einem Bildschirm (Laptop, Tablet, Phone) bedienbar.
Browser auf `http://localhost:7777` nach `lightning run`. Vier Bereiche
von oben nach unten plus Tastatur-Shortcuts.

---

## Header

```
LightningMCLLM    ● env: default  [default ▼]  [Reload]
```

* **Grüner / roter Punkt**: WebSocket-Status. Grün = Live-Status fließt
  rein. Rot = Verbindung weg (sollte automatisch nach 1 Sek wieder grün
  werden).
* **`env: …` + Dropdown**: aktuelle Umgebung. Dropdown wechseln →
  atomarer Switch zur anderen Umgebung. Voices werden gedroppt, neue
  Show wird geladen, kein Engine-Neustart.
* **`Reload`-Button**: forciert Re-Read von `data/`. Brauchst du nur,
  wenn du außerhalb des Watchers (z. B. `git checkout`) Files geändert
  hast — File-Watcher reloadet sonst automatisch.

---

## Status-Panel (links oben)

```
BPM: 128.0    Source: manual    Beat: 18847.45    Master: 1.00
DMX: ✓ null   Voices: 3         NonZero ch: 16    Tick: 33.3 ms / 30 Hz
```

| Feld | Bedeutung |
| --- | --- |
| **BPM** | Aktuelles Tempo |
| **Source** | `manual` / `tap` / `audio` / `audio (silent)` — wer steuert die Clock |
| **Beat** | Beat-Position seit Clock-Start (Beats, monoton wachsend). **Rot** wenn Clock pausiert oder Audio stumm. |
| **Master** | Globaler Dimmer 0…1 |
| **DMX** | `✓ <name>` grün wenn Hardware/Null verbunden, sonst rot |
| **Voices** | Wie viele aktive Paintbrushes gerade Channels schreiben |
| **NonZero ch** | Wie viele Channels gerade > 0 sind (gute Schnellprüfung "geht überhaupt was raus?") |
| **Tick** | Gemessene Frame-Zeit. Sollte nahe 33 ms (30 Hz) liegen. Dauerhaft >50 ms = System überlastet. |

Drunter zwei Slider-Reihen plus Genre-Reihe und Errors-Bereich.

### BPM-Reihe

* **Slider 40–240** — direkt ziehen, BPM wird live gesetzt
  (`source: manual`)
* **Zahlenfeld** — präzise eingeben + Enter
* **`Tap`-Button** — drei oder mehr Mal im Beat klopfen, ab dem dritten
  Tap lockt die BPM auf den Durchschnitt der Inter-Tap-Intervalle
  (`source: tap`). Tastatur: **`T`**.

### Master-Reihe

* **Master-Slider 0–1** — globaler Dimmer
* **`BLACKOUT`** (rot) — sofort alles auf 0. Latcht (bleibt aktiv).
  Tastatur: **`Leertaste`**.
* **`Release`** — Blackout-Latch lösen, Voices darunter werden wieder
  sichtbar. Chases laufen unter dem Blackout weiter — beim Release
  setzen sie sofort dort fort, wo sie wären. Tastatur: **`Esc`**.
* **`Stop chases`** — alle laufenden Chases beenden. Snap-Scenes
  (warm_idle etc.) bleiben unter den Chase-Voices liegen und werden
  wieder sichtbar.

### Genre-Reihe

* Dropdown wählen (`techno`, `house`, etc.) → **`Apply`** → setzt die
  BPM aus dem Genre-Preset und startet den Lead-Chase. Bestehende
  Chases werden vorher gestoppt.

### Errors-Bereich

Wenn die Engine Fehler protokolliert (kaputtes YAML, fehlende
Scene-Reference), erscheinen sie hier in Rot. Maximal die letzten 8.

---

## Bank-Panel (rechts oben)

```
Bank: [starter ▼]

┌──────────┬──────────┬──────────┐
│ 1  Idle  │ 2  Red.. │ 3  MH B. │
│ scene    │ scene    │ scene    │
├──────────┼──────────┼──────────┤
│ 4  MH A. │ 5  Red P.│ 6  MH S. │
│ scene    │ chase    │ chase    │
├──────────┼──────────┼──────────┤
│ 7  Color │ 8   —    │ 9 BLACK. │
│ chase    │          │ blackout │
└──────────┴──────────┴──────────┘
```

* **Dropdown**: welche Bank aktiv ist (falls mehrere existieren).
* **3×3-Pad**: jeder belegte Slot ist klickbar.
  * Scene-Slot → snap_scene
  * Chase-Slot → start_chase (aktive Chase-Slots werden gelb hinterlegt)
  * Blackout-Slot → blackout (rot eingefärbt)
  * Release-Slot → Voices der Selektion droppen
* **Tastatur**: **`1`–`9`** feuert den jeweiligen Slot. Das ist der
  Hauptweg, live zu spielen.

---

## Show-Panel

Drei Spalten — alles was die geladene Show kennt:

* **Scenes** — Liste aller Scenes. Klick = snap_scene.
* **Chases** — Liste mit Länge + Step-Anzahl. Klick togglet
  **start ↔ stop**. Aktive Chases werden gelb hinterlegt.
* **Fixtures** — readonly: Name, DMX-Adresse, Footprint, Tags. Zur
  Orientierung.

Diese drei Spalten ermöglichen sehr feinkörniges Triggern, das die
9er-Bank nicht abdeckt.

---

## Universe-Visualizer

Ein 1024×64-Canvas, das die letzten 512 DMX-Channels als Pixel-Streifen
zeigt. Jeder Channel = 2 Pixel breit. Helligkeit = Channel-Wert
(0…255). Updated 5×/Sek über die Status-Updates.

Brauchst du, um:

* zu prüfen, ob Lichter überhaupt rausgehen (auch ohne Hardware)
* zu sehen, welche Bereiche aktiv sind (Pars an Adresse 1–7 / 8–14
  etc.)
* Chase-Bewegungen visuell zu verifizieren

---

## Tastatur-Shortcuts

| Taste | Aktion |
| --- | --- |
| `1` … `9` | Bank-Slot feuern |
| `Leertaste` | BLACKOUT (latcht) |
| `Esc` | Blackout lösen |
| `T` | Tap-Tempo |

Wenn ein Input-Feld fokussiert ist, sind die Shortcuts deaktiviert — du
kannst also normal in BPM-Zahlen tippen, ohne dass die Leertaste das
Blackout auslöst.

---

## Typischer Live-Ablauf

1. Engine starten: `lightning run`
2. Browser auf `http://localhost:7777`
3. Genre wählen → Apply → BPM und Lead-Chase laufen
4. Mit Bank-Slots (`1`…`9`) zwischen Scenes/Chases live wechseln
5. Bei Build / Drop: `7` für Strobe-Build, dann `5` für Hauptchase
6. Übergang zwischen Tracks: `Leertaste` für Blackout, neuen Slot
   wählen, `Esc` zum Aufgehen
7. Wenn das Tempo wechselt: BPM-Slider oder `T` mehrmals tippen
8. Wenn ein Chase nicht passt: Klick auf seinen Namen in der
   Chase-Liste = stop, anderen klicken = start

---

## Vom Phone / iPad steuern

`lightning run --host 0.0.0.0` — bindet die GUI auf alle Interfaces.
Phone im selben WLAN auf `http://<rechner-ip>:7777` öffnen. Layout
faltet bei <800 px in eine Spalte; Bank-Pad bleibt 2-spaltig.
