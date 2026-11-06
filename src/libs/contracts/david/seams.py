"""The join between two scenes, and the look changes inside one (plan/2026-11-05e §4.3 `david_seams`, §7 D9).

    seam(before, link, start, after, number)     → [Problem]   scene N's end state against how scene N+1 opens
    look_changes(start, end, number)             → [LookChange] a person's look at the end differs from the start

A `continuous` pair compares place, hands, clothes and light and can be repaired (one repair on the later scene's first
shots). A `carry` pair compares clothes, injuries and a kept prop only. An unlinked pair compares looks only and is
REPORTED, never repaired: a costume change the next scene cannot know about is at least shown.
"""
from __future__ import annotations

import re

from contracts.david.checks import mentions, strings
from contracts.david.plan import Fix, Problem, norm
from contracts.david.stored import LookChange
from contracts.david.wire import DavidWire, EndStateW

_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def similar(a: str, b: str) -> bool:
    """Two descriptions of a look or of light say the same thing, loosely: a third of the smaller one's words are the
    other's. Either one empty = nothing to compare."""
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    if not wa or not wb:
        return True
    return len(wa & wb) / min(len(wa), len(wb)) >= 1 / 3


def look_changes(start: EndStateW | None, end: EndStateW, number: int) -> list[LookChange]:
    """Who looks different at the end of scene `number` than at its start (code works it out; no model field)."""
    if start is None:
        return []
    before = {norm(p.who): p for p in start.people}
    out = []
    for p in end.people:
        was = before.get(norm(p.who))
        if was is not None and was.look.strip() and p.look.strip() and not similar(was.look, p.look):
            out.append(LookChange(who=p.who, scene=number, before=was.look.strip(), after=p.look.strip()))
    return out


def opening(plan: DavidWire, who: str) -> tuple[str, str, str]:
    """(zone, holding, how the scene first describes them) for `who`: their first mark, and the subjects of the first
    shot
    that shows them."""
    marks = sorted((m for m in plan.staging.marks if norm(m.who) == norm(who)), key=lambda m: m.block)
    zone, holding = (marks[0].zone, marks[0].holding) if marks else ("", "")
    for s in plan.shots:  # the first shot that shows them: how the scene opens on them
        found = [" ".join(strings(subject)) for subject in s.ir.get("subjects") or []]
        found = [text for text in found if mentions(text, who)]
        if found:
            return zone, holding, " ".join(found)
    return zone, holding, ""


def seam(before: EndStateW, link: str, start: EndStateW | None, after: DavidWire, number: int) -> list[Problem]:
    """Scene `number - 1`'s end state against how scene `number` opens (`after`) and what it was planned from (`start`:
    the end state before it for a chain, canon looks otherwise)."""
    out: list[Problem] = []
    fix: Fix = "repair" if link else "report"
    prior = number - 1
    now = {norm(p.who): p for p in (start.people if start else [])}
    for p in before.people:
        key = norm(p.who)
        zone, holding, described = opening(after, p.who)
        if link == "continuous":
            if zone and zone != "off" and norm(p.where) and norm(zone) not in norm(p.where) \
                    and norm(p.where) not in norm(zone):
                out.append(Problem(code="seam", sentence=f"Scene {number} opens with {p.who} at the {zone}, but scene "
                                   f"{prior} ended with {p.who} at \"{p.where}\" and nothing shows the move.",
                                   fix=fix, key=f"seam:where:{key}"))
            if norm(p.holding) and zone and norm(p.holding) not in norm(holding):
                out.append(Problem(code="seam", sentence=f"Scene {prior} ends with {p.who} holding {p.holding}; "
                                   f"scene {number} opens with {p.who} holding "
                                   f"{holding or 'nothing'}.", fix=fix, key=f"seam:holding:{key}"))
        if link in ("continuous", "carry") and described and not similar(p.look, described):
            out.append(Problem(code="seam", sentence=f"Scene {prior} ends with {p.who} in \"{p.look}\"; scene "
                               f"{number}'s first shots describe {p.who} as \"{described[:120]}\".", fix=fix,
                               key=f"seam:look:{key}"))
        if link == "" or start is not None:
            was = now.get(key)
            if was is not None and not similar(p.look, was.look):
                out.append(Problem(code="seam", sentence=f"Scene {prior} ends with {p.who} in \"{p.look}\"; scene "
                                   f"{number} starts from \"{was.look}\", and no change is shown.",
                                   fix="report", key=f"seam:start:{key}"))
    if link == "continuous" and after.shots:
        light = " ".join(strings(after.shots[0].ir.get("lighting")))
        if before.light.strip() and not similar(before.light, light):
            out.append(Problem(code="seam", sentence=f"Scene {prior} ends in \"{before.light}\"; scene {number} opens "
                               f"in \"{light[:120]}\".", fix=fix, key="seam:light"))
    return out
