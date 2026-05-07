"""Tests for the palette mechanism."""

from __future__ import annotations

import pytest

from lightning_mcllm.core.library import load_fixture_library, load_stage
from lightning_mcllm.core.palettes import Palette, PaletteList, PaletteRef, merge_values
from lightning_mcllm.core.scenes import Scene


# ---------------------------------------------------------------------------
# Palette + helper unit tests
# ---------------------------------------------------------------------------


def test_palette_validates_range() -> None:
    Palette.model_validate(
        {
            "name": "red",
            "facets": {"rgb": {"color/red": 255, "color/green": 0}},
        }
    )
    with pytest.raises(Exception, match="0..255"):
        Palette.model_validate(
            {"name": "bad", "facets": {"rgb": {"color/red": 999}}}
        )


def test_palette_facet_lookup_raises_on_unknown() -> None:
    p = Palette.model_validate(
        {"name": "red", "facets": {"rgb": {"color/red": 255}}}
    )
    assert p.facet("rgb") == {"color/red": 255}
    with pytest.raises(KeyError):
        p.facet("wheel")


def test_palette_list_parses_yaml_shape() -> None:
    pl = PaletteList.model_validate(
        {
            "palettes": [
                {"name": "red", "facets": {"rgb": {"color/red": 255}}},
                {"name": "blue", "facets": {"rgb": {"color/blue": 255}}},
            ]
        }
    )
    assert len(pl.palettes) == 2
    assert pl.palettes[0].name == "red"


def test_merge_values_explicit_overrides_palette() -> None:
    pal = {"color/red": 255, "color/green": 0}
    explicit: dict[str, int | str] = {"color/red": 200}  # explicit wins
    merged = merge_values(pal, explicit)
    assert merged["color/red"] == 200
    assert merged["color/green"] == 0


# ---------------------------------------------------------------------------
# Stage rendering with palettes
# ---------------------------------------------------------------------------


@pytest.fixture()
def stolz_stage(tmp_data_dir, settings):
    """The stolz environment, which has a palettes.yaml authored."""
    lib, _ = load_fixture_library(settings.paths.fixture_library)
    s, issues = load_stage(settings.paths.environments / "stolz", lib)
    assert s is not None, f"stolz failed to load: {issues.errors}"
    return s


def test_stolz_palettes_loaded(stolz_stage) -> None:
    assert "rot" in stolz_stage.palettes
    assert "blau" in stolz_stage.palettes
    assert "wheel" in stolz_stage.palettes["rot"].facets
    assert stolz_stage.palettes["rot"].facets["wheel"]["color/wheel"] == 14
    assert stolz_stage.palettes["blau"].facets["wheel"]["color/wheel"] == 34


def test_scene_with_palette_ref_renders_palette_values(stolz_stage) -> None:
    """A target with palette+facet writes the facet's role values."""
    sc = Scene.model_validate(
        {
            "name": "test",
            "targets": [
                {
                    "select": {"tag": "bar"},
                    "palette": {"name": "rot", "facet": "wheel"},
                    "values": {"dimmer": 255},
                }
            ],
        }
    )
    rendered = stolz_stage.render_scene(sc)
    # Bar head-1 at addr 1, color/wheel offset 5 = ch 6 = shadow index 5
    assert rendered.values[(0, 5)] == 14  # red wheel
    # Dimmer at offset 8 = ch 9 = shadow index 8
    assert rendered.values[(0, 8)] == 255


def test_explicit_values_override_palette(stolz_stage) -> None:
    """If both palette and values set the same role, values wins."""
    sc = Scene.model_validate(
        {
            "name": "override",
            "targets": [
                {
                    "select": {"tag": "bar"},
                    "palette": {"name": "rot", "facet": "wheel"},
                    "values": {"color/wheel": 99, "dimmer": 255},
                }
            ],
        }
    )
    rendered = stolz_stage.render_scene(sc)
    assert rendered.values[(0, 5)] == 99  # explicit override, not palette's 14


def test_palette_param_substitution(stolz_stage) -> None:
    """A palette name as `${param}` resolves at render time using args."""
    sc = Scene.model_validate(
        {
            "name": "param_test",
            "parameters": {
                "col": {
                    "type": "str",
                    "default": "rot",
                    "options": ["rot", "blau"],
                }
            },
            "targets": [
                {
                    "select": {"tag": "bar"},
                    "palette": {"name": "${col}", "facet": "wheel"},
                    "values": {"dimmer": 255},
                }
            ],
        }
    )
    # Default: col=rot
    rendered_default = stolz_stage.render_scene(sc)
    assert rendered_default.values[(0, 5)] == 14
    # Override: col=blau
    rendered_blau = stolz_stage.render_scene(sc, args={"col": "blau"})
    assert rendered_blau.values[(0, 5)] == 34


