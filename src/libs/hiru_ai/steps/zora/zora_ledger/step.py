"""zora_ledger: `{"before", "after", "refused"?, "team_refused"?, "undelivered"?, "attempted"?, "staged"?, "mended"?,
"problems"?, "overruns"?, "seams"?, "stale"?, "offer"?, "undone"?}` → `{"ops", "gate", "context"}` (plan/2026-11-06e
§4.6, §4.10).

Deterministic, no model. `before` and `after` are the plan exported WITH handles. `ops` is the event the interface reads
(`nothing_changed` explicit), `gate` the warnings under the panel header, `context` the blocks the reply is given last.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.zora.zora_ledger.logic import build

LISTS = ("refused", "team_refused", "undelivered", "staged", "mended", "problems", "overruns", "seams", "stale",
         "locks")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    ledger = build(payload["before"], payload["after"], attempted=bool(payload.get("attempted")),
                   offer=str(payload.get("offer") or ""), undone=bool(payload.get("undone")),
                   **{k: [str(x) for x in payload.get(k) or []] for k in LISTS})
    return {"ops": ledger.event(), "gate": ledger.gate(), "context": ledger.context()}
