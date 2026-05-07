# DMX-Belegung — Environment `stolz`

Universe 0, single-rig.

## Inventar

| # | Fixture | Profil | Mode |
| --- | --- | --- | --- |
| 1 | Eurolite LED TMH Bar S120 (4 Heads) | `eurolite_tmh_bar_s120_head` | 38CH |
| 2 | Involight LED RX350 (4-Flower-Bar) | `involight_led_rx350` | 2CH (`d-P2`) |
| 3 | Varytec Pad 5 Fourty | `varytec_pad_5_fourty` | 7CH |
| 4 | Eurolite PAR 64 RGB Spot | `eurolite_led_par_64_rgb_spot` | 5CH (R, G, B, Dim, Strobe) |
| 5 | 3× Cameo Flat 1 TRI 3W IR | `cameo_flat_par_tri_3w_ir` | 6CH |
| 6 | 3× Showtec Par (ohne Modell, generic) | `showtec_par_6ch` | 6CH (R, G, B, Palette, Strobe, Mode) |

Summe belegter Channels: ~92 von 512.

## Adress-Layout

Zwei Blöcke. Innerhalb eines Blocks alle Geräte lückenlos hintereinander.
Zwischen den Blöcken ein Puffer für künftige Erweiterungen.

```
Block A — Komplexe Geräte (1-41)
   1- 38   Eurolite TMH Bar S120        38 channels
                                          ├ head-1   1- 9
                                          ├ head-2  10-18
                                          ├ head-3  19-27
                                          ├ head-4  28-36
                                          └ chaser  37-38   (global, ungenutzt)
  39- 40   Involight LED RX350           2 channels   (2CH mode `d-P2`)
                                          ch 41 frei (war 3CH-Reservierung)

  42- 99   ─── Puffer für weitere Movers / Effekte ───

Block B — Pars (100-150)
 100-106   Varytec Pad 5 Fourty          7 channels
 107-111   Eurolite PAR 64 RGB Spot      (5 reserviert; Mode tbd)
 112-117   Cameo Flat 1 TRI 3W IR  #1    6 channels
 118-123   Cameo Flat 1 TRI 3W IR  #2    6 channels
 124-129   Cameo Flat 1 TRI 3W IR  #3    6 channels
 130-135   Showtec Par  #1               6 channels (6CH RGB+Palette+Strobe+Mode)
 137-142   Showtec Par  #2               6 channels
 144-149   Showtec Par  #3               6 channels

 151-512   ─── reserviert für weitere Pars ───
```

## Patch-Sheet zum Abfotografieren

| # | Gerät | Mode | Startadresse | Range |
| --- | --- | --- | --- | --- |
|  1 | Eurolite TMH Bar S120 | 38CH | **001** | 1-38 |
|  2 | Involight LED RX350 | 2CH (`d-P2`) | **039** | 39-40 |
|  3 | Varytec Pad 5 Fourty | 7CH | **100** | 100-106 |
|  4 | Eurolite PAR 64 RGB Spot | 5CH | **107** | 107-111 |
|  5 | Cameo Flat 1 TRI 3W IR  #1 | 6CH | **112** | 112-117 |
|  6 | Cameo Flat 1 TRI 3W IR  #2 | 6CH | **118** | 118-123 |
|  7 | Cameo Flat 1 TRI 3W IR  #3 | 6CH | **124** | 124-129 |
|  8 | Showtec Par  #1 | 6CH | **130** | 130-135 |
|  9 | Showtec Par  #2 | 6CH | **137** | 137-142 |
| 10 | Showtec Par  #3 | 6CH | **144** | 144-149 |

## Begründung

- **Block A unten (1-41)**: Bar + RX350 lückenlos hintereinander. Bar belegt
  die unteren 38, RX350 schließt direkt an. Adressen am Gerät = exakt was die
  Doku sagt, kein Rätselraten.
- **42-99 als Puffer**: Reicht für einen zusätzlichen Moving-Head (16-21
  channels), Hazer-Controller, Laser-Bridge oder einen weiteren Effect-Bar.
- **Block B ab 100**: Klare visuelle Trennung. Mentales Modell "alles ab
  100 = Pars".
- **Pars lückenlos**: Wenn sich später ein Channel-Count verschiebt
  (Showtec 7→9 channels, PAR-64 5→3, …) muss zwar alles dahinter
  umadressiert werden — aber das ist ein einmaliger Aufwand und passiert
  ohnehin nur wenn ein Mode-Wechsel beabsichtigt ist.
- **151-512 frei**: Genug für ~50+ weitere Pars; neue Geräte werden hinten
  angehängt ohne den Rest anzufassen.

## Tag-Konvention

Tags sind die Brücke zwischen Hardware und Show-Authoring. Scene-Selektoren
greifen nach Tags, nicht nach Adressen — deshalb sollte die Tag-Vergabe
durchdacht sein.

| Fixture | Tags |
| --- | --- |
| Bar Heads (1-4) | `moving_head, mh, bar, head-N, left/right, inner/outer` |
| Involight RX350 | `effect, beam_bar` |
| Varytec Pad | `par, front` |
| Eurolite PAR-64 | `par, spot, back` (typischer Backlight-Einsatz) |
| Cameos | `par, flat, front` |
| Showtec | `par` + Position abhängig vom Setup |

Damit greift `select: { tag: par }` über **alle** Pars, `select: { tag: front }`
nur über die vorderen, `select: { tag: bar }` nur über die TMH-Heads, etc.

## Offene Punkte

_(alle offenen Punkte geklärt — alle Geräte gepatched.)_
