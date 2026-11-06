"""Conflicts in the production's memory (plan/2026-11-05d M8). Found in code, reported, never resolved silently.

Two kinds:

disagree  two entries on the same topic and the same target from DIFFERENT documents that say different things. One
          document is taken to agree with itself; two documents about the same thing may not. The newest document is
          suggested, a person chooses.
lens, length
          an entry asks for what the system cannot make: a lens the camera panel does not have (`CAMERA_OPTIONS`), or a
          shot or take of a length Veo cannot make (`VEO_DURATIONS`). The entry stays in the memory and is reported, not
          obeyed and not dropped.
"""
from __future__ import annotations

import re
from typing import Any

from contracts.memory import parse_target, topic_key
from contracts.producer import CAMERA_OPTIONS, CameraField
from contracts.veo import VEO_DURATIONS

_LENS = re.compile(r"(?<![\w.])(\d{2,3})\s*mm\b", re.IGNORECASE)
_SECONDS = r"(\d{1,3})(?:\s*|-)(?:s\b|sec\w*)"
_SHOT = r"(?:shot|take|clip)s?"
# "a 10 second shot", "shots of 10 seconds": an exact claim. "under 10 seconds" is a limit, and is left alone.
_LENGTH = (re.compile(rf"{_SECONDS}\s+{_SHOT}\b", re.IGNORECASE),
           re.compile(rf"\b{_SHOT}\s+(?:of|for|lasting)\s+{_SECONDS}", re.IGNORECASE))
_LIMIT_WORDS = re.compile(
    r"\b(under|below|less|than|most|max\w*|within|over|above|more|least|min\w*|up to|no longer)\b", re.IGNORECASE)


def _lenses() -> set[int]:
    return {int(re.sub(r"\D", "", lens)) for lens in CAMERA_OPTIONS[CameraField.LENS]}


def _live(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("status") != "rejected"]


def _tag(entry: dict[str, Any]) -> str:
    return f"{entry.get('topic')} · {entry.get('applies_to')}: {' '.join(str(entry.get('says') or '').split())}"


def _outside_limits(entry: dict[str, Any]) -> list[dict[str, Any]]:
    says = str(entry.get("says") or "")
    out: list[dict[str, Any]] = []
    have = sorted(_lenses())
    for found in dict.fromkeys(int(m.group(1)) for m in _LENS.finditer(says)):
        if found not in have:
            out.append({"kind": "lens", "ids": [entry.get("id")],
                        "text": f"Production memory asks for a {found}mm lens ({_tag(entry)}), which is not one the "
                                f"camera has ({', '.join(f'{n}mm' for n in have)}). A person decides what to use "
                                "instead."})
    seconds = {int(m.group(1)) for pattern in _LENGTH for m in pattern.finditer(says)
               if not _LIMIT_WORDS.search(says[max(0, m.start() - 20): m.end() + 20])}
    for found in sorted(seconds - set(VEO_DURATIONS)):
        out.append({"kind": "length", "ids": [entry.get("id")],
                    "text": f"Production memory asks for a shot of {found} s ({_tag(entry)}); Veo makes "
                            f"{', '.join(str(d) for d in VEO_DURATIONS[:-1])} or {VEO_DURATIONS[-1]} s."})
    return out


def _disagreements(entries: list[dict[str, Any]], documents: dict[str, str]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in _live(entries):
        target = parse_target(str(entry.get("applies_to") or ""))
        if target is None or not entry.get("document_id"):
            continue  # a person's own entry is a decision, not a document to disagree with
        key = (topic_key(str(entry.get("topic") or "")), f"{target[0]}:{target[1].casefold()}")
        groups.setdefault(key, []).append(entry)
    out: list[dict[str, Any]] = []
    for rows in groups.values():
        by_doc: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_doc.setdefault(str(row["document_id"]), []).append(row)
        if len(by_doc) < 2:
            continue
        sayings = {" ".join(str(r.get("says") or "").lower().split()) for r in rows}
        if len(sayings) < 2:
            continue  # the same direction in two documents agrees
        newest = max(by_doc, key=lambda d: (str(documents.get(d) or ""), d))
        pick = next(r for r in rows if str(r["document_id"]) == newest)
        out.append({"kind": "disagree", "ids": [r.get("id") for r in rows],
                    "text": "Two documents give different direction for the same thing: "
                            + " / ".join(_tag(r) for r in rows)
                            + f". The newer document's entry is suggested ({_tag(pick)}); a person chooses."})
    return out


def find(entries: list[dict[str, Any]], documents: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """-> `[{"kind", "ids", "text"}]`, in the order the entries are given. Rejected entries are not looked at."""
    live = _live(entries)
    found = [c for e in live for c in _outside_limits(e)]
    return found + _disagreements(live, documents or {})
