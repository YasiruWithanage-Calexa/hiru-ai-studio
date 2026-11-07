"""zora_guard: `{"message", "reply"?, "ledger"?, "has_card"?, "pending"?}` → `{"confirms", "agrees", "undo",
"reply"?}` (plan/2026-11-06e §4.8).

Deterministic, no model. Reads a person's message for what code answers itself (a confirmation, an undo, a redo) and,
with a `reply` and the turn's `ledger` (`contracts.zora.ledger.Ledger` as data), returns the reply with every sentence
that cannot stand taken out. The rules are `logic`, copied from the old chat's guards so the two never share code.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.ledger import Ledger
from hiru_ai.steps.zora.zora_guard import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "")
    out: dict[str, Any] = {"confirms": logic.confirms(message), "agrees": logic.agrees(message),
                           "undo": logic.undo_asked(message)}
    if "reply" in payload:
        ledger = Ledger.model_validate(payload.get("ledger") or {})
        guarded = logic.guard_reply(str(payload["reply"]), ledger, has_card=bool(payload.get("has_card")),
                                    pending=bool(payload.get("pending")))
        out["reply"] = guarded or logic.template_reply(ledger)
    return out
