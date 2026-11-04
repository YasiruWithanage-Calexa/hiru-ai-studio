"""craft_articulator hooks. Ported from `shot_producer/engine/techniques.py` (`articulate`).

Its phrases are the technique queries (one blended query returns the centroid of the piece) and open the DoP's
production block. Without a model there are none, which is also the fallback.
"""
from __future__ import annotations

from hiru_ai.agents.craft_articulator.schema import Input, Output

MAX_PROBLEMS = 5


def user_message(inp: Input) -> str:
    return "<scenes>\n" + "\n\n".join(inp.scenes) + "\n</scenes>"


def finish(inp: Input, out: Output) -> Output:
    clean: list[str] = []
    for p in out.problems:
        text = " ".join(str(p).split())[:240]
        if text and text not in clean:
            clean.append(text)
    return Output(problems=clean[:MAX_PROBLEMS])


def fallback(inp: Input) -> Output:
    return Output(problems=[])
