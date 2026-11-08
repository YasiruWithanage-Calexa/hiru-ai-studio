"""sable_summary hooks. The summary so far and the messages to add are the user message; the prompt is static.

No model: the summary stays as it was (absent-safe), and the turn sends only the recent messages.
"""
from __future__ import annotations

from hiru_ai.agents.sable.sable_summary.schema import Input, Output


def user_message(inp: Input) -> str:
    return (f"<summary_so_far>\n{inp.summary.strip() or '(none yet)'}\n</summary_so_far>\n"
            f"<older_messages>\n{inp.messages.strip()}\n</older_messages>")


def fallback(inp: Input) -> Output | None:
    return Output(summary=inp.summary)
