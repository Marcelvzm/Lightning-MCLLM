"""Fixture selectors.

Scenes and chase actions target fixtures via selectors rather than hard-coded
names. This makes scenes portable across environments — as long as the target
environment has fixtures with the right tags, the scene works.

Selector forms (matched in this order — first non-None field wins):

    { name: "MH-Left" }          # exact instance name
    { tag: "moving_heads" }      # any fixture having this tag
    { tags: [a, b] }             # AND — must have all of these tags
    { any_tag: [a, b] }          # OR — must have at least one of these tags
    { all: true }                # every fixture in the environment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from lightning_mcllm.core.fixtures import FixtureInstance


class Selector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    tag: str | None = None
    tags: list[str] | None = None
    any_tag: list[str] | None = None
    all: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> "Selector":
        chosen = sum(
            1 for x in (self.name, self.tag, self.tags, self.any_tag, self.all or None) if x is not None
        )
        if chosen != 1:
            raise ValueError(
                "selector must specify exactly one of: name, tag, tags, any_tag, all"
            )
        if self.tags is not None and not self.tags:
            raise ValueError("`tags` selector cannot be empty")
        if self.any_tag is not None and not self.any_tag:
            raise ValueError("`any_tag` selector cannot be empty")
        return self

    def matches(self, fixture: "FixtureInstance") -> bool:
        if self.all:
            return True
        if self.name is not None:
            return fixture.name == self.name
        if self.tag is not None:
            return self.tag.lower() in fixture.tags
        if self.tags is not None:
            need = {t.lower() for t in self.tags}
            return need.issubset(set(fixture.tags))
        if self.any_tag is not None:
            opts = {t.lower() for t in self.any_tag}
            return bool(opts & set(fixture.tags))
        return False

    def describe(self) -> str:
        if self.all:
            return "all"
        if self.name:
            return f"name={self.name}"
        if self.tag:
            return f"tag={self.tag}"
        if self.tags:
            return "tags=" + "+".join(self.tags)
        if self.any_tag:
            return "any_tag=" + "|".join(self.any_tag)
        return "<empty>"


def resolve(
    selector: Selector, fixtures: list["FixtureInstance"]
) -> list["FixtureInstance"]:
    """Return fixtures matching the selector. Stable order (preserves input order)."""
    return [f for f in fixtures if selector.matches(f)]
