"""note_merge: `{"critics": [{"acceptable": false, "notes": [{"note": "...", "severity": 1}]}, ...], "limit": 6}` → the
notes to act on, in order. A critic that failed is `null` and left out; if every one failed the step says so."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.note_merge.logic import MAX_NOTES, merge_notes, notes_of


def run(payload: dict[str, Any]) -> dict[str, Any]:
    critics = list(payload.get("critics") or [])
    if critics and all(c is None for c in critics):
        return {"notes": [], "all_failed": True}
    rounds = [notes_of(c) if c is not None else [] for c in critics]
    return {"notes": merge_notes(rounds, int(payload.get("limit") or MAX_NOTES)), "all_failed": False}
