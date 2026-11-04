"""verbatim_check: `{"op": {...}, "written": "everything the person typed"}` → `{"ok": bool}`."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.verbatim_check.logic import flat, verbatim, words


def check(op: dict[str, Any], written: str) -> bool:
    """Is every word of the operation the person's own, given everything they wrote?"""
    return verbatim(op, flat(written), set(words(written)))


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": check(payload.get("op") or {}, str(payload.get("written") or ""))}
