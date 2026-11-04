"""scene_write: save an edited scene plan.

The wrapper the director saves a turn's result through (`Store.save_plan`): shots keep their ids so frames and prompts
stay attached, a removed line goes first, and the scene's own fields last.

What it refuses, whoever asks (a tool answers for its own safety, not the graph's):
  * a scene, shot or line of another production or scene;
  * a spoken line that changes (words, speaker, delivery), is added or is removed, unless `by` is "person" (their own
    edit) or "translator" (a translation they accepted, which may only rewrite words and keep the original);
  * a scene field that moves the scene (`id`, `production_id`, `episode_id`).
"""
from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused

WORDS = ("text", "speaker", "delivery")
TRANSLATED = ("text", "source_text", "source_lang")
FROZEN_SCENE_FIELDS = ("id", "production_id", "episode_id")


class Args(BaseModel):
    scene_id: str
    shots: list[dict[str, Any]] = Field(default_factory=list, description="Shot rows to upsert, by id")
    removed_shots: list[str] = Field(default_factory=list)
    lines: list[dict[str, Any]] = Field(default_factory=list, description="Dialogue line rows to upsert, by id")
    removed_lines: list[str] = Field(default_factory=list)
    scene_fields: dict[str, Any] = Field(default_factory=dict, description="Columns of the scene to change")
    by: Literal["agent", "person", "translator"] = "agent"


class Result(BaseModel):
    shots: int
    removed_shots: int
    lines: int
    removed_lines: int


def _check_lines(args: Args, stored: dict[str, dict[str, Any]]) -> None:
    for row in args.lines:
        before = stored.get(str(row.get("id")))
        if before is not None and str(row.get("scene_id", args.scene_id)) != str(args.scene_id):
            raise ToolRefused("a line belongs to another scene")
        changed = before is None or any(k in row and row[k] != before.get(k) for k in WORDS)
        if not changed or args.by == "person":
            continue
        if args.by == "translator" and before is not None and not any(
                k in row and row[k] != before.get(k) for k in ("speaker", "delivery")) and "source_text" in row:
            continue  # a translation: the words change, the original is kept as `source_text`
        raise ToolRefused("only a person's own words change a line (or a translation they accepted)")
    if args.removed_lines and args.by != "person":
        raise ToolRefused("only a person can remove a line")
    stray = [i for i in args.removed_lines if str(i) not in stored]
    if stray:
        raise ToolRefused("a line to remove does not belong to this scene")


def run(args: Args, ctx: RunContext) -> Result:
    store, _ = tooling.scene_of(ctx, args.scene_id)
    stored_lines = {str(r["id"]): r for r in store.lines(args.scene_id)}
    stored_shots = {str(r["id"]) for r in store.shots(args.scene_id)}
    _check_lines(args, stored_lines)
    if any(str(i) not in stored_shots for i in args.removed_shots):
        raise ToolRefused("a shot to remove does not belong to this scene")
    if any(str(s.get("scene_id", args.scene_id)) != str(args.scene_id) for s in args.shots):
        raise ToolRefused("a shot belongs to another scene")
    if any(not s.get("id") for s in args.shots):
        raise ToolRefused("every shot needs an id")
    rows = [*args.shots, *args.lines]
    if any(str(r.get("production_id", ctx.production_id)) != str(ctx.production_id) for r in rows):
        raise ToolRefused("a row belongs to another production")
    moved = [k for k in FROZEN_SCENE_FIELDS if k in args.scene_fields]
    if moved:
        raise ToolRefused(f"a scene cannot change its {', '.join(moved)}")
    store.save_plan(args.scene_id, args.shots, [str(i) for i in args.removed_shots], args.lines, args.scene_fields,
                    [str(i) for i in args.removed_lines] or None)
    return Result(shots=len(args.shots), removed_shots=len(args.removed_shots), lines=len(args.lines),
                  removed_lines=len(args.removed_lines))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
