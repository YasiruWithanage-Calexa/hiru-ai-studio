"""staging_check: teleports, crossed lines and broken eyelines of a plan, from the staging map. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')
    shots: list[views.ShotProposal] | None = Field(None, max_length=20,
                                                     description="A plan to check instead of the stored one")


class Result(BaseModel):
    scene: str
    has_staging_map: bool
    ok: bool
    findings: list[dict[str, Any]]
    fixes: list[dict[str, Any]]
    unplaced: list[str]


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    scene_id = str(scene["id"])
    lines = store.lines(scene_id)
    canon = store.canon(tooling.production_of(ctx))
    rows = views.fitted_rows(scene, lines, args.shots) if args.shots else store.shots(scene_id)
    out = parts.module("step", "stage_check", "step").run(
        {"scene": scene, "lines": lines, "shots": rows, "cast": views.cast_names(canon)})
    detailed = args.response_format == "detailed"
    findings = [{"code": f["code"], "message": f["message"],
                 **({"shot": tooling.shot_code(f["shot"])} if f.get("shot") else {}),
                 **({"block": f["block"]} if detailed and f.get("block") is not None else {})} for f in out["findings"]]
    return Result(scene=tooling.scene_label(scene), has_staging_map=bool(scene.get("staging")), ok=not findings,
                  findings=findings,
                  fixes=[{"who": m["who"], "move_to": m["zone"], "before_block": m["before_block"]}
                         for m in out["moves"]],
                  unplaced=list(out["unplaced"]))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
