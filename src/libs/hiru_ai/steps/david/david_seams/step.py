"""david_seams: `{"before": EndState, "link", "start"?, "after": plan, "number"}` → `{"problems"}`, or
`{"start": EndState, "end": EndState, "number"}` → `{"look_changes"}` (plan/2026-11-05e §4.3, §7 D9).

Deterministic, no model. The rules are `contracts.david.seams`.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.david import seams
from contracts.david.wire import DavidWire, EndStateW


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        number = int(payload.get("number") or 0)
        if "end" in payload:
            start = EndStateW.model_validate(payload["start"]) if payload.get("start") else None
            changes = seams.look_changes(start, EndStateW.model_validate(payload["end"]), number)
            return {"look_changes": [c.model_dump() for c in changes]}
        start = EndStateW.model_validate(payload["start"]) if payload.get("start") else None
        found = seams.seam(EndStateW.model_validate(payload["before"]), str(payload.get("link") or ""), start,
                           DavidWire.model_validate(payload["after"]), number)
    except (ValidationError, KeyError) as exc:
        return {"malformed": str(exc)[:600], "problems": []}
    return {"problems": [p.model_dump() for p in found]}
