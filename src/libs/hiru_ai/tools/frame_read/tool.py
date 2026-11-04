"""frame_read: what frames and reference sheets exist and their state. Read-only; a storage path never leaves."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`shot` or `code`, one at a time"

    shot: str | None = Field(None, description='A shot: "S03" or 3. Returns its first frames')
    code: str | None = Field(None, max_length=20, description="A canon code (C02, L01). Returns its reference sheets")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')

    @model_validator(mode="after")
    def _one_of(self) -> Args:
        if not self.shot and not self.code:
            raise ValueError("pass `shot` (for first frames) or `code` (for reference sheets)")
        return self


class Result(BaseModel):
    frames: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []


def run(args: Args, ctx: RunContext) -> Result:
    frames_port = ctx.need("frames", "FrameStore")
    production = tooling.production_of(ctx)
    out = Result()
    if args.shot:
        store, scene = tooling.scene_in_scope(ctx, args.scene)
        shots = store.shots(str(scene["id"]))
        number = tooling.shot_number(args.shot)
        shot = views.shot_by_number(shots, number)
        if shot is None:
            raise tooling.not_found("shot", tooling.shot_code(number),
                                    [tooling.shot_code(int(s["number"])) for s in shots], example='{"shot": "S01"}')
        made = views.MadeAgainst(scene, shot, store.lines(str(scene["id"])), store.canon(production))
        found = frames_port.frame_status(production, shot_ids=[str(shot["id"])])["frames"]
        detailed = args.response_format == "detailed"
        out.frames = [{"shot": tooling.shot_code(number), "status": f["status"], "accepted": bool(f["accepted"]),
                       "out_of_date": bool(why := made.reasons(f.get("pins"))), "why": why,
                       **({"made": f.get("created_at"), "error": f.get("error")} if detailed else {})}
                      for f in found]
    if args.code:
        entities = ctx.need("canon", "CanonStore").entities(production) if ctx.ports.canon else []
        entity = views.find_entity(entities, args.code) if entities else None
        code = str(entity["code"]) if entity else args.code.upper()
        if entities and entity is None:
            raise tooling.not_found("canon item", args.code, views.entity_names(entities), example='{"code": "C02"}')
        out.sheets = frames_port.frame_status(production, codes=[code])["sheets"]
        if not out.sheets:
            raise ToolRefused(f"nothing is known about {args.code!r}", how_to_fix="Use a canon code like C02 or L01.",
                              example='{"code": "C02"}')
    return out


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
