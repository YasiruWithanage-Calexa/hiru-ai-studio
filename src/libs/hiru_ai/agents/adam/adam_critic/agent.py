"""adam_critic hooks (plan/2026-11-05 T4). New for Adam: the four screening critics in one call, no fallback (plan
§5.5); a
critic that cannot answer leaves the plan as it is. The answer is cleaned in code the way each critic's was: a note on a
card the plan does not have is dropped and at most four notes are kept for a lens, most severe first (`Output.results`).
"""
from __future__ import annotations

from contracts.adam.screening import screen_message
from hiru_ai.agents.adam.adam_critic.schema import Input, Output


def user_message(inp: Input) -> str:
    return screen_message(inp)


def finish(inp: Input, out: Output) -> Output:
    return out
