"""raphael_write: a result → the rows to store. Deterministic, no model, no database.

    {"scene": <scene row>, "lines": [<dialogue_lines rows>], "stored": <StoredRaphael as data>, "canon": [<canon rows>],
     "production": <production row>, "job_id"?: str}
        → {"shots": [...], "lines": [...], "fields": {status, fit_report, raphael, coverage}}     the system saves them

An approved scene is refused (`{"refused": ...}`); a result that cannot be read says so instead of raising.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.raphael.stored import StoredRaphael
from hiru_ai.steps.raphael.raphael_write import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        stored = StoredRaphael.model_validate(payload["stored"])
        shots, lines, fields = logic.write(
            dict(payload["scene"]),
            list(payload.get("lines") or []),
            stored,
            list(payload.get("canon") or []),
            dict(payload.get("production") or {}),
            str(payload.get("job_id") or ""),
        )
    except (ValidationError, KeyError) as exc:
        return {"malformed": str(exc)[:600]}
    except PermissionError as exc:
        return {"refused": str(exc)}
    return {"shots": shots, "lines": lines, "fields": fields}
