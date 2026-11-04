"""timing_check: fit a scene's shots to the Veo clock and report what does not fit. Read-only; never trims.

With no `shots` it checks the plan as stored; with `shots` (`start`/`end` block indexes and the hints a proposal
carries) it checks a plan someone is thinking about, before it is saved. The kernel is `contracts.shotplan.fit`.
It also answers when each spoken line starts, which the director's `get_shot_timing` did.
"""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts import sceneplan
from contracts.shotplan import ProposedShot, fit
from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext


class Proposal(BaseModel):
    start: int = Field(ge=0, description="First block index (inclusive)")
    end: int = Field(ge=1, description="Last block index (exclusive)")
    framing: str = "MS"
    title: str = ""
    sound_mode: str | None = None
    duration: int | None = Field(None, description="A length hint (4, 6 or 8), exact when duration_locked")
    duration_locked: bool = False
    camera_link: str = "cut"


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')
    shots: list[Proposal] | None = Field(None, max_length=20, description="A plan to check instead of the stored one")
    fixed_seconds: int | None = Field(None, description="Every shot runs this long (4, 6, 8) when fixed")


class Result(BaseModel):
    scene: str
    total_s: int
    envelope_s: int
    silent_s: int
    over_envelope_s: int
    shots: list[dict[str, Any]]
    lines: list[dict[str, Any]]
    issues: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    items = sceneplan.scene_items(scene, store.lines(str(scene["id"])))
    if args.shots is None:
        proposal = sceneplan.proposal_for(sceneplan.plan_from_rows(store.shots(str(scene["id"]))))
    else:
        proposal = [ProposedShot(p.start, p.end, p.framing, p.title, p.sound_mode, p.duration, p.duration_locked,
                                 p.camera_link) for p in args.shots]
    result = fit(items, proposal, envelope_s=int(scene["envelope_s"]), fixed_seconds=args.fixed_seconds)
    return Result(scene=tooling.scene_label(scene),
                  **views.timing_view(result, detailed=args.response_format == "detailed"))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
