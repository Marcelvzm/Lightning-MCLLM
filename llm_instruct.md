# How to write professional lightshows with LightningMCLLM

*Instructions for any LLM (Claude or otherwise) tasked with authoring shows
through this system's MCP interface. Read this **before** writing a single
line of YAML.*

---

## 0. What you are actually doing

You are not "decorating with light". You are designing **controlled
attention over time** for a human audience whose perception is governed by
information-theoretic principles.

Every channel value, every fade time, every phase offset is *a choice that
shapes what the audience notices*. The emotional impact of a great show is
the predictable consequence of correct choices across a small number of
dimensions: **time, space, contrast, coherence, entropy.**

A bad show is not "ugly" — it is **information-theoretically wrong**: too
flat (boring), too noisy (overwhelming), too random (meaningless), or
incoherent (confusing).

The single best heuristic: **a great show is maximally interesting just
short of becoming unreadable.** That spot — the *edge of chaos* — is where
all the work goes.

This document tells you how to find it.

---

## 1. The five commandments

Memorise these. Every other section is corollary.

1. **Maximise structured surprise** — not chaos, not order, the edge
   between them. The audience must be able to predict *just enough* to be
   gratified when you confirm the prediction, and *just little enough* to
   be surprised when you break it.

2. **Manage entropy as a curve, not a constant** — every show is a journey
   between order and chaos. Plan the curve before writing a single scene.

3. **Coherence is non-negotiable** — local complexity is allowed; global
   incoherence is not. Every variation must trace back to a recognisable
   visual language: a palette, a motion logic, a timing grid.

4. **Less-is-more is mathematics, not taste** — running every effect at
   maximum collapses information content to zero. Reserve the rig's full
   power for rare peaks that *mean* something.

5. **Light supports, never competes** — with the music, with the performer,
   with the dramaturgy. Do not show off the rig. Show off the song.

If a choice violates one of these, it is wrong, regardless of how it looks
in isolation.

---

## 2. Where you are working

LightningMCLLM is a DMX show engine. You are not running it directly — you
are *authoring data files* that the engine plays out. Concretely:

```
data/
├── fixture_library/                   ← profiles ("what kind of device")
│   └── *.yaml
└── environments/
    └── <env>/                         ← one rig (one stage)
        ├── environment.yaml           ← which fixtures, where patched, with what tags
        ├── scenes/*.yaml              ← named static states
        ├── chases/*.yaml              ← timed sequences
        ├── banks/*.yaml               ← launchpad-style trigger layouts
        └── genres.yaml                ← BPM + lead-chase presets
```

Read `technical_details.md` once, end-to-end, before authoring. It is the
spec for the YAML schema, the chase grammar, the voice model, and the
selector system. **You cannot write good YAML without understanding the
voice model in §7 and the chase grammar in §6.**

### MCP tools you have

| Tool | When to use |
| --- | --- |
| `list_show` | **Always start here.** Fixtures, scenes, chases, banks, genres |
| `list_yaml(prefix)` | List existing files |
| `read_yaml(path)` | Read existing — *prefer adapting an existing scene/chase to writing from scratch* |
| `write_yaml(path, content)` | Create or replace a YAML file |
| `delete_yaml(path)` | Remove a file |
| `reload` | Force re-read after you write. **Always reload after a batch of edits, then read the returned errors.** |
| `snap_scene(name)`, `start_chase(name)`, `blackout`, `release_blackout` | **Live-test what you wrote.** This is your feedback loop. |
| `fire_slot(bank, slot_id)` | Test a bank slot |
| `set_bpm(bpm)`, `tap` | Set tempo |
| `status`, `list_environments`, `switch_environment(name)` | Orientation |

Your loop: **inspect → plan → author → reload → validate errors → live-test
→ iterate.** Skip any step at your peril.

### Selectors (the most important pattern)

Scenes target fixtures by **selector**, never by raw DMX address:

```yaml
{ name: "MH-Left" }            # exact instance
{ tag: "moving_heads" }        # any fixture with this tag
{ tags: [moving_head, left] }  # AND — all of these tags
{ any_tag: [par, ledbar] }     # OR — at least one
{ all: true }                  # everything
```

This is **why scenes are portable across environments** and why **good tag
discipline matters more than fancy selectors**. Before authoring, read the
fixture instances and confirm the tag vocabulary is consistent (e.g.
`front`, `back`, `left`, `right`, `par`, `moving_head`, `bar`, `accent`).
If it isn't, propose a tag taxonomy to the user *before* writing scenes
that depend on it.

### Roles, not channel offsets

