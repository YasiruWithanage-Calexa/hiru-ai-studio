"""zora_reply hooks (plan/2026-11-06e §3, §4.6 step 5; Nova W2).

The reply is written from the ledger, which is the last thing the model reads; the plan it sees is the one AFTER the
turn. There is no fallback here: a reply is read as it is written, so a model that fails is answered in code from the
same ledger (`zora_guard.template_reply`), which the system decides.
"""
from __future__ import annotations

from hiru_ai.agents.zora.zora_reply.schema import Input

TRANSCRIPT = 6


def user_message(inp: Input) -> str:
    persona = f"<persona>{inp.persona}</persona>\n" if inp.persona else ""
    talk = "\n".join(inp.transcript[-TRANSCRIPT:]) or "(none)"
    return (f"{persona}<recent_chat>\n{talk}\n</recent_chat>\n<plan>\n{inp.plan}\n</plan>\n"
            f"<message>\n{inp.message}\n</message>\n<turn>\nTURN:\n" + "\n\n".join(inp.turn) + "\n</turn>")
