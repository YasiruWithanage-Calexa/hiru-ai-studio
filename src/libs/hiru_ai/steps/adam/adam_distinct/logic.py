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

from contracts.adam.plan import SIZE_RANK, SceneAnalysis, Treatment, norm

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


# ── choosing one of the three (plan/2026-11-04b §5.5: "a quick score on the treatment alone") ────


def _fit_points(t: Treatment, analysis: SceneAnalysis) -> tuple[int, list[str]]:
    """How well a treatment answers the analysis: who owns the point of view, the turn, the plant, the break, the way
    in and out. One point each; the reasons say which were missed."""
    owner = norm(analysis.pov_owner.start)
    turn_beats = {i for i, b in enumerate(analysis.beats) if b.turn}
    covered = {b for s in t.sections for b in s.beats}
    checks = [
        ("names the point-of-view owner", not owner or owner in norm(t.pov)),
        ("has a section on the turn", not turn_beats or bool(turn_beats & covered)),
        ("plants and pays off", t.plant is None or bool(t.plant.plant_when and (t.plant.payoff_when
                                                                                  or t.plant.payoff_scene))),
        ("has its one rhythm break", t.rhythm_break is not None),
        ("says how it enters and leaves", bool(norm(t.entry) and norm(t.exit) and norm(t.ending_image))),
    ]
    return sum(ok for _, ok in checks), [f"does not: {why}" for why, ok in checks if not ok]


def _sane(t: Treatment, analysis: SceneAnalysis) -> tuple[bool, str]:
    """Not over-directed: an arc far longer than the scene has beats, or a run of extreme close-ups, is a scene stuffed
    with devices."""
    too_long = len(t.size_arc) > 2 * max(1, len(analysis.beats)) + 2
    heavy = sum(1 for s in t.size_arc if s == "ECU") > 2
    return not (too_long or heavy), "over-directed" if too_long or heavy else ""


def choose(treatments: list[Treatment], analysis: SceneAnalysis) -> dict[str, Any]:
    """Picks the treatment that answers the analysis best, differs most from the others and is not over-directed. A tie
    keeps the earlier one (the stances come restrained, intimate, heightened). A person can always pick another."""
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(treatments):
        fit, missed = _fit_points(t, analysis)
        others = [o for j, o in enumerate(treatments) if j != i]
        apart = sum(len(differs_on(t, o)) for o in others) / (len(AXES) * len(others)) if others else 1.0
        sane, why = _sane(t, analysis)
        total = round(fit / 5 + apart + (1.0 if sane else 0.0), 3)
        rows.append({"index": i, "stance": t.stance, "fit": fit, "distinct": round(apart, 2), "sane": sane,
                     "total": total, "why": missed + ([why] if why else [])})
    best = max(rows, key=lambda r: (r["total"], -r["index"])) if rows else None
    return {"index": best["index"] if best else None, "stance": best["stance"] if best else "", "scores": rows}
