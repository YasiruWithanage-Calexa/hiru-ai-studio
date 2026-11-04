"""A critic's notes, and several critics' notes as one short list. Ported from `script_split/engine/critic.py`
(`_notes`, `merge_notes`) unchanged. Model critics write notes; code decides what is acted on and which plan wins."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MAX_NOTES = 6  # of all the reviewers, for the one re-plan
PER_CRITIC = 4


def notes_of(answer: dict[str, Any]) -> list[tuple[int, str]]:
    """(severity, note) from one reviewer; a plain string is a note of severity 2."""
    if answer.get("acceptable", True):
        return []
    out = []
    for n in (answer.get("notes") or [])[:PER_CRITIC]:
        if isinstance(n, dict):
            text, severity = str(n.get("note") or ""), n.get("severity")
        else:
            text, severity = str(n), 2
        if text.strip():
            out.append((severity if severity in (1, 2, 3) else 2, text.strip()[:300]))
    return out


def merge_notes(rounds: Sequence[Sequence[tuple[int, str]]], limit: int = MAX_NOTES) -> list[str]:
    """The panel's notes as one list: most severe first, each lens in turn on a tie, a repeated note once, at most
    `limit`."""
    ranked = sorted(((sev, lens, text) for lens, notes in enumerate(rounds) for sev, text in notes))
    out: list[str] = []
    for _, _, text in ranked:
        if text.casefold() not in {o.casefold() for o in out}:
            out.append(text)
    return out[:limit]
