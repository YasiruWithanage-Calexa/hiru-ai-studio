"""change_propose: a change to the plan, staged as a card for a person. It saves nothing and changes nothing itself.

The card goes into the run's `staging` port; the director turn shows it the way it shows an options card, and an
accepted card is applied by the same code that applies a button press. A model never writes the plan (plan/2026-11-04
D1)."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling, trial, views
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused


class Args(BaseModel):
    ops: list[views.ToolOp] = Field(min_length=1, max_length=8, description="The operations the change is made of")
    summary: str = Field(min_length=3, max_length=200,
                         description="One sentence for the person: what this does and why")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')


class Result(BaseModel):
    staged: bool
    card: str
    scene: str
    summary: str
    changes: list[str]
    timing: dict[str, Any]
    touched: list[str]
    next: str


def run(args: Args, ctx: RunContext) -> Result:
    staging = ctx.need("staging", "Staging")
    tried = trial.run(ctx, args.scene, args.ops)
    if tried.rejected:
        reasons = "; ".join(f"{row['op']}: {row['why']}" for row in tried.rows if not row["applied"])
        raise ToolRefused(f"{len(tried.rejected)} of {len(tried.rows)} operations would be refused ({reasons}). "
                          "Nothing was staged.",
                          how_to_fix="Fix or drop the refused operations and call again; plan_try shows the reasons "
                                     "without staging.",
                          example='{"summary": "Open on a close-up.", "ops": [{"op": "set", "shot": 1, '
                                  '"field": "framing", "value": "CU"}]}')
    ripple = tried.ripple()
    changes = [row["op"] for row in tried.rows]
    label = tooling.scene_label(tried.scene)
    card = staging.add({"kind": "change", "scene_id": str(tried.scene["id"]), "scene": label, "summary": args.summary,
                        "ops": tried.applied, "changes": changes, "touched": ripple["touched"],
                        "in_doubt": ripple["in_doubt"], "by": "change_propose"})
    return Result(staged=True, card=card, scene=label, summary=args.summary, changes=changes,
                  timing=tried.timing(), touched=ripple["touched"],
                  next="A person will see this card and choose. Nothing has changed yet.")


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
