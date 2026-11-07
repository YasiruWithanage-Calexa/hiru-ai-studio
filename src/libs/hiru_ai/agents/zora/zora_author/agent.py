"""zora_author hooks (plan/2026-11-06e §4.5; the lab's `author_message`, Phase 3, arm A).

The system prompt is Shot Planner Jonathan's author prompt to the letter, then Zora's charter (`prompts/system.md`; a
test compares the head with the planner's file), so the chat's craft is the planner's craft. The user message is the
lab's, byte for byte, for the same input. No fallback: a turn whose author cannot answer says so in its ledger.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.wire import author_schema
from hiru_ai.agents.zora.zora_author.schema import Input

TRANSCRIPT = 4


def output_schema() -> dict[str, Any]:
    return author_schema()


def memory_scope(inp: Input) -> dict[str, Any]:
    return {"place": inp.place, "people": list(inp.people)}


def user_message(inp: Input) -> str:
    lines = ["CONVERSATION (recent):\n" + ("\n".join(inp.transcript[-TRANSCRIPT:]) or "(none)"), "", inp.plan, ""]
    lines.append("ALREADY DONE THIS TURN:\n" + ("\n".join(f"- {d}" for d in inp.done) or "- nothing yet"))
    lines.append("\nTASKS THIS TURN:")
    for i, t in enumerate(inp.tasks, start=1):
        lines.append(f"{i}. {t.instruction}\n   YOU MAY WRITE ONLY: " + ", ".join(t.allowed)
                     + f"\n   ON: {t.on}\n   MUST CHANGE: " + ", ".join(t.must))
    if inp.variants:
        lines.append(f"\nGive {inp.variants} VARIANTS (each a label and its own operations); leave `ops` empty.")
    if inp.faults:
        lines.append("\nAFTER YOUR EDIT THE PLANNER'S CHECKS FOUND (fix exactly these; change nothing else):\n"
                     + "\n".join(f"- {f}" for f in inp.faults))
    return "\n".join(lines)
