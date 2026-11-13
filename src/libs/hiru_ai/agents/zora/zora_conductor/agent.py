"""zora_conductor hooks (plan/2026-11-13 §3.6, §3.9; the lab's `turn._conductor_user`).

The user message is the conversation (the last four messages), the scene as clip heads, what the person rejected in this
thread, and the person's latest message. A retry is told exactly what was wrong, after everything else, so the prefix a
cache keeps is the same bytes as the first call's. The production memory (a standing rule the person stated) is added by
the `production_memory` middleware. There is no fallback: a turn whose conductor cannot answer asks, it never guesses.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.wire import conductor_schema
from hiru_ai.agents.zora.zora_conductor.schema import Input

TRANSCRIPT = 4


def output_schema() -> dict[str, Any]:
    return conductor_schema()


def memory_scope(inp: Input) -> dict[str, Any]:
    return {"place": inp.place, "people": list(inp.people)}


def user_message(inp: Input) -> str:
    talk = "\n".join(inp.transcript[-TRANSCRIPT:]) or "(no earlier messages)"
    text = f"CONVERSATION (recent):\n{talk}\n\n{inp.scene}\n\n"
    if inp.rejected:
        text += f"THE PERSON REJECTED IN THIS THREAD (do not offer again): {'; '.join(inp.rejected)}\n\n"
    text += f"LATEST MESSAGE FROM THE DIRECTOR:\n{inp.message}"
    if inp.problems:
        text += ("\n\nYOUR LAST ANSWER COULD NOT BE USED (answer again, the whole answer, fixing exactly this):\n"
                 + "\n".join(f"- {p}" for p in inp.problems))
    return text