Channels are addressed by **role**, never by offset, in scenes/actions:

```yaml
values: { dimmer: 200, color/red: 255, color/blue: 50 }
```

Common roles: `dimmer`, `shutter`, `strobe`, `color/{red,green,blue,white,
amber}`, `position/{pan,tilt,pan_fine,tilt_fine}`, `gobo/{wheel,rotation,
index}`, `focus`, `zoom`, `iris`, `prism`, `effect/macro`. The full list is
in `core/fixtures.py:KNOWN_ROLES`. Roles are not enforced — invent new ones
freely if a fixture has something unusual.

If a fixture lacks a role, the engine silently skips it. So you can write
one scene that targets `tag: par` with `color/white: 200`, and it works on
fixtures with a white channel and on plain RGBs (the white value just gets
ignored on the latter).

---

## 3. Deterministic principles (universal — apply to every show)

These are not stylistic preferences. They follow from how human perception
works. Violating them produces predictably bad shows.

### 3.1 Edge of chaos

Both extremes fail:

* **Too ordered** → predictable → boring → attention drops
* **Too chaotic** → unpredictable → unparseable → brain disengages

The interesting zone is **structured complexity**, where patterns are
recognisable but never fully stable. Practical: a chase can repeat its
4-beat structure for 16 bars, but it should *evolve subtly within those
bars* (slight phase shift, slight color drift, one new accent).

### 3.2 Surprise is information

Rare events carry more information than frequent ones. Therefore:

* If strobe runs 50% of the time, strobe means nothing.
* If full-rig white-hits happen every drop, they don't feel like drops.
* If the rig blacks out twice during a 30-minute set, those blackouts
  carry weight.

**Rule of thumb: the strongest effects must be the rarest.** Reserve them.

### 3.3 Redundancy ≠ noise

Pure randomness is not interesting — it is just noise. Shows need:

* **Motifs** — recognisable mini-patterns that recur
* **Variations** — slight mutations of those motifs
* **Themes** — palette + motion logic that defines a section

Like music: same theme, different harmonisation; same chase, different
tempo or color; same gesture, different fixture group.

### 3.4 Contrast > absolute value

The brain measures *change*, not state. So:

* dim → bright moves attention
* still → moving moves attention
* slow → fast moves attention
* mono → polychrome moves attention

A scene at constant brightness 200 is invisible after 5 seconds. Same
scene fading from 50 to 200 is gripping. **Always think in gradients.**

### 3.5 Compressibility

A great show is *describable in a few words*: "deep blue, slow pulse,
single beam roving". A bad show requires a frame-by-frame description.

Audiences pick up on this within ~20 seconds. Once they sense the show
has "a logic", every subsequent variation lands harder. Once they sense
it doesn't, they stop trying.

**Practical: every section should have one sentence describing it.** If
you cannot write that sentence, the section is incoherent.

### 3.6 Fractal time scales

A show operates on three time scales simultaneously:

| Scale | Duration | Mechanism |
| --- | --- | --- |
| Micro | ms – seconds | beat-locked chases, strobes, fades |
| Meso | seconds – minute | sections, bridges, transitions between motifs |
| Macro | minute – set | entropy curve, dramaturgy, color story |

A common failure: get micro right, ignore meso and macro, end up with a
set that is "lots of cool moments, but no journey".

### 3.7 Symmetry is read instantly

Bilateral / radial symmetry registers in milliseconds. Therefore:

* Symmetric scenes → grounded, monumental, calm
* Asymmetric scenes → alive, unstable, energetic
* Slight symmetry-break → most interesting

**Default to ~80% symmetry, ~20% controlled deviation.** Pure symmetry
becomes static; pure asymmetry becomes stress.

### 3.8 Entropy hysteresis (recovery)

After a high-entropy peak, the audience needs **a reset window**, or the
next peak feels weaker. Reset = blackout, single beam, slow atmosphere,
stillness — anything that recalibrates the perceptual baseline.

**Rule of thumb: every drop wants 5–15 seconds of silence-shape after.**
Don't fill it.

### 3.9 Deterministic chaos > random

Apparent complexity from simple rules beats true randomness for two
reasons:

1. It looks intentional.
2. It is reproducible.

Mechanisms:

* Phase-shifted copies of one chase across fixtures
* Modulating one parameter sinusoidally while others stay locked
* Off-grid timing (e.g. step every 3 beats inside a 4-beat cycle)
* Rule-based color rotation (e.g. complementary swap every 8 bars)

Avoid `random` as a primitive. Use deterministic-but-interesting structure.

### 3.10 Coherence rules everything

