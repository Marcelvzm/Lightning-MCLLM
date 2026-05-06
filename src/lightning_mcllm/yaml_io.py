"""Comment-preserving YAML I/O.

Uses ruamel.yaml so when the LLM rewrites a file, hand-written comments survive.
Round-trip mode is the default. For one-shot loads where you don't need to
preserve comments, call `load_data` which returns plain dicts/lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _yaml_rt() -> YAML:
    y = YAML(typ="rt")
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    y.width = 4096
    return y


def _yaml_safe() -> YAML:
    y = YAML(typ="safe")
    return y


def load_data(path: Path) -> Any:
    """Plain load — returns dicts/lists/scalars. Use for read-only ingestion."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return _yaml_safe().load(f)


def load_rt(path: Path) -> Any:
    """Round-trip load — preserves comments. Use before editing a file."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return _yaml_rt().load(f)


def dump_rt(data: Any, path: Path) -> None:
    """Round-trip dump — preserves comments if `data` was loaded with `load_rt`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        _yaml_rt().dump(data, f)
    tmp.replace(path)


def dump_data(data: Any, path: Path) -> None:
    """Plain dump — for new files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        _yaml_rt().dump(data, f)
    tmp.replace(path)
