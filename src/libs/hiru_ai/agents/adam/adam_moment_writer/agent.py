"""adam_moment_writer hooks (plan/2026-11-04b §5.2).

New for Adam. The answer is tidied in code (ids without spaces, unique, present; a negative time is zero) and nothing
else: whether a moment invents story is `adam_fidelity`'s decision, made on the moment list after this agent, so a
refusal names its reason instead of being repaired here. There is no fallback: with no model the job fails clearly and
the production's classic planner is the way out (plan §5.5).
"""
from __future__ import annotations

from contracts.adam.plan import compact
from hiru_ai.agents.adam.adam_moment_writer.schema import Input, Output


def user_message(inp: Input) -> str:
    return (f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            f"<analysis>\n{compact(inp.analysis)}\n</analysis>\n\n"
            f"<treatment>\n{compact(inp.treatment)}\n</treatment>"
            + (f"\n\n<notes>\n{inp.notes}\n</notes>" if inp.notes else ""))


def finish(inp: Input, out: Output) -> Output:
    return Output.model_validate(out.tidy().model_dump())
