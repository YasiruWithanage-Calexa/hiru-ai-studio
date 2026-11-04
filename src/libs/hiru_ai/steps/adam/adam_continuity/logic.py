"""Continuity, in code (plan/2026-11-04b §5.3; Arijon, *Grammar of the Film Language*).

* the 180° line: two cards that cut straight from one side of the line between the two main people to the other, with
  no neutral shot (an insert or an extreme wide) between them;
* eyelines and screen direction: two people who talk must sit on opposite sides of the frame, so their eyelines meet;
* a person in two places without a move: the staging puts them in one zone, then another, and no move is written;
* props that change hands without being seen: an object is in one person's hands, then another's (or none), and no
  moment between shows it.

Nothing is repaired. Each issue names where it is and why, so the designer can fix it or a person can see it.
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any

from contracts.adam.plan import Moment, ShotCard, Staging, norm, subject_of

NEUTRAL_SIZES = ("INSERT", "EWS")  # a shot that does not take a side of the line
TALKING = ("single", "ots")  # arrangements that split two people into two frames


@dataclass(frozen=True)
class Issue:
    code: str  # axis_cross | screen_direction | eyeline | teleport | prop_unseen | unknown_moment
    where: str
    message: str


def _neutral(card: ShotCard) -> bool:
    return card.size in NEUTRAL_SIZES


def check_axis(cards: list[ShotCard]) -> list[Issue]:
    out = []
    for a, b in itertools.pairwise(cards):
        if a.axis and b.axis and a.axis != b.axis and not _neutral(a) and not _neutral(b):
            out.append(Issue("axis_cross", f"cards {a.number}-{b.number}",
                             f"the camera is on side {a.axis} of the line, then side {b.axis}, with no neutral shot "
                             "between: the people appear to swap places"))
    return out


def check_screen_direction(cards: list[ShotCard], moments: list[Moment]) -> list[Issue]:
    by_id = {m.id: m for m in moments}
    out = []
    for a, b in itertools.pairwise(cards):
        if a.axis and b.axis and a.axis != b.axis:
            continue  # the axis check owns this pair
        if a.arrangement not in TALKING or b.arrangement not in TALKING or _neutral(a) or _neutral(b):
            continue
        sa, sb = subject_of(a, by_id), subject_of(b, by_id)
        if not sa or not sb or sa == sb:
            continue
        pair = f"cards {a.number}-{b.number}"
        if a.composition.frame_side in ("left", "right") and a.composition.frame_side == b.composition.frame_side:
            out.append(Issue("screen_direction", pair, f"{sa} and {sb} are both on the {a.composition.frame_side} of "
                                                       "the frame: two people who face each other sit on "
                                                       "opposite sides"))
        elif a.eyeline in ("left", "right") and a.eyeline == b.eyeline:
            out.append(Issue("eyeline", pair, f"{sa} and {sb} both look {a.eyeline}: their eyelines do not meet"))
    return out


def check_staging(staging: Staging, moments: list[Moment]) -> list[Issue]:
    order = {m.id: i for i, m in enumerate(moments)}
    out: list[Issue] = []
    for mark in staging.marks:
        if mark.moment not in order:
            out.append(Issue("unknown_moment", f"mark of {mark.who}",
                             f"it names moment {mark.moment!r}, which the plan "
                                                                      "does not have"))
    marks = sorted((mk for mk in staging.marks if mk.moment in order), key=lambda mk: order[mk.moment])
    moves = [(order[mv.moment], norm(mv.who)) for mv in staging.moves if mv.moment in order]
    last: dict[str, tuple[int, str]] = {}
    for mk in marks:
        who, here = norm(mk.who), order[mk.moment]
        if who in last and last[who][1] != mk.zone:
            before = last[who][0]
            if not any(w == who and before < i <= here for i, w in moves):
                out.append(Issue("teleport", f"{mk.who} at {mk.moment}",
                                 f"{mk.who} is in {last[who][1]!r}, then in {mk.zone!r}, and no move is written "
                                 "between (add the move, or keep them in one place)"))
        last[who] = (here, mk.zone)
    return out


def check_props(staging: Staging, moments: list[Moment]) -> list[Issue]:
    """An object's holder (a person, or nobody) may change only across a moment that shows that object."""
    order = {m.id: i for i, m in enumerate(moments)}
    seen_at: dict[str, list[int]] = {}
    for i, m in enumerate(moments):
        for obj in m.objects:
            seen_at.setdefault(norm(obj), []).append(i)
    holders: dict[str, dict[int, set[str]]] = {}  # object → moment index → who holds it then
    people: dict[int, set[str]] = {}
    for mk in staging.marks:
        if mk.moment in order:
            people.setdefault(order[mk.moment], set()).add(norm(mk.who))
    objects = {norm(o) for mk in staging.marks for o in mk.holding}
    for mk in staging.marks:
        if mk.moment not in order:
            continue
        for obj in objects:
            holders.setdefault(obj, {}).setdefault(order[mk.moment], set())
            if obj in {norm(o) for o in mk.holding}:
                holders[obj][order[mk.moment]].add(norm(mk.who))
    out = []
    for obj, by_moment in sorted(holders.items()):
        points = sorted(by_moment)
        held = {points[0]: by_moment[points[0]]} if points else {}
        for before, now in itertools.pairwise(points):
            # a holder with no mark at `now` (gone off, or simply not staged then) still has the object
            held[now] = by_moment[now] | {h for h in held[before] if h not in people.get(now, set())}
            if held[before] == held[now]:
                continue
            if not any(before < k <= now for k in seen_at.get(obj, [])):
                out.append(Issue("prop_unseen", f"the {obj}, {moments[before].id} to {moments[now].id}",
                                 f"the {obj} changes hands ({_who(held[before])} to {_who(held[now])}) "
                                 "and no "
                                 "moment between shows it: show the hand-over, or keep it in one place"))
    return out


def _who(holders: set[str]) -> str:
    return " and ".join(sorted(holders)) or "nobody"


def check(cards: list[ShotCard], moments: list[Moment], staging: Staging) -> dict[str, Any]:
    issues = check_axis(cards) + check_screen_direction(cards, moments) + check_staging(staging, moments) \
        + check_props(staging, moments)
    return {"ok": not issues, "issues": [asdict(i) for i in issues], "count": len(issues)}
