"""adam_split: a crowded card is repaired in code, never by deleting what is on it (plan/2026-11-04c §4 F4).

    {"scene": SceneScript, "moments": [Moment], "cards": [ShotCard], "treatment"?: Treatment}     (or "plan": AdamPlan)
        → {"cards": [ShotCard], "changed": bool,
           "splits": [{"card": old number, "into": [new numbers], "at": [first moment of each later part],
                       "takes": [seconds], "how": "lengthened" | "split"}],
           "unsplit": [{"card", "why"}], "renumbered": {old number: its first new number}}

A card that holds more than its take can show is first given the shortest longer take that holds it (4, 6 or 8). One
that needs more than 8 s is split at a moment boundary into takes of 4, 6 or 8 s by the Veo clock: the later parts copy
the first's camera fields and cut in on a look or an action. A line stays with the moment that says it, so none is
trimmed or split. The plan that enters screening has no overrun that code could repair, which means deleting a moment
is never the cheap way out of one. A moment that alone needs more than 8 s cannot be split: it stays, and `adam_fit`
reports it.
Deterministic, no model.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import CutIn, Moment, ShotCard, cards_of, errors_of, moments_of, norm, part_of
from contracts.veo import VEO_DURATIONS
from hiru_ai.core import parts

MAX_PARTS = 4  # a card is never cut into more takes than this; past it the overrun is reported


def _fit(scene: Any, moments: list[Moment], card: ShotCard) -> dict[str, Any]:
    return dict(parts.module("step", "adam_fit", "step").run(
        {"scene": scene, "moments": [m.model_dump(mode="json", by_alias=True) for m in moments],
         "cards": [card.model_dump(mode="json", by_alias=True)]}))


def settle(scene: Any, moments: list[Moment], card: ShotCard) -> ShotCard | None:
    """The card with the shortest take (4, 6 or 8) that holds what is on it, or None when no take does."""
    for take in VEO_DURATIONS:
        trial = card.model_copy(update={"take_s": take, "use_s": None, "in_s": 0.0})
        if _fit(scene, moments, trial)["overruns"] == 0:
            return trial
    return None


def _part(card: ShotCard, ids: list[str], by_id: dict[str, Moment], *, first: bool, last: bool,
          break_moment: str) -> ShotCard:
    """One part of a split card: its moments and the lines they say; the first's camera, and a cut that has a motive."""
    said = {ln for i in ids for ln in by_id[i].lines}
    update: dict[str, Any] = {
        "moments": ids, "lines": [cl for cl in card.lines if cl.line_id in said], "use_s": None, "in_s": 0.0,
        "rhythm_break": card.rhythm_break and (break_moment in ids if break_moment else first),
        "sound": card.sound.model_copy(update={"pre_lap": card.sound.pre_lap if first else "",
                                               "carries_over": card.sound.carries_over if last else ""})}
    if not first:
        who = by_id[ids[0]].who
        keeps = norm(card.subject) in {norm(w) for w in who}
        on = card.subject if keeps else (who[0] if who else "")
        update.update(beats=[], subject=on, cut_in=CutIn(link="cut", motive="action" if keeps else "look"))
    return card.model_copy(update=update)


def _cut(scene: Any, moments: list[Moment], card: ShotCard, break_moment: str, depth: int = 1) -> list[ShotCard] | None:
    """The card as takes that each hold what is on them, or None. The cut that keeps the parts most even wins; when no
    two-way cut works, the longest first part that holds goes and the rest is cut again."""
    by_id = {m.id: m for m in moments}
    ids = [i for i in card.moments if i in by_id]
    if len(ids) < 2 or depth >= MAX_PARTS:
        return None
    found: list[tuple[float, int, list[ShotCard]]] = []
    longest: tuple[int, ShotCard] | None = None
    for k in range(1, len(ids)):
        head = settle(scene, moments, _part(card, ids[:k], by_id, first=True, last=False, break_moment=break_moment))
        if head is None:
            break  # a longer first part only gets longer
        longest = (k, head)
        tail = settle(scene, moments, _part(card, ids[k:], by_id, first=False, last=True, break_moment=break_moment))
        if tail is not None:
            found.append((abs(head.take_s - tail.take_s), k, [head, tail]))
    if found:
        return min(found, key=lambda f: (f[0], f[1]))[2]
    if longest is None:
        return None
    k, head = longest
    rest = _part(card, ids[k:], by_id, first=False, last=True, break_moment=break_moment)
    more = _cut(scene, moments, rest, break_moment, depth + 1)
    return [head, *more] if more else None


def repair(scene: Any, moments: list[Moment], cards: list[ShotCard], break_moment: str = "") -> dict[str, Any]:
    out: list[ShotCard] = []
    splits: list[dict[str, Any]] = []
    unsplit: list[dict[str, Any]] = []
    renumbered: dict[int, int] = {}
    by_id = {m.id: m for m in moments}
    for card in cards:
        renumbered[card.number] = len(out) + 1
        if _fit(scene, moments, card)["overruns"] == 0:
            out.append(card)
            continue
        longer = settle(scene, moments, card)
        if longer is not None:  # a longer take holds it: nothing is cut
            splits.append({"card": card.number, "into": [len(out) + 1], "at": [], "takes": [longer.take_s],
                           "how": "lengthened"})
            out.append(longer)
            continue
        cut = _cut(scene, moments, card, break_moment)
        if cut is None:
            need = max((m.seconds_need for m in (by_id.get(i) for i in card.moments) if m), default=0.0)
            unsplit.append({"card": card.number, "why": f"no way to cut it into takes that hold what is on it "
                                                        f"(the longest moment asks {need:g} s)"})
            out.append(card)
            continue
        into = list(range(len(out) + 1, len(out) + 1 + len(cut)))
        splits.append({"card": card.number, "into": into, "at": [c.moments[0] for c in cut[1:]],
                       "takes": [c.take_s for c in cut], "how": "split"})
        out += cut
    numbered = [c.model_copy(update={"number": i}) for i, c in enumerate(out, start=1)]
    return {"cards": [c.model_dump(mode="json", by_alias=True) for c in numbered], "changed": bool(splits),
            "splits": splits, "unsplit": unsplit, "renumbered": renumbered}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        moments, cards = moments_of(payload), cards_of(payload)
        treatment = part_of(payload, "treatment") or {}
        scene = payload.get("scene")
    except ValidationError as exc:
        return {"cards": [], "changed": False, "splits": [], "unsplit": [], "renumbered": {},
                "malformed": errors_of(exc)}
    brk = (treatment.get("rhythm_break") or {}).get("moment", "") if isinstance(treatment, dict) else ""
    return repair(scene, moments, cards, str(brk))

