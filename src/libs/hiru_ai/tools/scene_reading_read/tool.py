"""scene_reading_read: the scene's reading and staging map, for a stretch of blocks. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext

UNIT_KEYS = ("from_block", "to_block", "wants", "turn_block")
HOLD_KEYS = ("after_block", "kind", "who", "seconds", "why")
MARK_KEYS = ("block", "who", "zone", "facing", "frame_side", "holding")


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`from_block` and `to_block`"

    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')
    from_block: int | None = Field(None, ge=0, description="First block of the stretch (inclusive)")
    to_block: int | None = Field(None, ge=0, description="Last block of the stretch (inclusive)")


class Result(BaseModel):
    scene: str
    blocks: str
    about: str
    value: dict[str, Any]
    tone: str
    ending: str
    units: list[dict[str, Any]]
    holds: list[dict[str, Any]]
    subtext: list[Any]
    zones: list[str]
    marks: list[dict[str, Any]]
    has_reading: bool
    has_staging: bool


def _pick(row: dict[str, Any], keys: tuple[str, ...], detailed: bool) -> dict[str, Any]:
    return dict(row) if detailed else {k: row[k] for k in keys if k in row}


def run(args: Args, ctx: RunContext) -> Result:
    _, scene = tooling.scene_in_scope(ctx, args.scene)
    reading, staging = scene.get("reading") or {}, scene.get("staging") or {}
    low = 0 if args.from_block is None else args.from_block
    high = 10**6 if args.to_block is None else args.to_block
    detailed = args.response_format == "detailed"
    units = [u for u in reading.get("units") or [] if int(u["to_block"]) >= low and int(u["from_block"]) <= high]
    holds = [h for h in reading.get("breath") or [] if low <= int(h["after_block"]) <= high and not h.get("off")]
    marks = [m for m in staging.get("marks") or [] if low <= int(m["block"]) <= high]
    return Result(
        scene=tooling.scene_label(scene), blocks=f"{low}-{high if args.to_block is not None else 'end'}",
        about=str(reading.get("about") or ""), value=dict(reading.get("value") or {}),
        tone=str(reading.get("tone") or ""),
        ending=str(reading.get("ending") or ""), units=[_pick(u, UNIT_KEYS, detailed) for u in units],
        holds=[_pick(h, HOLD_KEYS, detailed) for h in holds], subtext=list(reading.get("subtext") or []),
        zones=list(staging.get("zones") or []), marks=[_pick(m, MARK_KEYS, detailed) for m in marks],
        has_reading=bool(reading), has_staging=bool(staging))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
