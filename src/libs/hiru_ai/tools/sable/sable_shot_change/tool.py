"""sable_shot_change: a change to the open scene's shot rows, staged as a card for a person. It saves nothing.

The operations are the row kernel's (`steps/coverage_kernel`), tried on a copy as a model's (`core.row_trial`): if
every one would land, a card goes into the run's `staging` port with what would change, what it leaves to check, why a
person must OK it, and the rows' fingerprint. On Accept the function replays the same operations and saves them in
place (plan/2026-11-13 phase 8): refused if the shots changed since, and a revision the scene's chat can undo. A model
never writes the shots."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import row_trial, tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused


class Args(BaseModel):
    ops: list[row_trial.RowOp] = Field(min_length=1, max_length=row_trial.MAX_OPS,
                                       description="The operations the change is made of")
    summary: str = Field(min_length=3, max_length=200,
                         description="One sentence for the person: what this does and why")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: the scene in view')


class Result(BaseModel):
    staged: bool
    card: str
    scene: str
    summary: str
    changes: list[str]
    touched: list[str]
    in_doubt: list[str]
    timing: dict[str, Any]
    next: str


def run(args: Args, ctx: RunContext) -> Result:
    staging = ctx.need("staging", "Staging")
    tried, raw = row_trial.run(ctx, args.scene, args.ops)
    rows = tried.rows(raw)
    if tried.rejected:
        reasons = "; ".join(f"{r['op']}: {r['why']}" for r in rows if not r["applied"])
        raise ToolRefused(f"{len(tried.rejected)} of {len(rows)} operations would be refused ({reasons}). Nothing was "
                          "staged.",
                          how_to_fix="Fix or drop the refused operations and call again; sable_shot_try shows the "
                                     "reasons without staging. A locked field is the person's: say so.",
                          example='{"summary": "Open on a close-up.", "ops": [{"op": "set", "shot": 1, '
                                  '"field": "size", "value": "CU"}]}')
    if not tried.done:
        raise ToolRefused("Those operations change nothing in the shots. Nothing was staged.",
                          how_to_fix="Read the shot (sable_shot_try with no ops) and propose what differs.")
    in_doubt = list(dict.fromkeys(tried.problems()))
    card = staging.add({"kind": "change", "engine": "rows", "scene_id": str(tried.scene["id"]), "scene": tried.label,
                        "summary": args.summary, "ops": [{"op": a["op"], "by": a["by"]} for a in tried.applied],
                        "made_on": tried.made_on, "changes": tried.done + tried.notes, "touched": tried.touched(),
                        "in_doubt": in_doubt, "risks": tried.risks(), "by": "sable_shot_change"})
    return Result(staged=True, card=card, scene=tried.label, summary=args.summary, changes=tried.done + tried.notes,
                  touched=tried.touched(), in_doubt=in_doubt, timing=tried.timing(),
                  next="A person will see this card and choose. Nothing has changed yet.")


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
