"""jonathan_check: `{"scene", "plan", "removed"?, "craft"?}` → `{"ok", "problems", "measures", "score", "counts"}`
(plan/2026-11-06b §5).

Deterministic, no model. A problem is `{code, sentence, shots, fix, key}`; `fix` says who deals with it: `mend` (code,
in
`jonathan_mend`), `repair` (the reviser is sent exactly this sentence), `drop` (an addition code removes) or `report`
(shown to a person, never sent back). A measure is a craft rule of thumb, `met`, `missed` or `info`: reported, never
blocking. `score` is `[faults, craft gaps]`, lower is better: the stabiliser keeps the plan with the lowest. `ok` is
true
when nothing is left for the reviser. The rules are `contracts.jonathan.checks` and `contracts.jonathan.measures`.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.jonathan import checks, measures
from contracts.jonathan.scene import SceneS
from contracts.jonathan.wire import JonathanWire


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, plan = SceneS.model_validate(payload["scene"]), JonathanWire.model_validate(payload["plan"])
        craft = measures.Craft.model_validate(payload.get("craft") or {})
    except (ValidationError, KeyError) as exc:
        text = str(exc)[:600]
        return {"ok": False, "malformed": text, "problems": [{"code": "shape", "sentence": text, "shots": [],
                                                              "fix": "repair", "key": "shape:malformed"}],
                "measures": [], "score": [99, 99], "counts": {"repair": 1}}
    removed = [(str(r["kind"]), int(r["after_block"])) for r in payload.get("removed") or []]
    found = checks.problems(scene, plan, removed)
    measured = measures.measures(scene, plan, craft)
    counts: dict[str, int] = {}
    for p in found:
        counts[p.fix] = counts.get(p.fix, 0) + 1
    return {"ok": not checks.repairable(found), "problems": [p.model_dump() for p in found],
            "measures": [m.model_dump() for m in measured],
            "score": [len(checks.faults(found)), len(measures.missed(measured))], "counts": counts}
