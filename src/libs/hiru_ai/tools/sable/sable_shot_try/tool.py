"""sable_shot_try: the open scene's shot rows as the row kernel numbers them, and what operations would do to them.
Nothing is saved or staged.

With no operations it returns the scene's view (the blocks, each spoken line's code, one line per clip). With some, it
tries them on a copy as `sable_shot_change` would (`core.row_trial`, plan/2026-11-13 phase 8) and says for each whether
it lands and why not, what would change, the problems left and whether a person must OK it."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import row_trial, tooling
from hiru_ai.core.context import RunContext


class Args(BaseModel):
    ops: list[row_trial.RowOp] = Field(default_factory=list, max_length=row_trial.MAX_OPS,
                                       description="The operations to try; none = just show the shots")
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: the scene in view')


class Result(BaseModel):
    scene: str
    shots: str  # the view (with no ops) or the shots after the ops, one line each
    applied: int
    refused: int
    tried: list[dict[str, Any]]  # {op, applied, why?}
    changes: list[str]
    new_problems: list[str]
    needs_ok: list[str]  # why a person would be asked first (shown on the card)
    timing: dict[str, Any]


def run(args: Args, ctx: RunContext) -> Result:
    if not args.ops:
        scene, shots = row_trial.view(ctx, args.scene)
        return Result(scene=tooling.scene_label(scene), shots=shots, applied=0, refused=0, tried=[], changes=[],
                      new_problems=[], needs_ok=[], timing={})
    tried, raw = row_trial.run(ctx, args.scene, args.ops)
    return Result(scene=tried.label, shots=tried.after.render(detail=False),
                  applied=len(tried.applied), refused=len(tried.rejected), tried=tried.rows(raw),
                  changes=tried.done + tried.notes, new_problems=tried.problems(), needs_ok=tried.risks(),
                  timing=tried.timing())


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
