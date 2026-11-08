"""raphael_cinematic hooks (plan/2026-11-08e §3.5): stage 2, the cinematic pass.

A fresh conversation (stage 1's turns do not count against it) over stage 1's finished bin, which the tools refuse to
touch.
The prompt is the lab's `cinematic.md` plus the variety lines (D-V). The tools are CODE: `Stage2Session`.
"""

from __future__ import annotations

from typing import Any

from contracts.raphael.bin import Bin
from contracts.raphael.scene import Brief
from contracts.raphael.tools import Stage2Session
from hiru_ai.agents.raphael import wire_schema
from hiru_ai.agents.raphael.raphael_cinematic.schema import Input, Output

MAX_OUTPUT = 48_000


def user_message(inp: Input) -> str:
    return inp.opening


def session(inp: Input) -> Stage2Session:
    """The session over a bin rebuilt from stage 1's result: the next clip id follows stage 1's last."""
    work = Bin(scene=inp.scene_no)
    work.edit = inp.edit
    work.clips = [c.model_copy(deep=True) for c in inp.clips]
    work.next_no = max((int(c.id[1:]) for c in work.clips if c.id[1:].isdigit()), default=0) + 1
    return Stage2Session(
        Brief(inp.scene, inp.guide_s), work, cap=inp.cap, allowed=tuple(inp.allowed), max_turns=inp.max_turns
    )


def converse_args(inp: Input, run: Stage2Session) -> dict[str, Any]:
    def before(turn: int) -> None:
        run.turn = turn

    return {
        "tools": wire_schema.stage2_specs(),
        "call_tool": run.call,
        "finished": lambda: run.done,
        "max_turns": inp.max_turns,
        "max_output": MAX_OUTPUT,
        "later_tier": "raphael_cinematic_repair",  # plan/2026-11-08f §5: the repair turns, at their own effort
        "later_when": lambda turn: bool(run.work.extras()),  # clips written: repairs from here
        "before": before,
    }


def outcome(run: Stage2Session) -> dict[str, Any]:
    return {
        "clips": len(run.work.clips),
        "cinematic": len(run.work.extras()),
        "take_s": run.work.counts()["take_s"],
        "changed_must": run.changed_must(),
        "done": run.done,
    }


def output_for(stopped: str) -> Output:
    return Output(stopped=stopped)
