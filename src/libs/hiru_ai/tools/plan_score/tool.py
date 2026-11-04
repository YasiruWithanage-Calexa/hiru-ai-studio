"""plan_score: the kernel score of a proposed plan, by name. Read-only; code picks the plan, not a model."""
from __future__ import annotations

from typing import ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext

# the terms of `kernel_score`, in the order it compares them
PARTS = ("problems", "two_speakers", "breath_missing", "turn_unseen", "teleports", "crossed_lines", "no_button",
         "breath_band_s", "over_envelope_s", "silent_s")


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "fewer `shots`"

    shots: list[views.ShotProposal] = Field(min_length=1, max_length=20, description="The plan to score")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')
    fixed_seconds: int | None = Field(None, description="Every shot runs this long (4, 6, 8) when fixed")


class Result(BaseModel):
    scene: str
    lower_is_better: bool = True
    score: list[float]
    parts: dict[str, float]
    total_s: int
    problems: list[str]
    plan: str | None = None


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    lines = store.lines(str(scene["id"]))
    canon = store.canon(tooling.production_of(ctx))
    rows = views.fitted_rows(scene, lines, args.shots, args.fixed_seconds)
    out = parts.module("step", "kernel_score", "step").run(
        {"scene": scene, "lines": lines, "shots": rows, "cast": views.cast_names(canon),
         "fixed_seconds": args.fixed_seconds})
    score = [float(x) for x in out["score"]]
    return Result(scene=tooling.scene_label(scene), score=score, parts=dict(zip(PARTS, score, strict=True)),
                  total_s=int(out["total_s"]), problems=list(out["issues"]),
                  plan=str(out["described"]) if args.response_format == "detailed" else None)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
