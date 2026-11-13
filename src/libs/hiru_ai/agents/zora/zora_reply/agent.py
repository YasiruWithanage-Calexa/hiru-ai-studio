"""zora_reply hooks (plan/2026-11-13 §3.6 Reply; the lab's `turn._reply`).

The facts are the last thing the model reads, as plain sentences ("S01's size went from MS to WIDE"), never a machine
fact sheet (lab run 2: the reply pasted it back). No fallback here: a reply is read as it is written, so a model that
fails or does not fit the turn's budget is answered in code from the same facts (`zora_chat.turn.plain_reply`).
"""
from __future__ import annotations

from hiru_ai.agents.zora.zora_reply.schema import Input


def user_message(inp: Input) -> str:
    talk = "\n".join(inp.transcript) or "(none)"
    persona = f"<persona>{inp.persona}</persona>\n" if inp.persona else ""
    return (f"{persona}<recent_chat>\n{talk}\n</recent_chat>\n<scene>\n{inp.scene}\n</scene>\n<message>\n"
            f"{inp.message}\n</message>\n<turn>\nWHAT HAPPENED THIS TURN (the truth; it outranks the conversation):\n"
            + "\n\n".join(inp.facts) + "\n</turn>")
