"""sound_designer hooks (the board's `sound` craft). Ported from `director_chat/engine/agents.py`."""
from __future__ import annotations

from hiru_ai.agents.sound_designer.schema import Input, Output

NO_LEAD = "No lead persona: direct for a family teledrama audience."


def user_message(inp: Input) -> str:
    scope = ", ".join(f"S{n:02d}" for n in inp.shots) or "the whole scene"
    return (f"<lead_director>\n{inp.lead_charter or NO_LEAD}\n</lead_director>\n<shot_list>\n{inp.scene_text}\n"
            f"</shot_list>\nYour task ({scope}): {inp.instruction}")


def fallback(inp: Input) -> Output:
    return Output(ops=[], note="")
