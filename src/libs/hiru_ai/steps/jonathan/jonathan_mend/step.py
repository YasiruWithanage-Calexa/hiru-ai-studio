"""jonathan_mend: `{"scene", "plan", "removed"?}` → `{"plan", "mended", "dropped"}` (plan/2026-11-05e §4.3).

Deterministic, no model. Never a deletion of the script and never a trimmed line: a shot gets the shortest take that
holds it, or is cut at a block boundary with a line kept whole; speech is taken out of free text; an addition the checks
refuse is dropped and listed in `dropped`. The rules are `contracts.jonathan.mend`.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.jonathan import mend
from contracts.jonathan.scene import SceneS
from contracts.jonathan.wire import JonathanWire


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, plan = SceneS.model_validate(payload["scene"]), JonathanWire.model_validate(payload["plan"])
    except (ValidationError, KeyError) as exc:
        return {"malformed": str(exc)[:600]}
    removed = [(str(r["kind"]), int(r["after_block"])) for r in payload.get("removed") or []]
    mended, done, dropped = mend.mend(scene, plan, removed)
    return {"plan": mended.model_dump(mode="json"), "mended": done, "dropped": [p.model_dump() for p in dropped]}
