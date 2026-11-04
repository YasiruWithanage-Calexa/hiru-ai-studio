"""canon_write: candidates → canon entities and versions.

`plan.py` decides (ported from `canon_extract/engine/write.py`); this applies it through the `canon` port in the
builder's order: new entities, then new versions, then identity-only changes. A locked entity is reported, not
changed, and a person's wording is never overwritten.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.tools.canon_write.plan import plan


class Args(BaseModel):
    candidates: list[dict[str, Any]] = Field(description="Canon candidates, as the canon_rules step returns them")
    aspect_ratio: str = "16:9"


class Result(BaseModel):
    created: int
    versioned: int
    updated: int
    unchanged: int
    locked: list[str]


def run(args: Args, ctx: RunContext) -> Result:
    store = ctx.need("canon", "CanonStore")
    production_id = tooling.production_of(ctx)
    p = plan(args.candidates, store.entities(production_id), production_id=str(production_id),
             aspect_ratio=args.aspect_ratio, actor=str(ctx.actor_user_id) if ctx.actor_user_id else None)
    for entity, version in p.creates:
        store.create_entity(entity, version)
    for entity_id, version, fields in p.versions:
        store.add_version(entity_id, version, fields)
    for entity_id, fields in p.updates:
        store.update_entity(entity_id, fields)
    return Result(created=len(p.creates), versioned=len(p.versions), updated=len(p.updates), unchanged=p.unchanged,
                  locked=p.locked)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
