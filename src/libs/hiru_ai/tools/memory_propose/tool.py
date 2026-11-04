"""memory_propose: a rule staged as a card; accepted, it becomes a `memory_items` row. Nothing is remembered by this
call."""
from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused

MAX_RULE = 300  # one rule is a sentence or two; `memory_items.text` holds 2,000


class Args(BaseModel):
    rule: str = Field(min_length=5, max_length=MAX_RULE, description="The rule, as one or two plain sentences")
    scope: Literal["scene", "production"] = Field(
        description='"scene" holds for this scene only, "production" everywhere')


class Result(BaseModel):
    staged: bool
    card: str
    rule: str
    scope: str
    next: str


def run(args: Args, ctx: RunContext) -> Result:
    staging = ctx.need("staging", "Staging")
    tooling.production_of(ctx)
    rule = " ".join(args.rule.split())
    if args.scope == "scene" and ctx.scene_id is None:
        raise ToolRefused("this run has no scene in scope, so there is no scene to hold the rule",
                          how_to_fix='Use scope "production", or ask for the rule in a scene.',
                          example='{"rule": "...", "scope": "production"}')
    card: dict[str, Any] = {"kind": "memory", "rule": rule, "scope": args.scope, "by": "memory_propose",
                            "scene_id": str(ctx.scene_id) if args.scope == "scene" and ctx.scene_id else None}
    return Result(staged=True, card=staging.add(card), rule=rule, scope=args.scope,
                  next="A person will see this card and choose. Nothing is remembered yet.")


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
