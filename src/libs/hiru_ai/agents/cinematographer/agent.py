"""cinematographer hooks. Ported from `director_chat/engine/agents.py` (`run_specialists`).

Specialists run in parallel on a scoped slice of the scene and never talk to each other. Each returns operations and a
one-sentence note; the `board_settle` step settles collisions by OWNERSHIP, and the kernel applies what lands. The
panel's manifest says which operations this craft owns. A specialist that fails returns no operations (the fallback).
"""
from __future__ import annotations

from hiru_ai.agents.cinematographer.schema import Input, Output

NO_LEAD = "No lead persona: direct for a family teledrama audience."


def user_message(inp: Input) -> str:
    scope = ", ".join(f"S{n:02d}" for n in inp.shots) or "the whole scene"
    return (f"<lead_director>\n{inp.lead_charter or NO_LEAD}\n</lead_director>\n<shot_list>\n{inp.scene_text}\n"
            f"</shot_list>\nYour task ({scope}): {inp.instruction}")


def fallback(inp: Input) -> Output:
    return Output(ops=[], note="")
