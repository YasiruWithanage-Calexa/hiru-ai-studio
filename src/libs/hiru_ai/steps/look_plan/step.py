"""look_plan: `{"canon": [rows], "with_looks": ["<entity id>"], "episodes": 3, "production_id": "...", "asked": [...]}`.

`asked` is the look_drafter's `looks` list (or empty / absent when it was not asked or failed): the rules cover the
rest.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.look_plan import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    episodes = int(payload["episodes"])
    rows = logic.wanted(payload["canon"], set(payload.get("with_looks") or []))
    asked = logic.asked_from(payload.get("asked") or [], episodes) if rows else {}
    out, names = logic.rows_for(rows, asked, episodes, production_id=str(payload["production_id"]),
                                actor=payload.get("actor"))
    return {"rows": out, "names": names, "wanted": [str(r["name"]) for r in rows]}
