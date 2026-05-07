"""Palettes — named cross-fixture colour definitions.

A palette ("red", "blue", "sunset") is a named bundle of role-keyed values,
organised into **facets** so the same palette can address fixtures with
different control models (RGB direct, indexed colour wheel, macro override
on a single channel) consistently.

```yaml
# data/environments/<env>/palettes.yaml
palettes:
  red:
    description: Sattes Bühnenrot
    facets:
      rgb:    { color/red: 255, color/green: 0, color/blue: 0 }
      wheel:  { color/wheel: 14 }
      cameo:  { color/red: 255, color/green: 0, color/blue: 0, effect/macro: 10 }
      rx350:  { effect/macro: 11 }
```

A scene references a palette + facet inside a target:

```yaml
targets:
  - select: { tag: bar }
    palette: { name: red, facet: wheel }
    values:  { dimmer: 255 }     # explicit values override palette values
```

The render path resolves the palette+facet at fire time, merges with any
explicit `values:` (explicit wins), and writes per-fixture channels.

Parameter substitution: the palette `name` field can be a `${param}`
placeholder so a single scene can be re-fired with different palettes:

```yaml
parameters:
  col: { type: str, default: red }
targets:
  - select: { tag: bar }
    palette: { name: ${col}, facet: wheel }
```

Palettes live per-environment (next to environment.yaml) because facet
naming + values are tied to the specific fixture mix in that env.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Palette(BaseModel):
    """One named palette — a bundle of facets, each a role→value dict."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)

    @field_validator("facets")
    @classmethod
    def _check_facets(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for facet_name, role_values in v.items():
            facet_clean: dict[str, int] = {}
            for role, val in role_values.items():
                if not isinstance(val, int) or isinstance(val, bool):
                    raise ValueError(
                        f"facet {facet_name!r}, role {role!r}: must be int (got {val!r})"
                    )
                if not (0 <= val <= 255):
                    raise ValueError(
                        f"facet {facet_name!r}, role {role!r}: value {val} not in 0..255"
                    )
                facet_clean[role.strip().lower()] = val
            out[facet_name] = facet_clean
        return out

    def facet(self, name: str) -> dict[str, int]:
        """Return the named facet's values, or raise KeyError if absent."""
        if name not in self.facets:
            raise KeyError(
                f"palette {self.name!r}: unknown facet {name!r}; have {sorted(self.facets)}"
            )
        return self.facets[name]


class PaletteList(BaseModel):
    """Top-level structure of `palettes.yaml`."""

    model_config = ConfigDict(extra="forbid")

    palettes: list[Palette] = Field(default_factory=list)


class PaletteRef(BaseModel):
    """Reference to a palette+facet inside a SceneTarget or chase action.

    `name` may be a literal palette name (`"red"`) or a placeholder
    (`"${col}"`) that resolves at render time against the scene/chase args.
    `facet` is always a literal — it depends on the fixture type, which is
    fixed for a given target.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    facet: str = Field(min_length=1)


def merge_values(
    palette_values: dict[str, int],
    explicit_values: dict[str, int | str],
) -> dict[str, int | str]:
    """Combine palette-provided values with explicit per-target values.

    Explicit values WIN on conflicts — palettes are a baseline you can
    override. Used when rendering a SceneTarget with a palette ref plus
    its own `values:` block.
    """
    out: dict[str, int | str] = dict(palette_values)
    out.update(explicit_values)
    return out