def test_unknown_palette_raises(stolz_stage) -> None:
    sc = Scene.model_validate(
        {
            "name": "bad",
            "targets": [
                {
                    "select": {"tag": "bar"},
                    "palette": {"name": "schokolade", "facet": "wheel"},
                }
            ],
        }
    )
    # Note: the load-time validator catches static mismatches, but since we're
    # building this scene programmatically (not loading from yaml), it bypasses
    # that check. The render-time guard still catches it.
    with pytest.raises(ValueError, match="unknown palette"):
        stolz_stage.render_scene(sc)


def test_unknown_facet_raises(stolz_stage) -> None:
    sc = Scene.model_validate(
        {
            "name": "bad_facet",
            "targets": [
                {
                    "select": {"tag": "bar"},
                    "palette": {"name": "rot", "facet": "schokolade"},
                }
            ],
        }
    )
    with pytest.raises(KeyError, match="unknown facet"):
        stolz_stage.render_scene(sc)


def test_load_stage_validates_static_palette_refs(tmp_data_dir, settings):
    """Adding a scene that references a non-existent palette is rejected at load."""
    bad_scene = tmp_data_dir / "environments" / "stolz" / "scenes" / "bad_palette.yaml"
    bad_scene.write_text(
        "name: bad_palette\n"
        "targets:\n"
        "  - select: { tag: bar }\n"
        "    palette: { name: schokolade, facet: wheel }\n"
    )
    lib, _ = load_fixture_library(settings.paths.fixture_library)
    s, issues = load_stage(settings.paths.environments / "stolz", lib)
    assert s is None
    assert any("unknown palette" in e for e in issues.errors)


def test_load_stage_skips_palette_validation_for_placeholders(tmp_data_dir, settings):
    """A scene with `${param}` palette name should NOT fail load (resolved later)."""
    deferred = tmp_data_dir / "environments" / "stolz" / "scenes" / "deferred.yaml"
    # ${...} placeholders must be quoted inside flow-mapping context.
    deferred.write_text(
        'name: deferred\n'
        'parameters:\n'
        '  col: { type: str, default: rot }\n'
        'targets:\n'
        '  - select: { tag: bar }\n'
        '    palette: { name: "${col}", facet: wheel }\n'
    )
    lib, _ = load_fixture_library(settings.paths.fixture_library)
    s, issues = load_stage(settings.paths.environments / "stolz", lib)
    assert s is not None, f"deferred placeholder should load OK: {issues.errors}"
    assert "deferred" in s.scenes


# ---------------------------------------------------------------------------
# End-to-end via the all_color scene shipping in stolz
# ---------------------------------------------------------------------------


def test_stolz_all_color_default_renders_red(stolz_stage):
    """Default args → 'rot' → bar wheel = 14."""
    sc = stolz_stage.scenes["all_color"]
    rendered = stolz_stage.render_scene(sc)
    # head-1 wheel ch is at (universe 0, shadow index 5)
    assert rendered.values[(0, 5)] == 14


def test_stolz_all_color_blau_renders_blue(stolz_stage):
    sc = stolz_stage.scenes["all_color"]
    rendered = stolz_stage.render_scene(sc, args={"col": "blau"})
    assert rendered.values[(0, 5)] == 34
    # Cameo-1 starts at addr 112, RGB = R/G/B at offsets 2/3/4 (after dim+strobe).
    # Profile order: dimmer, strobe, R, G, B, macro → offsets 0, 1, 2, 3, 4, 5
    # Address 112 → shadow index 111. R at 113, G at 114, B at 115.
    assert rendered.values[(0, 111 + 2)] == 0    # cameo R
    assert rendered.values[(0, 111 + 3)] == 0    # cameo G
    assert rendered.values[(0, 111 + 4)] == 255  # cameo B (blau)


def test_stolz_all_color_options_validated(stolz_stage):
    sc = stolz_stage.scenes["all_color"]
    with pytest.raises(ValueError, match="not in options"):
        stolz_stage.render_scene(sc, args={"col": "schokolade"})
