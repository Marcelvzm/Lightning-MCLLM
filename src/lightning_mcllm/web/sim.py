"""Visual simulation state — interprets the live DMX shadow buffer
through each fixture's profile to produce a small JSON state per
fixture (kind, color, intensity, pan/tilt) that the GUI canvas can
render.

Pure function over (stage, shadow). No engine state mutation.
"""

from __future__ import annotations

from typing import Any

from lightning_mcllm.core.library import Stage


# Eurolite TMH Bar S120 colour wheel (channel 5) — reproduced from the
# manual range table in eurolite_tmh_bar_s120_head.yaml. Each entry is
# (max_value_inclusive, (r, g, b)). First match wins.
_BAR_WHEEL = [
    (9,  (255, 255, 255)),  # white
    (19, (255, 0,   0)),    # red
    (29, (0,   210, 0)),    # green
    (39, (40,  60,  255)),  # blue
    (49, (255, 230, 0)),    # yellow
    (59, (140, 220, 255)),  # light blue
    (63, (255, 140, 0)),    # orange (wider band → reaches up to 64-ish)
    (69, (255, 140, 0)),    # orange (continued)
    (79, (200, 50,  220)),  # purple
    (89, (220, 100, 100)),  # purple+orange split
    (99, (220, 180, 100)),  # orange+lightblue split
    (109,(180, 220, 200)),  # lightblue+yellow split
    (119,(220, 230, 60)),   # yellow+blue split
    (255,(255, 255, 255)),  # rotation modes — fall-through to white
]


def _wheel_to_rgb(value: int) -> tuple[int, int, int]:
    for cap, rgb in _BAR_WHEEL:
        if value <= cap:
            return rgb
    return (255, 255, 255)


# Involight RX350 — 12 macro modes selectable via the single effect/macro
# channel. Mode value ranges & meanings come straight from the profile
# YAML. The colours below are illustrative, not photometrically exact;
# the goal is "user can tell the 12 modes apart at a glance".
_RX350_MACRO = [
    (0,   (0, 0, 0)),          # off — black
    (22,  (255, 0,   0)),      # 1: red
    (45,  (0,   220, 0)),      # 2: green
    (68,  (40,  60,  255)),    # 3: blue
    (91,  (255, 230, 0)),      # 4: yellow
    (114, (255, 255, 255)),    # 5: white
    (137, (255, 245, 180)),    # 6: yellow + white
    (160, (255, 160, 0)),      # 7: red + green (orange mix)
    (183, (220, 0,   220)),    # 8: red + blue (magenta)
    (206, (0,   220, 220)),    # 9: green + blue (cyan)
    (229, (255, 120, 200)),    # 10: rgb together — pinkish shimmer
    (252, (220, 220, 255)),    # 11: all on — neutral white-ish multi
    (255, (255, 100, 255)),    # 12: music — strobing magenta hint
]


def _rx350_macro_to_rgb(value: int) -> tuple[int, int, int]:
    for cap, rgb in _RX350_MACRO:
        if value <= cap:
            return rgb
    return (200, 200, 220)


def _classify(roles: set[str]) -> str:
    """Return a render-kind hint based on which channel roles exist."""
    has_pan = "position/pan" in roles
    has_tilt = "position/tilt" in roles
    has_rgb = {"color/red", "color/green", "color/blue"}.issubset(roles)
    has_wheel = "color/wheel" in roles
    if has_pan and has_tilt:
        return "moving_head"
    if has_rgb:
        return "rgb_par"
    if has_wheel:
        return "wheel_par"
    if "effect/macro" in roles:
        return "effect_bar"
    return "generic"


def compute_sim_state(stage: Stage, shadow: bytes) -> dict[str, Any]:
    """Walk every fixture, read its current DMX values, return a
    simplified visual state list."""
    if stage is None:
        return {"fixtures": []}

    out: list[dict[str, Any]] = []
    for fx in stage.fixtures:
        profile = stage.library.get(fx.profile)
        if profile is None:
            continue
        roles = {ch.role: ch for ch in profile.channels}
        # Read current value per role from the shadow buffer.
        # address is 1-based, shadow is 0-based.
        base = fx.address - 1
        vals: dict[str, int] = {}
        for role, ch in roles.items():
            idx = base + ch.offset
            if 0 <= idx < len(shadow):
                vals[role] = shadow[idx]

        kind = _classify(set(roles.keys()))

        # Color resolution
        prof_lower = (profile.name or "").lower()
        if "color/red" in vals:
            r = vals.get("color/red", 0)
            g = vals.get("color/green", 0)
            b = vals.get("color/blue", 0)
            color = (r, g, b)
        elif "color/wheel" in vals:
            color = _wheel_to_rgb(vals["color/wheel"])
        elif "rx350" in prof_lower and "effect/macro" in vals:
            # Macro-driven LED bar — 12 modes mapped to distinguishable hues.
            color = _rx350_macro_to_rgb(vals["effect/macro"])
        else:
            # No explicit color channel — show a neutral fixed hue.
            color = (200, 200, 220)

        # Intensity from dimmer (linear). For fixtures without a dimmer,
        # use any explicit color or wheel as proxy: full if wheel != 0
        # or any RGB > 0, else 0.
        if "dimmer" in vals:
            intensity = vals["dimmer"] / 255.0
        else:
            intensity = 1.0 if max(color) > 0 else 0.0

        # Macro-blackout heuristic: cameo macro 0 = blackout, all else = pass.
        # Other profiles' macros are diverse enough that we won't try to
        # interpret them — just expose the raw value.
        macro = vals.get("effect/macro")
        if (
            kind == "rgb_par"
            and macro is not None
            and "cameo" in (profile.name or "").lower()
            and macro == 0
        ):
            intensity = 0.0

        # Strobe (0 = open / steady, >0 = strobe with rate)
        strobe = vals.get("strobe", 0) / 255.0

        # Pan/tilt — coarse 8-bit only (16-bit fine ignored for the sim)
        pan = vals.get("position/pan")
        tilt = vals.get("position/tilt")
        gobo = vals.get("gobo/wheel")

        out.append({
            "name": fx.name,
            "profile": fx.profile,
            "kind": kind,
            "tags": list(fx.tags),
            "address": fx.address,
            "color": list(color),
            "intensity": round(intensity, 3),
            "strobe": round(strobe, 3),
            "pan": pan,
            "tilt": tilt,
            "gobo": gobo,
            "raw_macro": macro,
        })

    return {"fixtures": out}
