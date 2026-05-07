"""Loaders + the runtime `Stage` aggregate.

`FixtureLibrary` indexes the global fixture profiles. `Stage` joins one
environment's manifest with its scenes/chases/banks/shows, validates
cross-references, and exposes lookups the engine needs (resolve scene,
fixture by name, etc.).

Validation strategy: collect *all* errors during load instead of failing on the
first. The engine should never silently accept a broken stage, but the user/LLM
needs the full list to fix the YAML quickly.

Naming: `Stage` is what's loaded into the engine at runtime — the union of
environment manifest + scenes + chases + banks + shows. `Show` (separate
module `core.shows`) is one *scripted choreography* that runs ON the stage.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from lightning_mcllm.core.banks import Bank
from lightning_mcllm.core.chases import Chase, ReleaseAction, SnapAction, TransitionAction
from lightning_mcllm.core.environments import EnvironmentManifest
from lightning_mcllm.core.fixtures import FixtureInstance, FixtureProfile
from lightning_mcllm.core.parameters import resolve_args, resolve_placeholder
from lightning_mcllm.core.scenes import RenderedScene, Scene
from lightning_mcllm.core.selectors import Selector, resolve as selector_resolve
from lightning_mcllm.yaml_io import load_data

log = logging.getLogger(__name__)


def _coerce_channel_value(value: object, context: str, role: str) -> int:
    """Validate that a resolved scene/chase value is an int in 0..255.

    Used after parameter substitution. If the placeholder resolved to a
    non-int or out-of-range value, raise — callers catch and add to the
    engine error log so the show keeps running.
    """
    if isinstance(value, bool):
        raise ValueError(f"{context}: role {role!r} resolved to bool {value!r}, expected int 0..255")
    if isinstance(value, int):
        if not (0 <= value <= 255):
            raise ValueError(f"{context}: role {role!r} resolved to {value}, must be 0..255")
        return value
    if isinstance(value, float) and value.is_integer():
        v = int(value)
        if not (0 <= v <= 255):
            raise ValueError(f"{context}: role {role!r} resolved to {v}, must be 0..255")
        return v
    raise ValueError(f"{context}: role {role!r} resolved to {value!r}, must be int 0..255")


@dataclass
class LoadIssues:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "LoadIssues") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def _iter_yaml_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}:
            yield p


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    msgs = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msgs.append(f"  - {loc}: {err['msg']}")
    return f"{path}: validation errors:\n" + "\n".join(msgs)


# ---------------------------------------------------------------------------
# Fixture library
# ---------------------------------------------------------------------------


class FixtureLibrary:
    def __init__(self, profiles: dict[str, FixtureProfile]):
        self._profiles = profiles

    def __contains__(self, name: str) -> bool:
        return name in self._profiles

    def get(self, name: str) -> FixtureProfile | None:
        return self._profiles.get(name)

    def require(self, name: str) -> FixtureProfile:
        prof = self._profiles.get(name)
        if prof is None:
            raise KeyError(f"unknown fixture profile {name!r}")
        return prof

    def names(self) -> list[str]:
        return sorted(self._profiles.keys())

    def all(self) -> list[FixtureProfile]:
        return list(self._profiles.values())


def load_fixture_library(directory: Path) -> tuple[FixtureLibrary, LoadIssues]:
    issues = LoadIssues()
    profiles: dict[str, FixtureProfile] = {}
    for path in _iter_yaml_files(directory):
        try:
            data = load_data(path)
            if data is None:
                issues.warnings.append(f"{path}: empty file")
                continue
            prof = FixtureProfile.model_validate(data)
        except ValidationError as e:
            issues.errors.append(_format_validation_error(path, e))
            continue
        except Exception as e:  # noqa: BLE001 — parse-time errors must not crash loader
            issues.errors.append(f"{path}: failed to parse — {e}")
            continue
        if prof.name in profiles:
            issues.errors.append(f"{path}: profile name {prof.name!r} already defined")
            continue
        profiles[prof.name] = prof
    return FixtureLibrary(profiles), issues


# ---------------------------------------------------------------------------
# Stage — environment + scenes + chases + banks + shows, joined with library
# ---------------------------------------------------------------------------


@dataclass
class Stage:
    """Everything the engine needs to run one environment.

    "Stage" is the loaded runtime composite. It bundles fixture instances,
    scenes, chases, banks and shows into one object the engine ticks against.
    A `Show` (see core.shows) is one *scripted choreography* that runs on a
    stage — it lives in `Stage.shows`.
    """

    library: FixtureLibrary
    manifest: EnvironmentManifest
    fixtures: list[FixtureInstance]
    scenes: dict[str, Scene]
    chases: dict[str, Chase]
    banks: dict[str, Bank]
    env_dir: Path
    shows: dict[str, "Show"] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.manifest.name

    def fixture_by_name(self, name: str) -> FixtureInstance | None:
        for f in self.fixtures:
            if f.name == name:
                return f
        return None

    def fixtures_for(self, selector: Selector) -> list[FixtureInstance]:
        return selector_resolve(selector, self.fixtures)

    def render_scene(
        self, scene: Scene, args: dict[str, object] | None = None
    ) -> RenderedScene:
        """Resolve a scene against this stage's fixtures into (universe, addr) -> value.

        `args` overrides the scene's declared parameter defaults. Passing
        unknown args raises; missing args fall back to defaults.
        """
        resolved_args = resolve_args(scene.parameters, args)
        out: dict[tuple[int, int], int] = {}
        for target in scene.targets:
            matches = selector_resolve(target.select, self.fixtures)
            for fixture in matches:
                profile = self.library.get(fixture.profile)
                if profile is None:
                    log.warning("scene %r: fixture %r references unknown profile %r",
                                scene.name, fixture.name, fixture.profile)
                    continue
                # Inline role values (with placeholder resolution)
                for role, raw_value in target.values.items():
                    offset = profile.role_to_offset(role)
                    if offset is None:
                        continue
                    value = resolve_placeholder(raw_value, resolved_args)
                    iv = _coerce_channel_value(value, scene.name, role)
                    out[(fixture.universe, fixture.address - 1 + offset)] = iv
                # Preset values (resolved via profile.presets)
                if target.presets:
                    for role, preset_name in target.presets.items():
                        offset = profile.role_to_offset(role)
                        if offset is None:
                            continue
                        ch = next((c for c in profile.channels if c.role == role), None)
                        if ch is None or not ch.presets or preset_name not in ch.presets:
                            log.warning("scene %r: preset %r not found for role %r on profile %r",
                                        scene.name, preset_name, role, profile.name)
                            continue
                        out[(fixture.universe, fixture.address - 1 + offset)] = int(ch.presets[preset_name])
        return RenderedScene(name=scene.name, values=out)

    def render_inline_values(
        self,
        selector: Selector,
        role_values: dict[str, int | str],
        args: dict[str, object] | None = None,
    ) -> dict[tuple[int, int], int]:
        """Resolve inline (role -> value) for a selector — used by chase actions.

        `args` resolves any `${param}` placeholders. Caller (the chase runner)
        is responsible for already validating args against its own parameter
        spec.
        """
        args = args or {}
        out: dict[tuple[int, int], int] = {}
        for fixture in self.fixtures_for(selector):
            profile = self.library.get(fixture.profile)
            if profile is None:
                continue
            for role, raw_value in role_values.items():
                offset = profile.role_to_offset(role)
                if offset is None:
                    continue
                value = resolve_placeholder(raw_value, args)
                iv = _coerce_channel_value(value, "<inline>", role)
                out[(fixture.universe, fixture.address - 1 + offset)] = iv
        return out

    def channels_for(self, selector: Selector) -> set[tuple[int, int]]:
        """Every (universe, addr) channel touched by any fixture matching the selector."""
        out: set[tuple[int, int]] = set()
        for fixture in self.fixtures_for(selector):
            profile = self.library.get(fixture.profile)
            if profile is None:
                continue
            for ch in profile.channels:
                out.add((fixture.universe, fixture.address - 1 + ch.offset))
        return out


# ---------------------------------------------------------------------------
# Stage loader
# ---------------------------------------------------------------------------


def load_stage(env_dir: Path, library: FixtureLibrary) -> tuple[Stage | None, LoadIssues]:
    """Load an environment directory into a runtime Stage.

    Layout:
        env_dir/environment.yaml
        env_dir/scenes/*.yaml
        env_dir/chases/*.yaml
        env_dir/banks/*.yaml
        env_dir/shows/*.yaml         (optional)
    """
    # Late import to avoid circular dependency (core.shows imports nothing
    # from this module, but we don't want core.library importing shows at
    # module load time when bootstrapping fresh code).
    from lightning_mcllm.core.shows import Show, validate_show_against_stage

    issues = LoadIssues()

    manifest_path = env_dir / "environment.yaml"
    if not manifest_path.exists():
        issues.errors.append(f"{env_dir}: missing environment.yaml")
        return None, issues
    try:
        manifest_data = load_data(manifest_path)
        manifest = EnvironmentManifest.model_validate(manifest_data)
    except ValidationError as e:
        issues.errors.append(_format_validation_error(manifest_path, e))
        return None, issues
    except Exception as e:  # noqa: BLE001
        issues.errors.append(f"{manifest_path}: {e}")
        return None, issues

    # Validate fixtures against library
    valid_fixtures: list[FixtureInstance] = []
    occupied: dict[int, dict[int, str]] = {}  # universe -> {address -> fixture_name}
    for fx in manifest.fixtures:
        profile = library.get(fx.profile)
        if profile is None:
            issues.errors.append(
                f"{manifest_path}: fixture {fx.name!r} references unknown profile {fx.profile!r}"
            )
            continue
        end = fx.address + profile.footprint - 1
        if end > 512:
            issues.errors.append(
                f"fixture {fx.name!r}: address {fx.address} + footprint {profile.footprint} exceeds 512"
            )
            continue
        u_map = occupied.setdefault(fx.universe, {})
        for a in range(fx.address, end + 1):
            if a in u_map:
                issues.errors.append(
                    f"fixture {fx.name!r} (univ {fx.universe} addr {a}) overlaps with {u_map[a]!r}"
                )
                break
        else:
            for a in range(fx.address, end + 1):
                u_map[a] = fx.name
            valid_fixtures.append(fx)

    # Load scenes
    scenes: dict[str, Scene] = {}
    for path in _iter_yaml_files(env_dir / "scenes"):
        try:
            data = load_data(path)
            if data is None:
                continue
            scene = Scene.model_validate(data)
        except ValidationError as e:
            issues.errors.append(_format_validation_error(path, e))
            continue
        except Exception as e:  # noqa: BLE001
            issues.errors.append(f"{path}: {e}")
            continue
        if scene.name in scenes:
            issues.errors.append(f"{path}: scene {scene.name!r} already defined")
            continue
        scenes[scene.name] = scene

    # Load chases
    chases: dict[str, Chase] = {}
    for path in _iter_yaml_files(env_dir / "chases"):
        try:
            data = load_data(path)
            if data is None:
                continue
            chase = Chase.model_validate(data)
        except ValidationError as e:
            issues.errors.append(_format_validation_error(path, e))
            continue
        except Exception as e:  # noqa: BLE001
            issues.errors.append(f"{path}: {e}")
            continue
        if chase.name in chases:
            issues.errors.append(f"{path}: chase {chase.name!r} already defined")
            continue
        for i, step in enumerate(chase.steps):
            for j, action in enumerate(step.actions):
                if isinstance(action, (TransitionAction, SnapAction)):
                    if action.scene is not None and action.scene not in scenes:
                        issues.errors.append(
                            f"{path}: step {i} action {j} references unknown scene {action.scene!r}"
                        )
                if isinstance(action, ReleaseAction):
                    pass
        chases[chase.name] = chase

    # Load banks
    banks: dict[str, Bank] = {}
    for path in _iter_yaml_files(env_dir / "banks"):
        try:
            data = load_data(path)
            if data is None:
                continue
            bank = Bank.model_validate(data)
        except ValidationError as e:
            issues.errors.append(_format_validation_error(path, e))
            continue
        except Exception as e:  # noqa: BLE001
            issues.errors.append(f"{path}: {e}")
            continue
        if bank.name in banks:
            issues.errors.append(f"{path}: bank {bank.name!r} already defined")
            continue
        from lightning_mcllm.core.banks import ChaseSlot, SceneSlot
        for slot in bank.slots:
            if isinstance(slot, SceneSlot) and slot.name not in scenes:
                issues.errors.append(
                    f"{path}: bank {bank.name!r} slot {slot.id} references unknown scene {slot.name!r}"
                )
            if isinstance(slot, ChaseSlot) and slot.name not in chases:
                issues.errors.append(
                    f"{path}: bank {bank.name!r} slot {slot.id} references unknown chase {slot.name!r}"
                )
        banks[bank.name] = bank

    if manifest.default_bank is not None and manifest.default_bank not in banks:
        issues.warnings.append(
            f"environment {manifest.name!r}: default_bank {manifest.default_bank!r} not found"
        )

    # Load shows (scripted choreographies)
    shows: dict[str, Show] = {}
    shows_dir = env_dir / "shows"
    for path in _iter_yaml_files(shows_dir):
        try:
            data = load_data(path)
            if data is None:
                continue
            show = Show.model_validate(data)
        except ValidationError as e:
            issues.errors.append(_format_validation_error(path, e))
            continue
        except Exception as e:  # noqa: BLE001
            issues.errors.append(f"{path}: {e}")
            continue
        if show.name in shows:
            issues.errors.append(f"{path}: show {show.name!r} already defined")
            continue
        # Cross-reference validate against the stage we've built so far
        for warn in validate_show_against_stage(show, scenes, chases, banks):
            issues.warnings.append(f"{path}: {warn}")
        shows[show.name] = show

    if issues.errors:
        return None, issues

    stage = Stage(
        library=library,
        manifest=manifest,
        fixtures=valid_fixtures,
        scenes=scenes,
        chases=chases,
        banks=banks,
        env_dir=env_dir,
        shows=shows,
    )
    return stage, issues


# Backward-compat alias for any caller still using the old name.
load_show = load_stage


def list_environments(envs_dir: Path) -> list[str]:
    if not envs_dir.exists():
        return []
    return sorted(p.name for p in envs_dir.iterdir() if p.is_dir() and (p / "environment.yaml").exists())
