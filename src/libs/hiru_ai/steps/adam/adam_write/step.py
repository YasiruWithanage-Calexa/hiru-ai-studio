"""adam_write: a plan → the rows to store. Deterministic, no model, no database.

    {"scene": <scene row>, "lines": [<dialogue_lines rows>], "stored": <StoredPlan as data>, "fit": <adam_fit answer>,
     "notes"?: [str], "people"?: {character name: canon id}}
        → {"shots": [...], "lines": [...], "fields": {status, fit_report, adam}}     the system saves them
    {"moments": [...], "removed": [...]}
        → {"moments": [...kept], "dropped": [ids]}                                   elaborations a person removed

An approved scene is refused (`{"refused": ...}`); a plan that cannot be read says so instead of raising.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import Moment, errors_of, norm
from contracts.adam.stored import Removed, StoredPlan
from hiru_ai.steps.adam.adam_write import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if "stored" not in payload:
            moments = [Moment.model_validate(m) for m in payload.get("moments") or []]
            removed = [Removed.model_validate(r) for r in payload.get("removed") or []]
            kept, dropped = logic.apply_removed(moments, removed)
            return {"moments": [m.model_dump(mode="json") for m in kept], "dropped": dropped}
        stored = StoredPlan.model_validate(payload["stored"])
        shots, lines, fields = logic.write(dict(payload["scene"]), list(payload.get("lines") or []), stored,
                                           dict(payload.get("fit") or {}), list(payload.get("notes") or []),
                                           {norm(k): str(v) for k, v in (payload.get("people") or {}).items()})
    except ValidationError as exc:
        return {"malformed": errors_of(exc)}
    except PermissionError as exc:
        return {"refused": str(exc)}
    return {"shots": shots, "lines": lines, "fields": fields}
