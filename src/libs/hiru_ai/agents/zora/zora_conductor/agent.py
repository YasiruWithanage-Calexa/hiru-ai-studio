"""zora_conductor hooks (plan/2026-11-06e §4.4; the lab's `conductor_message`, Phase 3).

The user message is the conversation (the last four messages), the plan with every address, and the person's latest
message. A retry is told exactly what was wrong (Nova W1: `problems`), after everything else, so the prefix a cache
keeps is the same bytes as the first call's. There is no fallback: with no model, the turn says Zora needs one.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.wire import conductor_schema
from hiru_ai.agents.zora.zora_conductor.schema import Input

TRANSCRIPT = 4


def output_schema() -> dict[str, Any]:
    return conductor_schema()


def user_message(inp: Input) -> str:
    talk = "\n".join(inp.transcript[-TRANSCRIPT:]) or "(no earlier messages)"
    text = f"CONVERSATION (recent):\n{talk}\n\n{inp.plan}\n\nLATEST MESSAGE FROM THE DIRECTOR:\n{inp.message}"
    if inp.problems:
        text += ("\n\nYOUR LAST ANSWER COULD NOT BE USED (answer again, the whole answer, fixing exactly this):\n"
                 + "\n".join(f"- {p}" for p in inp.problems))
    return text
