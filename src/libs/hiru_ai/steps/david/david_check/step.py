"""david_check: `{"scene", "plan", "removed"?}` → `{"ok", "problems", "counts"}` (plan/2026-11-05e §6).

Deterministic, no model. A problem is `{code, sentence, shots, fix, key}`; `fix` says who deals with it: `mend`
(code, in
`david_mend`), `repair` (the author is sent exactly this sentence), `drop` (an addition code removes) or `report` (shown
to a person, never sent back). `ok` is true when nothing is left for `repair`. The rules are `contracts.david.checks`.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.david import checks
from contracts.david.scene import SceneS
from contracts.david.wire import DavidWire


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, plan = SceneS.model_validate(payload["scene"]), DavidWire.model_validate(payload["plan"])
    except (ValidationError, KeyError) as exc:
        text = str(exc)[:600]
        return {"ok": False, "malformed": text, "problems": [{"code": "shape", "sentence": text, "shots": [],
                                                              "fix": "repair", "key": "shape:malformed"}],
                "counts": {"repair": 1}}
    removed = [(str(r["kind"]), int(r["after_block"])) for r in payload.get("removed") or []]
    found = checks.problems(scene, plan, removed)
    counts: dict[str, int] = {}
    for p in found:
        counts[p.fix] = counts.get(p.fix, 0) + 1
    return {"ok": not checks.repairable(found), "problems": [p.model_dump() for p in found], "counts": counts}
