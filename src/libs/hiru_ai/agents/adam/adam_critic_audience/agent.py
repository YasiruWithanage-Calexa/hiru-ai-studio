"""adam_critic_audience hooks (plan/2026-11-04b §5.4). New for Adam: the audience lens only, no fallback (plan §5.5); a
critic that cannot answer is left out by the panel and the first plan stands. The answer is cleaned in code: a note on a
card the plan does not have is dropped, and at most four notes are kept, most severe first."""
from __future__ import annotations

from contracts.adam.screening import screen_message
from hiru_ai.agents.adam.adam_critic_audience.schema import Input, Output


def user_message(inp: Input) -> str:
    return screen_message(inp)


def finish(inp: Input, out: Output) -> Output:
    return Output.model_validate(out.clean({c.number for c in inp.cards}).model_dump())
