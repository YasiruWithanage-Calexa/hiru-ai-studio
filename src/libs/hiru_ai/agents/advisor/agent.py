"""advisor hooks. Ported from `director_chat/engine/agents.py` (`advisor_review`).

Advisors are heard in the reply, never in the plan. One that agrees, or has nothing to say, adds nothing; one that
cannot answer is left out (the fallback agrees), so the turn never waits on an opinion.
"""
from __future__ import annotations

from hiru_ai.agents.advisor.schema import Input, Output


def user_message(inp: Input) -> str:
    return (f"<your_style>\n{inp.charter}\n</your_style>\n<changes>\n{inp.summary}\n"
            f"</changes>\n<shot_list>\n{inp.scene_text}\n</shot_list>")


def fallback(inp: Input) -> Output:
    return Output(agrees=True, view="")
