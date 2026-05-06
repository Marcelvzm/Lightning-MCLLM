# Genre concepts

Detailed conceptual proposals for the genres LightningMCLLM is designed to
serve. Each file describes the **aesthetic philosophy, palette, motion
vocabulary, time grid, fixture-role hierarchy, section archetypes, peak
architecture, recurring motifs, and anti-patterns** for one genre — at a
level of abstraction that maps to *any rig*.

These documents do **not** name specific fixtures. They speak in **abstract
roles**:

| Role | What it means |
| --- | --- |
| **Atmosphere layer** | Wide diffuse fixtures that define the room's mood. Usually pars or LED bars. |
| **Pulse layer** | Beat-locked fixtures, often the dominant presence in dance genres. |
| **Beam layer** | Narrow-angle architectural beams visible in fog. Often moving heads at narrow zoom. |
| **Lead group** | The 1–2 most expressive fixtures (often centre-stage moving heads). |
| **Accent layer** | Strobes, blinders, peak-only fixtures. Used rarely. |
| **Performer spot** | Front-of-house spotlight on the artist (rap-specific). |

When implementing on a real rig, map each role to whichever fixtures you
have. A 4-fixture setup collapses several roles together. A 30-fixture
setup distributes them widely. The principles do not change.

## Files

| Genre | BPM | Vibe |
| --- | --- | --- |
| [techno.md](techno.md) | 125–138 | Hypnotic, slow evolution, restraint |
| [hardtekk.md](hardtekk.md) | 150–180 | Aggressive 4OTF, structured chaos |
| [hardstyle.md](hardstyle.md) | 150–200 | Drop-driven, peak spectacle |
| [rap_trap.md](rap_trap.md) | 70–95 | Performer-centric, restraint |
| [dnb.md](dnb.md) | 165–180 | Continuous flow, beautiful drops |
| [ambient.md](ambient.md) | beatless / 60–90 | Slow atmosphere, meditative |

## How to use these

Reading order for an LLM authoring a show:

1. `read_authoring_guide` (returns `llm_instruct.md`)
2. `read_genre_concept(<genre>)` for the relevant genre — returns the
   matching file from this directory
3. `list_show` to learn the actual rig
4. Author scenes/chases/banks/genre presets that **map the abstract roles
   in this document to the user's actual fixture tags**

The genre concepts are starting points, not laws. The user's track choice
trumps the genre label, and the user's rig may suggest variations the
abstract concept doesn't anticipate. Use these as **scaffolding** — not
prescriptions.

## Cross-genre patterns

Worth noting before reading any individual file:

* **Entropy curve > absolute level**. Every genre trades order and chaos
  in different ways, but every genre needs a CURVE, not a constant.
* **Layered hierarchy**. Every genre uses an atmosphere/pulse/beam/accent
  hierarchy, just with different proportions.
* **Time grid alignment**. Every genre has its grid (or, for ambient,
  consciously rejects one). Off-grid work is always intentional.
* **Reserved peak vocabulary**. Every genre reserves one or two effects
  (full-rig white, strobe volley, total blackout) for the rare moments
  that EARN them. Burn these effects on filler and the show flattens.
* **Recurring motifs**. Every genre has 3–5 visual signatures that recur
  across a set, building the audience's visual vocabulary.

The genre-specific files describe how each principle plays out in that
particular musical context.