All local variation must read as part of the same global logic. The
moment the audience perceives "two different shows stitched together",
the spell breaks.

Coherence anchors:

* Palette (no more than 3–5 colors per section)
* Motion vocabulary (if you sweep, sweep consistently — don't mix
  "hard square chase" with "smooth sine sweep" without a transition)
* Tempo grid (if everything is on the beat, stay there; deviating *once*
  is a feature, deviating constantly is incoherence)
* Energy aesthetic (a section is "calm" or "driving" — don't ride both)

When in doubt: **fewer choices, repeated more.**

---

## 4. Inter-fixture relationships

The single fixture is not the unit. The **set of fixtures over time** is.
The audience reads relationships, not individual lights. The same
deterministic principles now apply to *correlations between lights*.

### 4.1 Correlation vs. decorrelation

| Setting | Effect | Use |
| --- | --- | --- |
| All fixtures fully synced | Monumental, machine-precise, can become static fast | Drops, builds, monumental moments |
| All fixtures independent | Chaotic, "noisy", unreadable | Avoid as default |
| Slight phase offset / parameter variation | Organic, alive, large | **Default for most chases** |

The middle option is right ~70% of the time.

### 4.2 Phase shift as a multiplier

Tiny delays between fixtures running the same pattern produce huge
perceived motion:

```
all sync             →  one blob pulsing
~50ms phase shift    →  wave across the rig (organic, ~25 BPM
                          equivalent of perceived flow)
~250ms phase shift   →  classic chase (mechanical)
~1s phase shift      →  separate gestures, no longer one motion
```

**Author rule:** start identical chases on multiple groups with explicit
phase offsets, not by hoping for randomness.

In our YAML this is done by writing two chase steps with different
`at_beat` values for `mh-left` vs `mh-right`. See cookbook §9.3.

### 4.3 Hierarchy

Not every fixture should carry equal weight. Music has lead, rhythm,
atmosphere — light should too. Designate:

* **Lead** (1–2 fixtures or a tight group): carries the highlights, hits,
  punctuation. Often centred or moving.
* **Rhythm** (medium group): pulses with the beat, less varied.
* **Atmosphere** (large diffuse group): washes, slow drift, sets the mood.
* **Accents** (1–3 fixtures): rare, special, specific moments.

Tag your fixtures accordingly: `lead`, `rhythm`, `atmosphere`, `accent`.
Then author scenes that respect this hierarchy.

### 4.4 Movement relations

Relative motion is much stronger than absolute motion:

* Convergence / divergence (centre vs edges moving in opposite directions)
* Mirroring (left moves left, right moves right — symmetric)
* Counter-mirroring (left moves left, right moves left too — directional)
* Rotation around a centre
* Expansion / collapse from a focal point

These are **emergent properties** of the rig — the audience sees the
*pattern*, not individual moves.

### 4.5 Color combination logic

A color alone means little. Color *contrast* is what registers:

* **Same-hue group** → unity, mass
* **Complementary** → tension, depth
* **Analogous** → smooth, flowing
* **Warm vs. cold** → spatial depth (warm forward, cold back)

Treat colors as **roles**, not paint:

| Role | Typical hue | Purpose |
| --- | --- | --- |
| Focus | white, neutral | "look here" |
| Frame | deep blue, magenta | spatial container |
| Energy | red, white, orange | peak intensity |
| Warmth | amber, gold | atmosphere, rest |
| Foreign | UV, deep red, lime | unusual moments |

**Rule of thumb: a section uses 2–4 colors at most.** Five+ colors and
the eye gives up trying to read meaning.

### 4.6 Group symmetry as a tool

Bilateral symmetry across the stage is the strongest perceptual hook. Use
it as a *baseline* and break it deliberately:

```
All-sync symmetric (4 bars)
  → mirrored asymmetric (2 bars)
    → broken asymmetric (1 bar at the peak)
      → blackout
        → return to symmetric
```

This pattern works *every time* because it tracks an entropy curve.

### 4.7 Frequency separation

Different elements should run at different temporal frequencies:

* **Slow background**: changes every 8–16 bars
* **Mid foreground**: changes every 1–4 bars
* **Fast accents**: change on the beat or sub-beat

When everything runs at one frequency, the show feels flat. When the
frequencies are clearly stratified, the show feels deep — exactly like
bass / mid / treble in music.

### 4.8 Energy flow

Lighting moves should have a *direction*:

* up / down
* inside / outside
* away from / towards the audience
* left / right

Random direction = noise. **Pick a direction per section, hold it.** It
makes the audience feel a logic without being able to articulate it.

### 4.9 Sparse complexity

Complex action in *one zone* with rest elsewhere reads as intentional
detail. Complex action *everywhere* reads as nothing.

Practical: when running a high-energy chase, *kill or simplify* the rest
of the rig at the same time. Then the eye locks onto the active zone.

### 4.10 Emergence

The strongest moments come from collective patterns the audience can't
attribute to a single fixture: waves, swarms, expanding volumes,
rotating spaces. Aim for this on peak moments — it makes the rig look
*much bigger than it is*.

In our YAML this means: a single chase that targets **all fixtures with
the same logic but with phase offsets per-fixture** (e.g. by
running parallel chases on `tag: left` and `tag: right` with `at_beat`
values offset by 0.5).

---

## 5. Genre playbook

Default templates per genre. **Apply them, but don't be a slave to them.**
The user's track choice trumps the genre label.

### 5.1 Techno (≈ 125–138 BPM)

The audience is in a trance. Hypnosis is the goal. Light is *part of the
trance*, not a competing show.

| Property | Setting |
| --- | --- |
| Entropy | Low to mid; very slow drift across whole tracks |
| Palette | Mono / desaturated. White, deep blue, UV, single accent. |
| Motion | Slow, often with phase shift across fixtures. Avoid hectic chases. |
| Sync | Precise on-beat. **Critical.** Off-beat work breaks trance. |
| Reset | Use **darkness as an active beat**. A 1-bar near-blackout is gold. |
| Peaks | Rare, often heralded by 8–16 bars of slow build, *not* by stacking effects |
| Avoid | Many fast cuts, rainbow palettes, constantly-on full-rig white |

Lead motif: **single moving-head beam** doing slow figure-eight
across the room, low intensity, white only. Pars = breathing wash, deep
blue, dim. Drop = full-rig white snap on the bass note, then back to wash.

### 5.2 Hardtekk / Tekk (≈ 150–180 BPM)

More aggressive than techno but not yet hardstyle. Faster, denser, more
white.

| Property | Setting |
| --- | --- |
| Entropy | Medium-high; rapid local changes inside a coherent macro structure |
| Palette | High-contrast. White + deep red, white + UV, hard-edged. |
| Motion | Fast chases, asymmetric possible, beam sweeps. |
| Sync | Big synced hits on bar lines. Quarter-beat strobes during builds. |
| Reset | **Short blackouts** every 16–32 bars, even mid-track |
| Peaks | Full-rig sync hits, brief high-rate strobing |
| Avoid | Constant max — 30 seconds of "everything blasting" makes the next 30 seconds also feel like nothing |

Lead motif: **hard 4-on-the-floor on pars + alternating MH sweep at half
speed**. Builds add quarter-beat strobing. Drops snap to white-hit + 2s
freeze + chaotic sweep.

### 5.3 Hardcore / Rawstyle / Hardstyle (≈ 150–200 BPM)

Maximally kinetic. Drops are the show. Everything else is preparation.

| Property | Setting |
| --- | --- |
| Entropy | **Low pre-drop, very high at drop.** This contrast IS the show. |
| Palette | White-hits + saturated peak colors (orange, red, magenta, lime) |
| Motion | Big sweeps, beam fans, lasers if available, fast rotations |
| Sync | Full-rig drops; hits perfectly on the kick |
| Reset | **Reduced "compression" zones** in the 8–16 bars before a drop. Less light, less color, less motion. |
| Peaks | Full rig + strobe + lasers + everything, for 2–8 bars |
| Avoid | Exploding too early, ignoring the build, no payoff zone |

Lead motif: **build = single MH centre + dim red wash, rising in BPM-
locked pulse intensity**. Drop = white snap + full-rig strobe at quarter
beats + rotating beams. Then hold a single warm color for 4 bars before
the next phrase.

### 5.4 Rap / Trap (≈ 70–95 BPM, often half-time feel)

The performer is the show. Light supports them.

| Property | Setting |
| --- | --- |
| Entropy | Generally low; specific peaks |
| Palette | Deep red, deep amber, white. Avoid playful colors. |
| Motion | Mostly still. Slow pans/tilts at most. |
| Sync | **Punchlines, hooks, bass-hits** — not every beat |
| Reset | **Dark space is the default.** The performer is the focus. |
| Peaks | Big white hits on bass-drops, deep-red wash for hooks |
| Avoid | Hectic chases competing with the vocal, rainbow lighting, busy backgrounds |

Lead motif: **deep red back-wash + single white spot on artist**. Hook =
add second wash in deep blue. Punchline = full-rig white snap, 200ms,
back to red wash. Bass-drop = full-rig red snap, 1 bar, back.

### 5.5 Drum & Bass / Liquid (≈ 165–180 BPM)

Fast but groovy. Looks fast, feels smooth.

| Property | Setting |
| --- | --- |
| Entropy | Mid-high; busy but coherent |
| Palette | Saturated but cool. Magenta, cyan, deep blue. |
| Motion | Continuous, flowing, often with strong phase shifts |
| Sync | On every snare hit (i.e. every 2 beats) plus on the bass drops |
| Reset | Less needed than in hardcore; the genre breathes naturally |
| Peaks | Beam fans on bass drops, rapid color swap on snares |

Lead motif: **continuous wave across the rig** at the snare rate, color
slowly drifting through cyan → magenta → cyan over 16 bars. Bass drop =
full-rig white-hit + freeze.

### 5.6 Ambient / Downtempo (≈ 60–90 BPM, often beatless sections)

Time-anchored, not BPM-anchored. Use `length_seconds` chases.

| Property | Setting |
| --- | --- |
| Entropy | Very low; long evolutions |
| Palette | Deep, often single dominant hue with slow drift |
| Motion | Almost none. Slow MH drifts at most. |
| Sync | Not beat-locked. Time-anchored. |
| Peaks | Rare; often a slow swell to bright, then back |
| Avoid | Beat sync (often there is no beat), strobes, anything fast |

Lead motif: **slow color walk on pars over 30–60 seconds**. MHs parked,
dim, very slow tilt drift. No strobing. No fast moves.

### 5.7 Universal genre rules

Across genres:

* **Repetitive music → micro-variation is essential**. Same palette, same
  chase, but evolve one parameter slowly (color, intensity, phase).
* **Transient-rich/aggressive music → high entropy peaks + strong contrast.**
  But always frame them with low-entropy zones.
* **Light should not "show the music"**. It should *complement* the
  music's rhythm, space, dramaturgy, energy. The two together form the
  audience experience.

---

## 6. Workflow for authoring a new show

Follow this every time. **Skipping the inspect step is the #1 reason
LLM-authored shows fail.**

### Step 1: Inspect the rig (5 minutes)

```python
# in this order
list_environments()
list_show()                      # the loaded environment
list_yaml(prefix="environments/<env>")   # find existing scenes/chases
read_yaml("environments/<env>/environment.yaml")   # full fixture list
# read 1–3 existing scenes/chases as reference
```

Note for yourself:

* What groups exist (tags)?
* What roles do the fixtures support (read 1–2 profiles)?
* What's already authored — *don't reinvent existing scenes*; build on them.

### Step 2: Plan the entropy curve (before writing anything)

For a single track or set, sketch (in your head or in a comment):

```
0:00 - 0:30  | low entropy, single color, very slow
0:30 - 1:30  | rising — add second color, slight motion
1:30 - 2:00  | build — quarter-beat pulses, white added, strobing toward end
2:00 - 2:30  | DROP — full rig + lasers + strobes
2:30 - 2:45  | reset — single beam, near-blackout
2:45 - end   | reprise of opening section, slightly varied
```

This **macro plan determines everything else**. Without it, you write
disconnected scenes.

### Step 3: Choose the palette (3–5 colors, period)

Write it down. Reference it in every scene. If a scene needs a sixth
color, *change the palette for that section explicitly* — don't sneak it
in.

### Step 4: Author scenes (motifs)

A *scene* is a snapshot — what every fixture should be doing at a moment.
Scenes are the vocabulary of your show.

Author 4–10 scenes per section:

* `<section>_idle` — the baseline of the section
* `<section>_lift` — slight intensification
* `<section>_peak` — the high-energy version
* `<section>_reset` — near-blackout / single accent

Naming: lower_snake_case, descriptive, no abbreviations the user can't
read. `techno_a_idle`, `techno_a_strobe_white`, `rap_hook_red_wash`.

### Step 5: Author chases (phrases)

A *chase* is a timed sequence of scene/value transitions. Use
**beat-anchored** chases for music-locked work, **time-anchored** for
ambient.

Patterns:

* **Pulse**: `at_beat: 0` snap to bright, `at_beat: 0` transition to dim
  over 0.4s. Repeat at `at_beat: 1, 2, 3` etc.
* **Sweep**: `at_beat: 0` transition group to scene A over 1–2s,
  `at_beat: half-length` transition to scene B. Loop.
* **Build**: a chain of chases triggered in sequence, each higher-energy
  than the last.

See cookbook §9.

### Step 6: Author banks

Banks are the user's launchpad layout. Slots 1–9 (the GUI grid). Group
them by section: e.g. slot 1–3 for the "warm" section, 4–6 for the
"build", 7–8 for the "peak", 9 = blackout (always).

### Step 7: Author the genre preset (if applicable)

```yaml
genres:
  - name: techno_set_a
    description: 128 BPM techno, blue palette, hypnotic
    bpm: 128
    lead_chase: techno_a_pulse
    recommended_chases: [techno_a_pulse, techno_a_sweep]
    recommended_scenes: [techno_a_idle, techno_a_peak]
```

### Step 8: Reload, validate, fix

```python
reload()
# read the returned errors
# if errors → fix YAML → reload again
```

**Read the errors.** They are *complete and specific*. The error
"`/.../scenes/foo.yaml: validation errors: targets.0.values.color/red:
must be 0..255 (got 300)`" means exactly what it says. Fix it.

### Step 9: Live-test

Trigger your scenes and chases live and watch the universe visualiser:

```python
snap_scene("techno_a_idle")
# observe: did the right channels light up?
start_chase("techno_a_pulse")
# observe for 8–16 bars
blackout()
release_blackout()
```

If the user is on-stage with hardware, ask them to confirm visually. The
visualiser canvas in the GUI is your eyes when they aren't.

### Step 10: Iterate

Trust the principles in §1–4. If the test reveals "too busy", reduce
information density (remove a color, slow a fade, stop a chase). If
"too flat", add contrast (a phase offset, a color hit on the bar line, a
white snap on the drop).

---

## 7. Quality checklist (run before declaring done)

Pretend you are the user reading the YAML in the morning. For every
authored show:

- [ ] Does each section have a one-sentence description? (compressibility)
- [ ] Does the palette contain ≤ 5 colors per section? (coherence)
- [ ] Is there at least one entropy peak and at least one rest zone? (curve)
- [ ] Are phase offsets used in at least one chase? (phase rule)
- [ ] Is at least one chase using `tag: <group>` for portability, not `name:`?
- [ ] Have you reserved one strong effect (full-rig white-hit, blackout)
      for at most one or two moments? (rarity)
- [ ] Does the lead group differ from the atmosphere group? (hierarchy)
- [ ] Are there motifs that recur with variation, not all-new content? (redundancy)
- [ ] If genre = techno: is sync precise? Are darkness windows used?
- [ ] If genre = hardcore: does the build occupy 8+ bars before the drop?
- [ ] If genre = rap: does the light leave space for the performer?
- [ ] Have you `reload`ed and read all errors and warnings?
- [ ] Have you live-tested at least the lead chase?

If any of these is "no", the show is not done.

---

## 8. Anti-patterns (what makes shows bad)

These are the failure modes of LLM-written shows. Watch yourself.

### 8.1 The Christmas tree

Every fixture on, every color on, every motion on. Maximum information →
zero information. Audience sees a blob.

**Fix**: pick a hierarchy. Lead group bright + colored, atmosphere dim +
mono, accents off most of the time.

### 8.2 The flat ride

A 30-minute set with one entropy level. Maybe the entropy is "high" or
"low" but the *gradient* is zero. Audience tunes out within 90 seconds.

**Fix**: enforce sections. A section is 30 seconds to 4 minutes of one
mood; sections are separated by *contrast moments* (blackout, color
swap, tempo change).

### 8.3 The kitchen sink palette

Eight colors per chase. The eye cannot infer meaning from any one of
them.

**Fix**: 3–5 colors per section. Promote 2 to "lead" colors and 1–3 to
"support".

### 8.4 The non-sync

Scene timing chosen by gut, not by beat. Audience cannot lock visual
to musical rhythm. Everything feels "slightly off".

**Fix**: use beat-anchored chases for anything music-locked. Pick
`at_beat` values on integers, halves, or thirds. Avoid arbitrary decimals.

### 8.5 The over-strobe

Strobe across multiple chases, all the time. Strobe stops being a peak
effect and becomes background noise. The actual drop is now indistinguishable.

**Fix**: strobe at most twice per minute, *never as background*. Use
strobe to punctuate, not to fill.

### 8.6 The orphan scene

A scene exists but is referenced nowhere — not by a chase, not by a bank.
Wasted authoring.

**Fix**: every scene appears in at least one chase or bank. Otherwise
delete it.

### 8.7 The hardcoded rig

Scenes reference fixtures by `name:` exclusively. Show is unportable to
any other rig.

**Fix**: prefer `tag:` selectors. Use `name:` only when targeting a single
specific instance for a specific reason (e.g. "the centre MH does the
lead beam").

### 8.8 The rainbow chase

A chase that cycles through ROYGBIV. Looks like a kindergarten
playroom. Has no relationship to the music.

**Fix**: use 2–3 colors max in a chase. Cycle through them
*musically*, on bar lines or section boundaries.

### 8.9 The infinite build

A 4-minute build with no drop — or a drop that is just "more". The
audience's expectation must *resolve*.

**Fix**: every build has a payoff. The bigger the build, the bigger
the payoff. The bigger the payoff, the *quieter* the bars after it.

### 8.10 The locked stare

Moving heads pointed at one spot for the whole track. Defeats the
purpose of a moving head.

**Fix**: even in calm sections, give MHs slow drift (a 16-bar tilt
from 100 → 130 and back). They should be part of the breathing of the
show, not statues.

---

## 9. YAML cookbook

Concrete, copy-and-adapt patterns. **Do not invent syntax** — these are
the supported forms, validated against the schema in `core/`.

### 9.1 Calm wash scene

```yaml
name: techno_a_idle
description: |
  Section A baseline — deep blue wash, MHs parked centre, lamps off.
  Held for ~16 bars between phrases.
targets:
  - select: { tag: par }
    values: { dimmer: 80, color/red: 0, color/green: 30, color/blue: 220, color/white: 0 }
  - select: { tag: moving_head }
    values: { position/pan: 128, position/tilt: 110, dimmer: 0, shutter: 255 }
```

### 9.2 Peak hit scene

```yaml
name: techno_a_white_hit
description: Full-rig white snap. Use sparingly — once per phrase peak.
targets:
  - select: { all: true }
    values: { dimmer: 255, color/red: 255, color/green: 255, color/blue: 255, color/white: 255, shutter: 255 }
```

### 9.3 Phase-shifted chase across two MH groups

```yaml
name: mh_phase_sweep
description: |
  Left MH and right MH run the same up-down sweep, phase-offset by 0.5
  beats. Produces a perceived wave across the rig.
loop: true
length_beats: 4
steps:
  # Left side leads
  - at_beat: 0
    actions:
      - { kind: transition, group: { tag: left }, scene: mh_beam_open_blue,  fade_seconds: 0.8, easing: ease_in_out }
  - at_beat: 0.5
    actions:
      - { kind: transition, group: { tag: right }, scene: mh_beam_open_blue, fade_seconds: 0.8, easing: ease_in_out }
  # Then both reset
  - at_beat: 2
    actions:
      - { kind: transition, group: { tag: left }, scene: mh_park_dark, fade_seconds: 0.8, easing: ease_in_out }
  - at_beat: 2.5
    actions:
      - { kind: transition, group: { tag: right }, scene: mh_park_dark, fade_seconds: 0.8, easing: ease_in_out }
```

### 9.4 4-on-the-floor pulse with snap-then-fade

```yaml
name: par_kick_pulse
description: Pars snap-on on each beat, fade out by 0.4s. The standard 4OTF.
loop: true
length_beats: 4
steps:
  - at_beat: 0
    actions:
      - { kind: snap,       group: { tag: par }, scene: par_full_red }
      - { kind: transition, group: { tag: par }, scene: par_dim_red, fade_seconds: 0.4 }
  - at_beat: 1
    actions:
      - { kind: snap,       group: { tag: par }, scene: par_full_red }
      - { kind: transition, group: { tag: par }, scene: par_dim_red, fade_seconds: 0.4 }
  - at_beat: 2
    actions:
      - { kind: snap,       group: { tag: par }, scene: par_full_red }
      - { kind: transition, group: { tag: par }, scene: par_dim_red, fade_seconds: 0.4 }
  - at_beat: 3
    actions:
      - { kind: snap,       group: { tag: par }, scene: par_full_red }
      - { kind: transition, group: { tag: par }, scene: par_dim_red, fade_seconds: 0.4 }
```

The snap-fires-first-then-transition pattern works because the engine
applies the snap to the in-tick shadow snapshot, then the transition's
source-capture reads the post-snap value. (See `technical_details.md` §7.)

### 9.5 Time-anchored ambient color walk

```yaml
name: ambient_drift
description: Slow color walk over 30 seconds. Time-anchored — independent of BPM.
loop: true
length_seconds: 30
steps:
  - at_seconds: 0
    actions:
      - { kind: transition, group: { tag: par }, values: { dimmer: 140, color/red: 0,   color/green: 60,  color/blue: 200 }, fade_seconds: 8.0, easing: ease_in_out }
  - at_seconds: 8
    actions:
      - { kind: transition, group: { tag: par }, values: { dimmer: 140, color/red: 80,  color/green: 30,  color/blue: 200 }, fade_seconds: 8.0, easing: ease_in_out }
  - at_seconds: 16
    actions:
      - { kind: transition, group: { tag: par }, values: { dimmer: 140, color/red: 200, color/green: 60,  color/blue: 60  }, fade_seconds: 8.0, easing: ease_in_out }
  - at_seconds: 24
    actions:
      - { kind: transition, group: { tag: par }, values: { dimmer: 140, color/red: 60,  color/green: 200, color/blue: 100 }, fade_seconds: 6.0, easing: ease_in_out }
```

### 9.6 Build with progressive density

The right way to build energy. **Don't use one chase that gets faster** —
use a *sequence of chases*, each louder than the last, triggered by the
operator (or by hand-off in a bank slot):

```yaml
# bank
slots:
  - { id: 1, kind: chase, name: build_phase_1, label: "Build A" }   # 16 bars: pulse on snare only
  - { id: 2, kind: chase, name: build_phase_2, label: "Build B" }   # 8 bars: pulse on every beat + MH sweep
  - { id: 3, kind: chase, name: build_phase_3, label: "Build C" }   # 4 bars: quarter-beat strobe + chaos
  - { id: 4, kind: scene, name: peak_white_hit,  label: "DROP",   fade_seconds: 0.0 }
  - { id: 5, kind: scene, name: post_drop_rest,  label: "Rest",   fade_seconds: 0.5 }
```

Then the `build_phase_*` chases each have *higher entropy than the
previous*. The user fires them in sequence; the show evolves naturally.

### 9.7 The "rare blackout" pattern

```yaml
# A chase that, once during its loop, blacks out for 1 beat. Reserved
# for high-energy genres only. Use the slot fade for short cuts:
slots:
  - { id: 8, kind: blackout, label: "1-beat cut", fade_seconds: 0.0 }
```

Trigger this manually on bar boundaries. The audience will *feel* it.

### 9.8 Don't do this (anti-pattern)

```yaml
# WRONG — selectors match nothing because tags are inconsistent.
name: bad_scene
targets:
  - select: { tag: front_pars }       # tags are usually "front", not "front_pars"
    values: { dimmer: 200 }
```

Always cross-check selector tags against the actual tags in
`environment.yaml`. Use `list_show` to see them.

```yaml
# WRONG — addressing by raw DMX channel offset breaks portability.
name: bad_scene_2
targets:
  - select: { name: par-l }
    values: { raw/0: 255 }            # don't address "raw/0" — use a role like dimmer
```

Use roles, not raw offsets.

```yaml
# WRONG — eight colors in one chase.
name: rainbow_chaos
length_beats: 8
steps:
  - at_beat: 0  ; actions: [{kind: snap, group: {all: true}, values: {color/red: 255}}]
  - at_beat: 1  ; actions: [{kind: snap, group: {all: true}, values: {color/green: 255}}]
  - at_beat: 2  ; actions: [{kind: snap, group: {all: true}, values: {color/blue: 255}}]
  - at_beat: 3  ; actions: [{kind: snap, group: {all: true}, values: {color/red: 255, color/green: 255}}]
  # ... etc
```

**Don't.** Pick 2–3 colors and rotate them on bar boundaries, not every beat.

---

## 10. Closing meta-rule

When in doubt, **author less, repeat more, vary subtly.**

The single biggest mistake an LLM authoring a show can make is treating
each scene as an opportunity to add *more*. Strong shows are not the sum
of strong scenes — they are the *unfolding* of a small number of
recognisable elements over time, each variation answered by a return to
the baseline.

If you find yourself adding a fifth color, a third strobe pattern, a new
fixture group: **stop, delete, simplify.** The audience cannot
consciously thank you for restraint, but they will absolutely notice its
absence.

Light is not what you put on the rig. Light is what the audience *feels*
in their attention — and attention is finite.

---

## 11. When the user asks you to author

1. **Read this document fully** if it's not already in your context.
2. **`list_show`** before anything else. Know the rig.
3. **Sketch the macro entropy curve** in 5–8 lines of plain prose.
4. **Pick a palette** (write it down).
5. **Author scenes → chases → banks → genre preset**, in that order.
6. **Reload + validate + live-test**.
7. **Iterate** against §7's checklist.
8. **When you hand back to the user**, give them a one-paragraph
   description of what you built, the names of the lead chases, and
   suggested fire sequences. Don't make them archaeology your YAML.

---

*This document is itself a YAML-like artefact: edit it freely as you learn
what works on this user's rigs. The principles are universal; the
specific genre BPMs and palettes are starting points, not laws.*
