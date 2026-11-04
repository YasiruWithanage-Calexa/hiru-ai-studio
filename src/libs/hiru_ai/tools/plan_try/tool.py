"""plan_try: operations tried on a copy of the scene by the kernel, with the ripple. Read-only; nothing is saved.

One call replaces three: the kernel (what lands), the refusal screen (why not, in words a person reads: the kernel
already words its refusals with it) and the ripple (what an accepted edit touches). The operations are tried as the
conductor's, so an operation only a person may make (the script, the cast, the checks) is refused here as it would be
there."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling, trial, views
from hiru_ai.core.context import RunContext


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "fewer `ops`, or `response_format: concise`"

    ops: list[views.ToolOp] = Field(min_length=1, max_length=8, description="The operations to try, in order")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')


class Result(BaseModel):
    scene: str
    nothing_saved: bool = True
    applied: int
    refused: int
    results: list[dict[str, Any]]
    timing: dict[str, Any]
    ripple: dict[str, Any]


def run(args: Args, ctx: RunContext) -> Result:
    tried = trial.run(ctx, args.scene, args.ops)
    detailed = args.response_format == "detailed"
    return Result(scene=tooling.scene_label(tried.scene), applied=len(tried.applied), refused=len(tried.rejected),
                  results=tried.rows, timing=tried.timing(detailed=detailed), ripple=tried.ripple(detailed=detailed))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
