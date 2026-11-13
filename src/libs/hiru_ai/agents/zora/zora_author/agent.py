"""zora_author hooks (plan/2026-11-13 §3.6, §3.9; the lab's `turn._author_user`).

The system prompt is Zora's own (the lab's `prompts/author.md` with the safe-depiction line), not a planner's: Zora
edits any planner's scene. The user message is the lab's layout. No fallback: a turn whose author cannot answer says so.
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
    lines = ["CONVERSATION (recent):\n" + ("\n".join(inp.transcript[-TRANSCRIPT:]) or "(none)"), "", inp.scene, ""]
    lines.append("ALREADY DONE THIS TURN:\n" + ("\n".join(f"- {d}" for d in inp.done) or "- nothing yet"))
    lines.append("\nTASKS THIS TURN:")
    for i, t in enumerate(inp.tasks, start=1):
        lines.append(f"{i}. {t.instruction}\n   YOU MAY CHANGE: {', '.join(t.writes)}\n   ON: {t.on}")
    if inp.variants:
        lines.append(f"\nGive {inp.variants} VARIANTS (each a short label and its own operations, at most 6 operations "
                     "with short values); leave `ops` empty.")
    if inp.faults:
        lines.append("\nAFTER THE EDIT THE CHECKS FOUND (fix exactly these; change nothing else):\n"
                     + "\n".join(f"- {f}" for f in inp.faults))
    return "\n".join(lines)
