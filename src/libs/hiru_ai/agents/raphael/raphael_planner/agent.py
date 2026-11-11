"""raphael_planner hooks (plan/2026-11-08e §3.1): stage 1, the intended cut and the must bin.

The prompt is the lab's `raphael_must.md` (S1: must clips only; the room above the target belongs to the cinematic
pass).
The user message is the opening `contracts.raphael.pack` built. The tools are CODE:
`contracts.raphael.tools.Stage1Session`
runs them and returns the check report; `Agent.converse` carries the conversation. There is no fallback: with no model
the
job fails clearly and names the classic planner.
"""

from __future__ import annotations

from typing import Any

from contracts.raphael.scene import Brief
from contracts.raphael.tools import Stage1Session
from hiru_ai.agents.raphael import wire_schema
from hiru_ai.agents.raphael.raphael_planner.schema import Input, Output

MAX_OUTPUT = 48_000  # reasoning included; a sequence of complete clips per call. It bounds a turn's worst case


def user_message(inp: Input) -> str:
    return inp.opening


def session(inp: Input) -> Stage1Session:
    return Stage1Session(
        Brief(inp.scene, inp.guide_s),
        allowed=tuple(inp.allowed),
        max_turns=inp.max_turns,
        scene_no=inp.scene_no,
        breakdown=inp.breakdown,
    )


def converse_args(inp: Input, run: Stage1Session) -> dict[str, Any]:
    """What `Agent.converse` takes for this session. `before` records the turn on the session (the report says how many
    turns are left); a caller that adds a money cap calls it first."""

    def before(turn: int) -> None:
        run.turn = turn

    return {
        "tools": wire_schema.stage1_specs(),
        "call_tool": run.call,
        "finished": lambda: run.done,
        "max_turns": inp.max_turns,
        "max_output": MAX_OUTPUT,
        "later_tier": "raphael_repair",  # plan/2026-11-08f §5: the repair turns, at their own effort
        "later_when": lambda turn: run.work.counts()["written"] > 0,  # clips written: repairs from here
        "before": before,
    }


def outcome(run: Stage1Session) -> dict[str, Any]:
    """The session's result as data (evals, tests)."""
    counts = run.work.counts()
    return {"clips": counts["clips"], "must": counts["must"], "take_s": counts["take_s"], "done": run.done}


def output_for(stopped: str) -> Output:
    return Output(stopped=stopped)
