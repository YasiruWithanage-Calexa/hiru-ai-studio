"""canon_read: one canon item by name, nickname or code, and the look a character wears in an episode. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    name_or_code: str = Field(min_length=1, max_length=80,
                              description="A character, place or prop by name, nickname or code (C01, L03, P02)")
    episode: int | None = Field(None, ge=1, description="An episode number: also returns the look worn in it")


class Result(BaseModel):
    code: str
    kind: str
    name: str
    locked: bool
    version: int | None
    summary: str
    wardrobe_anchor: str = ""
    voice_pin: str = ""
    look: dict[str, Any] | None = None
    looks: list[str] = []
    aliases: list[str] = []
    card: dict[str, Any] = {}


def run(args: Args, ctx: RunContext) -> Result:
    canon = ctx.need("canon", "CanonStore")
    production = tooling.production_of(ctx)
    entities = canon.entities(production)
    entity = views.find_entity(entities, args.name_or_code)
    if entity is None:
        raise tooling.not_found("canon item", args.name_or_code, views.entity_names(entities),
                                example='{"name_or_code": "C02"}', where="canon_find lists them all.")
    current = entity.get("current") or {}
    own = [lk for lk in canon.looks(production) if str(lk["entity_id"]) == str(entity["id"])]
    wears = views.look_in(own, entity, args.episode) if args.episode is not None else None
    detailed = args.response_format == "detailed"
    look = None
    if wears is not None:
        look = views.look_view(wears) if detailed else {k: v for k, v in views.look_view(wears).items()
                                                        if k in ("name", "outfit", "hair")}
    return Result(
        code=str(entity["code"]), kind=str(entity["kind"]), name=str(entity["name"]),
        locked=bool(entity.get("locked")), version=current.get("version"), summary=views.card_summary(entity),
        wardrobe_anchor=str(current.get("wardrobe_anchor") or ""), voice_pin=str(current.get("voice_pin") or ""),
        look=look, looks=[f"{lk['name']} ({views.episodes_text(lk.get('ranges') or [])})" for lk in own],
        aliases=[str(a) for a in entity.get("aliases") or []] if detailed else [],
        card=dict(current.get("card") or {}) if detailed else {})


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
