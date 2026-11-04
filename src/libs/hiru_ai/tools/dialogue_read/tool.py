"""dialogue_read: a scene's spoken lines exactly as stored. Read-only.

Dialogue keeps the language it was written in (CLAUDE.md), so a line is returned as stored and never normalised,
trimmed or translated here; `source_text` / `source_lang` appear only on a line a person accepted a translation for.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext

COLUMNS = ("id", "ord", "speaker", "character_id", "text", "delivery", "words", "source_text", "source_lang")


class Args(BaseModel):
    scene_id: str | None = Field(None, description='The scene: "E1S2", or its id. Default: the scene this run is about')


class Result(BaseModel):
    lines: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene_id)
    return Result(lines=[{k: row[k] for k in COLUMNS if k in row} for row in store.lines(scene["id"])])


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
