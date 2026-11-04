"""shot_intent hooks. Ported from `shot_producer/engine/intent.py` (`write`).

The production block and the scene prompt are rendered by the producer's system from the stored rows (the `serialize`
step's shot model); this agent joins them, production first so the cached prefix is the same for every scene. Its answer
is matched BY NUMBER in code, and a shot it skipped gets the rules' intent, so there is no fallback here.
"""
from __future__ import annotations

from hiru_ai.agents.shot_intent.schema import Input


def user_message(inp: Input) -> str:
    return inp.production + "\n\n" + inp.scene
