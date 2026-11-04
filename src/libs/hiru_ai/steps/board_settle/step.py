"""board_settle: `{"outputs": [{"agent": "sound", "ops": [...], "note": "..."}], "owners": {"set.sound_mode": "sound"}}`
→ the operations that land and the disagreements to show the person. `owners` is optional: the panel's ownership
table."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.board_settle.logic import Output, settle


def run(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = [Output(str(o["agent"]), list(o.get("ops") or []), str(o.get("note") or ""))
               for o in payload.get("outputs") or []]
    settled = settle(outputs, dict(payload["owners"]) if payload.get("owners") else None)
    return {"ops": [{"agent": agent, "op": op} for agent, op in settled.ops],
            "disagreements": settled.disagreements}
