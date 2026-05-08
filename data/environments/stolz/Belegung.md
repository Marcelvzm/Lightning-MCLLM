# DMX-Belegung — Environment `stolz`

Universe 0, single-rig.

## Inventar (Stand nach Reduktion)

Behaltene Geräte. Varytec Pad, Eurolite PAR-64 und 3× Showtec wurden
bewusst entfernt (waren Test-Setup, finales Rig läuft mit weniger).

| # | Fixture | Profil | Mode |
| --- | --- | --- | --- |
| 1 | Eurolite LED TMH Bar S120 (4 Heads) | `eurolite_tmh_bar_s120_head` | 38CH |
| 2 | Involight LED RX350 (4-Flower-Bar) | `involight_led_rx350` | 2CH (`d-P2`) |
| 3 | 3× Cameo Flat 1 TRI 3W IR | `cameo_flat_par_tri_3w_ir` | 6CH |

Summe belegter Channels: 58 von 512.

## Adress-Layout

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

Block B — Pars (112-129)
 112-117   Cameo Flat 1 TRI 3W IR  #1    6 channels
 118-123   Cameo Flat 1 TRI 3W IR  #2    6 channels
 124-129   Cameo Flat 1 TRI 3W IR  #3    6 channels

 130-512   ─── reserviert für weitere Pars ───
```

Adressen 100-111 sind aktuell unbelegt (waren Varytec + PAR-64). Wenn neue
Pars dazukommen, kann von 100 oder 130 ausstartet werden — keine
Re-Adressierung der Cameos nötig.

## Patch-Sheet zum Abfotografieren

| # | Gerät | Mode | Startadresse | Range |
| --- | --- | --- | --- | --- |
|  1 | Eurolite TMH Bar S120 | 38CH | **001** | 1-38 |
|  2 | Involight LED RX350 | 2CH (`d-P2`) | **039** | 39-40 |
|  3 | Cameo Flat 1 TRI 3W IR  #1 | 6CH | **112** | 112-117 |
|  4 | Cameo Flat 1 TRI 3W IR  #2 | 6CH | **118** | 118-123 |
|  5 | Cameo Flat 1 TRI 3W IR  #3 | 6CH | **124** | 124-129 |

## Tag-Konvention

| Fixture | Tags |
| --- | --- |
| Bar Heads (1-4) | `moving_head, mh, bar, head-N, left/right, inner/outer` |
| Involight RX350 | `effect, beam_bar` |
| Cameos | `par, flat, cameo, front` |

Bedeutung der Tags für die Scenes:

* `tag: par` → matcht aktuell die 3 Cameos (alle Pars im Rig sind Cameos).
* `tag: bar` → matcht alle 4 Bar-Heads.
* `tag: cameo` → matcht die 3 Cameos (gleich wie `tag: par` aktuell, aber
  semantisch Macro-bewusst — wichtig für die Cameo-spezifische Macro-Override).
* `tag: front` → matcht die 3 Cameos (sind aktuell die einzigen Front-Pars).
* `tag: beam_bar` → matcht nur die RX350.
* `tag: head-N`, `tag: left/right`, `tag: inner/outer` → Per-Head-Adressierung der Bar.

Scenes/Chases sind generell tag-basiert geschrieben — wenn weitere Pars
dazukommen, matchen sie automatisch ohne Code-Anpassung. Ausnahme: die
hard-coded Per-Cameo-Patterns (z.B. `pars_random_blinks`) referenzieren
explizit `name: cameo-1` etc.; falls weitere Pars dazu kommen die ähnlich
behandelt werden sollen, in jenen Chases erweitern.
