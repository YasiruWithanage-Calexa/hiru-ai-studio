"""continuity_check: the join between shot N and shot N+1, in code (the `shot_joins` step). Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    shot: str = Field(description='The shot that comes first: "S02" or 2. It is compared with the shot after it')
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')


class Result(BaseModel):
    first: str
    second: str | None
    join: str | None
    ok: bool
    findings: list[dict[str, Any]]
    staging_map: bool
    note: str = ""


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    scene_id = str(scene["id"])
    shots = store.shots(scene_id)
    number = tooling.shot_number(args.shot)
    if views.shot_by_number(shots, number) is None:
        raise tooling.not_found("shot", tooling.shot_code(number), [tooling.shot_code(int(s["number"])) for s in shots],
                                example='{"shot": "S01"}')
    canon = store.canon(tooling.production_of(ctx))
    try:
        out = parts.module("step", "shot_joins", "step").run(
            {"scene": scene, "lines": store.lines(scene_id), "shots": shots, "number": number,
             "cast": views.cast_names(canon), "canon": canon})
    except ValueError as exc:  # the step's own sentence
        raise ToolRefused(str(exc)) from exc
    detailed = args.response_format == "detailed"
    return Result(first=out["first"], second=out["second"], join=out["join"], ok=out["ok"],
                  findings=[f if detailed else {"code": f["code"], "message": f["message"]} for f in out["findings"]],
                  staging_map=out["staging_map"], note=out.get("note", ""))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
