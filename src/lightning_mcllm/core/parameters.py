"""Runtime parameters for scenes and chases.

A scene or chase can declare a `parameters:` block at the top of its YAML.
Each parameter has a name, a type, and a default value (plus optional
constraints). Numeric values inside the file (`values:` dicts, `at_beat`,
`fade_seconds`, etc.) can reference parameters via `${name}` placeholders.

At trigger time the caller can pass an `args` dict that overrides defaults.
The engine resolves placeholders against the merged dict before rendering.

Design notes:
  * Whole-string substitution only — `"${baseline}"` is recognised, but
    `"prefix${baseline}suffix"` is NOT. Numeric fields don't need string
    composition, and forbidding it keeps the substitution rules sharp.
  * Pydantic schemas accept `int | str` for numeric fields so YAML can
    legally hold `"${name}"` until the resolver swaps it for the real value.
  * Unknown args (passed but not declared) raise — this catches typos at
    trigger time rather than silently doing nothing.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


# Matches `$name` or `${name}` filling the entire (stripped) string.
_PLACEHOLDER_RE = re.compile(r"^\$\{?([a-zA-Z_][a-zA-Z0-9_]*)\}?$")


class ParameterSpec(BaseModel):
    """One parameter declaration. Lives in the `parameters:` block of a YAML."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["int", "float", "str", "bool"] = "int"
    default: int | float | str | bool
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _check_default_matches_type(self) -> "ParameterSpec":
        if not _value_matches_type(self.default, self.type):
            raise ValueError(
                f"parameter default {self.default!r} does not match declared type {self.type!r}"
            )
        if self.options is not None and self.type != "str":
            raise ValueError("`options` is only valid when type='str'")
        if self.options is not None and self.default not in self.options:
            raise ValueError(f"default {self.default!r} not in options {self.options!r}")
        if self.type in ("int", "float"):
            if self.min is not None and float(self.default) < self.min:
                raise ValueError(f"default {self.default} below min {self.min}")
            if self.max is not None and float(self.default) > self.max:
                raise ValueError(f"default {self.default} above max {self.max}")
        return self


def _value_matches_type(value: Any, t: str) -> bool:
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "str":
        return isinstance(value, str)
    if t == "bool":
        return isinstance(value, bool)
    return False


def _coerce(value: Any, spec: ParameterSpec) -> Any:
    """Coerce a raw value into the declared type, raise on mismatch / out-of-range."""
    t = spec.type
    if t == "int":
        if isinstance(value, bool):
            raise ValueError(f"expected int, got bool {value}")
        if isinstance(value, (int, float)) and float(value).is_integer():
            v = int(value)
        else:
            raise ValueError(f"expected int, got {value!r}")
    elif t == "float":
        if isinstance(value, bool):
            raise ValueError(f"expected float, got bool {value}")
        if isinstance(value, (int, float)):
            v = float(value)
        else:
            raise ValueError(f"expected float, got {value!r}")
    elif t == "str":
        if not isinstance(value, str):
            raise ValueError(f"expected str, got {value!r}")
        if spec.options is not None and value not in spec.options:
            raise ValueError(f"value {value!r} not in options {spec.options!r}")
        v = value
    elif t == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"expected bool, got {value!r}")
        v = value
    else:
        raise ValueError(f"unknown parameter type {t!r}")

    if t in ("int", "float"):
        if spec.min is not None and v < spec.min:
            raise ValueError(f"value {v} below min {spec.min}")
        if spec.max is not None and v > spec.max:
            raise ValueError(f"value {v} above max {spec.max}")
    return v


def resolve_args(
    spec: dict[str, ParameterSpec],
    passed: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge passed args with defaults, validating types and constraints.

    Unknown args (in `passed` but not in `spec`) raise — the caller likely
    typo'd a parameter name and we'd rather fail loud.
    """
    passed = passed or {}
    unknown = set(passed) - set(spec)
    if unknown:
        raise ValueError(f"unknown parameter(s): {sorted(unknown)}")
    out: dict[str, Any] = {}
    for name, ps in spec.items():
        raw = passed[name] if name in passed else ps.default
        try:
            out[name] = _coerce(raw, ps)
        except ValueError as e:
            raise ValueError(f"parameter {name!r}: {e}") from e
    return out


def resolve_placeholder(value: Any, args: dict[str, Any]) -> Any:
    """If `value` is a `${name}` / `$name` placeholder, swap it for `args[name]`.
    Otherwise return `value` unchanged. Raises if the placeholder names an
    unknown parameter.
    """
    if not isinstance(value, str):
        return value
    m = _PLACEHOLDER_RE.match(value.strip())
    if m is None:
        return value  # plain string, not a placeholder
    name = m.group(1)
    if name not in args:
        raise KeyError(f"placeholder ${name!r} references undeclared parameter")
    return args[name]
