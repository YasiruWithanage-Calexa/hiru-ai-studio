"""adam_distinct: the three treatments of a scene must differ on purpose (plan/2026-11-04b §10 Phase 3 exit).

Three treatments that say the same thing in three voices are one idea and cost three calls. A pair differs on an
AXIS when:

* size arc: the largest size either reaches differs, or at least half of the arc's places differ (an arc that is
  longer or shorter counts the missing places as different);
* point of view: the words of the two `pov` lines overlap by no more than `SAME_ABOVE` (Jaccard on lower-case words);
* sound concept: the same, on `sound_concept`.

Every pair must differ on at least `MIN_AXES` of the three, and the names (and stances, when given) must all be
different. A treatment with an axis left empty cannot differ on it: the axis counts as the same.
"""
from __future__ import annotations

import itertools
import re
from typing import Any

from contracts.adam.plan import SIZE_RANK, Treatment, norm

AXES: tuple[str, ...] = ("size_arc", "pov", "sound_concept")
MIN_AXES = 2
SAME_ABOVE = 0.6  # two descriptions that share more than this fraction of their words say the same thing
ARC_SHARE = 0.5  # an arc differs when at least this share of its places differ

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


def _words(text: str) -> set[str]:
    return set(_WORDS.findall(text.lower()))


def words_differ(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False  # nothing said: it cannot differ
    return len(wa & wb) / len(wa | wb) <= SAME_ABOVE


def arcs_differ(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    if max(SIZE_RANK.get(s, -1) for s in a) != max(SIZE_RANK.get(s, -1) for s in b):
        return True
    places = max(len(a), len(b))
    apart = sum(1 for i in range(places) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None))
    return apart / places >= ARC_SHARE


def differs_on(a: Treatment, b: Treatment) -> list[str]:
    found: list[str] = []
    if arcs_differ(list(a.size_arc), list(b.size_arc)):
        found.append("size_arc")
    if words_differ(a.pov, b.pov):
        found.append("pov")
    if words_differ(a.sound_concept, b.sound_concept):
        found.append("sound_concept")
    return found


def check(treatments: list[Treatment], expected: int = 3) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if len(treatments) != expected:
        issues.append({"code": "count", "where": "the treatments",
                       "message": f"{len(treatments)} treatments, {expected} wanted"})
    pairs: list[dict[str, Any]] = []
    for (i, a), (j, b) in itertools.combinations(enumerate(treatments, start=1), 2):
        found = differs_on(a, b)
        pairs.append({"a": i, "b": j, "differs": found, "same": [x for x in AXES if x not in found]})
        where = f"treatments {i} and {j}"
        if len(found) < MIN_AXES:
            issues.append({"code": "alike", "where": where,
                           "message": f"differ on {found or 'nothing'}; they must differ on at least {MIN_AXES} of "
                                      f"{list(AXES)}"})
        if norm(a.name) == norm(b.name):
            issues.append({"code": "same_name", "where": where, "message": f"both are called {a.name!r}"})
        if a.stance and norm(a.stance) == norm(b.stance):
            issues.append({"code": "same_stance", "where": where, "message": f"both play it {a.stance!r}"})
    return {"ok": not issues, "count": len(issues), "issues": issues, "pairs": pairs}
