"""The coverage grid (plan/2026-11-04c §4 F2): which faces the viewer must see, and on which beats.

A script supervisor's lined script shows at a glance whether the reaction was shot. This is that page for a plan: rows
are the beats, columns the people present, and a cell is filled when a card on that beat shows that person's face (the
frame is on them, a line plays over them, or they share a two-shot or a group). Cells are filled from the card's subject
and framing, never from a model's claim that a cell is covered.

The REQUIRED cells come from the analysis, not from the model's own plan:

    turn          the reactor's face while the turn lands
    other         every other person involved, on the turn beat or the one after (Murch's listener)
    irony         the face of whoever does not know what the audience knows, from the block the audience knows it
    subtext       a card whose moment serves the block and shows its behaviour, object or sound
    stake         each person involved, on a card of their own before the break and one after
    baseline, key, plant, ending   as the craft score has always asked

`check` answers `{"cells", "holes", "coverage", "grid"}`; `required` is the same list before any card exists, for the
designer. Pure code, no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from contracts.adam.plan import (
    AdamPlan,
    Moment,
    SceneAnalysis,
    SceneScript,
    ShotCard,
    Subtext,
    Treatment,
    norm,
    people_of,
    subject_of,
)

SHARED = ("two", "group")  # arrangements that put several people sharp in one frame
KINDS: tuple[str, ...] = ("turn", "other", "irony", "subtext", "stake", "baseline", "key", "plant", "ending")
_WORD = re.compile(r"[^\W\d_]{4,}")
# A speaker marked as a voice is heard, never seen: "Father (on the phone)", "Narrator (V.O.)", "Mother (off)".
_VOICE = re.compile(r"\((?=[^)]*(?:phone|voice|v\.?o\.?|o\.?s\.?|off|narrat|radio|tv|recording|speaker))[^)]*\)",
                    re.IGNORECASE)


@dataclass
class Cell:
    id: str
    kind: str
    who: str
    blocks: list[int]
    why: str  # what the cell asks of the plan, in words a person reads
    ok: bool = False
    card: int | None = None  # the card that fills it, or the card nearest to it
    suggest: str = ""

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "who": self.who, "blocks": self.blocks, "why": self.why,
                "ok": self.ok, "card": self.card}


def involved(scene: SceneScript) -> list[tuple[str, set[int]]]:
    """The people of the cast who speak or are named in the action, with the blocks where they do. A voice that is only
    heard (on the phone, off screen) has no face to cover."""
    out = []
    for name in scene.cast:
        if _VOICE.search(name):
            continue
        key = norm(name)
        where = {b.index for b in scene.blocks if norm(b.speaker) == key or (key and key in norm(b.text))}
        if where:
            out.append((name, where))
    return out


def _words(*texts: str) -> set[str]:
    return {w.lower() for t in texts for w in _WORD.findall(t)}


class Grid:
    """The plan, indexed once for every cell."""

    def __init__(self, scene: SceneScript, analysis: SceneAnalysis, treatment: Treatment, moments: list[Moment],
                 cards: list[ShotCard]) -> None:
        self.scene, self.analysis, self.treatment = scene, analysis, treatment
        self.moments, self.cards = moments, cards
        self.by_id = {m.id: m for m in moments}
        self.card_of = {mid: c for c in cards for mid in c.moments}

    def subject(self, card: ShotCard) -> str:
        return subject_of(card, self.by_id)

    def blocks(self, card: ShotCard) -> set[int]:
        """The blocks a card is about. A plant serves the block where it pays off, not the one it is seeded in, so it is
        not counted unless it is all the card holds."""
        held = [m for ident in card.moments if (m := self.by_id.get(ident))]
        return {b for m in held if m.kind != "plant" or all(x.kind == "plant" for x in held) for b in m.blocks}

    def faces(self, card: ShotCard) -> set[str]:
        """Whose face the card shows. An insert shows a thing, never a face."""
        if card.size == "INSERT":
            return set()
        out = {self.subject(card)} - {""}
        out |= {norm(cl.over_whom) for cl in card.lines if not cl.on_speaker and cl.over_whom}
        if card.arrangement in SHARED:
            out |= people_of(card, self.by_id)
        return out

    def own(self, card: ShotCard) -> str:
        """The person a card is OF: the frame is on them (a single, an over-the-shoulder). Empty for an insert."""
        return "" if card.size == "INSERT" else self.subject(card)

    def on(self, blocks: set[int]) -> list[ShotCard]:
        return [c for c in self.cards if self.blocks(c) & blocks]

    def beat_blocks(self, index: int) -> set[int]:
        beats = self.analysis.beats
        return set(beats[index].blocks) if 0 <= index < len(beats) else set()


def required(scene: SceneScript, analysis: SceneAnalysis, treatment: Treatment) -> list[Cell]:
    """Every cell the plan must fill, from the analysis, the treatment and the script alone."""
    cells: list[Cell] = []
    people = involved(scene)
    named = {norm(n): n for n, _ in people}

    def turn_cells() -> None:
        for i, beat in enumerate(analysis.beats):
            if not beat.turn:
                continue
            reactor = beat.reactor or analysis.pov_owner.start
            cells.append(Cell(f"turn:{i}", "turn", reactor, list(beat.blocks),
                              f"{reactor}'s face is seen while the turn at block {_span(beat.blocks)} lands"))
            for name, _ in people:
                if norm(name) != norm(reactor):
                    cells.append(Cell(f"other:{i}:{norm(name)}", "other", name, list(beat.blocks),
                                      f"{name}'s face is seen at the turn (block {_span(beat.blocks)}) or just after"))

    turn_cells()
    for k, kn in enumerate(analysis.audience_knows):
        who = named.get(norm(kn.who_doesnt))
        if who:
            cells.append(Cell(f"irony:{k}", "irony", who, [kn.from_block],
                              f"{who}'s face is seen from block {kn.from_block}, while the audience knows what "
                              f"{who} does not ({kn.fact})"))
    for k, sub in enumerate(analysis.subtext):
        cells.append(Cell(f"subtext:{k}", "subtext", sub.who, [sub.block],
                          f"block {sub.block}'s subtext is shown: {_subtext_words(sub)}"))
    brk = analysis.break_.block
    for name, where in people:
        if brk is None:
            cells.append(Cell(f"stake:{norm(name)}", "stake", name, sorted(where),
                              f"{name} has a card of their own"))
            continue
        if any(b < brk for b in where):
            cells.append(Cell(f"stake:{norm(name)}:before", "stake", name, sorted(b for b in where if b < brk),
                              f"{name} has a card of their own before the break (block {brk})"))
        if any(b >= brk for b in where):
            cells.append(Cell(f"stake:{norm(name)}:after", "stake", name, sorted(b for b in where if b >= brk),
                              f"{name} has a card of their own from the break (block {brk}) on"))
    if analysis.baseline.blocks:
        cells.append(Cell("baseline", "baseline", "", list(analysis.baseline.blocks),
                          "the state before the break has a moment of its own"))
    if treatment.rhythm_break is not None:
        cells.append(Cell("key", "key", "", [analysis.key_moment.block],
                          f"the key moment (block {analysis.key_moment.block}) is the card marked as the break"))
    if treatment.plant is not None:
        cells.append(Cell("plant", "plant", "", [], f"the {treatment.plant.object} is planted and pays off"))
    if treatment.ending_moment:
        cells.append(Cell("ending", "ending", "", [], "the last card is the treatment's ending image"))
    return cells


def _span(blocks: list[int]) -> str:
    return f"{min(blocks)}-{max(blocks)}" if len(blocks) > 1 else str(blocks[0]) if blocks else "?"


def _subtext_words(sub: Subtext) -> str:
    return (sub.behaviour or sub.object or sub.sound or "the subtext").strip()


def fill(cells: list[Cell], g: Grid) -> list[Cell]:
    """Marks each cell filled or not from the cards, and says how to fill a hole."""
    for cell in cells:
        FILLERS[cell.kind](cell, g)
    return cells


def _turn(cell: Cell, g: Grid) -> None:
    holders = g.on(set(cell.blocks))
    shown = [c for c in holders if norm(cell.who) in g.faces(c)]
    near = (shown or holders)[:1]
    cell.ok, cell.card = bool(shown), near[0].number if near else None
    if not cell.ok:
        cell.suggest = f"a card on {cell.who} while the turn lands (blocks {_span(cell.blocks)})"


def _other(cell: Cell, g: Grid) -> None:
    index = int(cell.id.split(":")[1])
    blocks = g.beat_blocks(index) | g.beat_blocks(index + 1)
    shown = [c for c in g.on(blocks) if norm(cell.who) in g.faces(c)]
    cell.ok, cell.card = bool(shown), shown[0].number if shown else None
    if not cell.ok:
        cell.suggest = f"{cell.who}'s face at the turn or the beat after it: a listener or a reaction card"


def _irony(cell: Cell, g: Grid) -> None:
    start = cell.blocks[0]
    shown = [c for c in g.cards if g.blocks(c) and max(g.blocks(c)) >= start and norm(cell.who) in g.faces(c)]
    cell.ok, cell.card = bool(shown), shown[0].number if shown else None
    if not cell.ok:
        cell.suggest = f"{cell.who}'s unknowing face on a card from block {start}"


def _subtext(cell: Cell, g: Grid) -> None:
    sub = g.analysis.subtext[int(cell.id.split(":")[1])]
    want = _words(sub.behaviour, sub.object, sub.sound)
    for card in g.cards:
        for ident in card.moments:
            m = g.by_id.get(ident)
            if m and sub.block in m.blocks and want & _words(m.seen, m.heard, " ".join(m.objects)):
                cell.ok, cell.card = True, card.number
                return
    held = g.on({sub.block})
    cell.card = held[0].number if held else None
    cell.suggest = f"a moment on block {sub.block} that shows: {_subtext_words(sub)}"


def _stake(cell: Cell, g: Grid) -> None:
    brk = g.analysis.break_.block
    side = cell.id.rsplit(":", 1)[-1]
    mine = [c for c in g.cards if g.blocks(c) and norm(g.own(c)) == norm(cell.who)]
    if brk is not None and side == "before":
        mine = [c for c in mine if min(g.blocks(c)) < brk]
    elif brk is not None and side == "after":
        mine = [c for c in mine if max(g.blocks(c)) >= brk]
    cell.ok, cell.card = bool(mine), mine[0].number if mine else None
    if not cell.ok:
        cell.suggest = f"a single or over-the-shoulder card on {cell.who}" + (
            f" {'before' if side == 'before' else 'after'} the break" if brk is not None else "")


def _baseline(cell: Cell, g: Grid) -> None:
    base = set(g.analysis.baseline.blocks)
    own = [c for c in g.cards if g.blocks(c) and g.blocks(c) <= base]
    added = [c for c in g.cards if any(g.by_id[m].kind == "baseline" for m in c.moments if m in g.by_id)]
    hit = added or own
    cell.ok, cell.card = bool(hit), hit[0].number if hit else None
    if not cell.ok:
        cell.suggest = "a baseline moment: the state before the break, shown"


def _key(cell: Cell, g: Grid) -> None:
    """The treatment's break moment is in a card marked as the break, and it sits on the key moment's block."""
    key = cell.blocks[0]
    rb = g.treatment.rhythm_break
    moment = g.by_id.get(rb.moment) if rb else None
    card = g.card_of.get(rb.moment) if rb else None
    cell.ok = bool(card and card.rhythm_break and moment and key in moment.blocks)
    holders = [c for c in g.cards if key in g.blocks(c)]
    near = [card] if card else holders[:1]
    cell.card = near[0].number if near else None
    if not cell.ok:
        cell.suggest = f"the card that holds the break moment, on block {key}, marked as the rhythm break"


def _plant(cell: Cell, g: Grid) -> None:
    plant = g.treatment.plant
    assert plant is not None
    seeded = g.card_of.get(plant.plant_moment)
    paid = g.card_of.get(plant.payoff_moment) if plant.payoff_moment else None
    later = seeded is not None and (
        (paid is not None and g.cards.index(paid) > g.cards.index(seeded))
        or (bool(plant.payoff_scene) and not plant.payoff_moment))
    cell.ok, cell.card = later, seeded.number if seeded else None
    if not cell.ok:
        cell.suggest = f"plant the {plant.object} in a card and pay it off in a later one"


def _ending(cell: Cell, g: Grid) -> None:
    last = g.cards[-1] if g.cards else None
    cell.ok = bool(last and g.treatment.ending_moment in last.moments)
    cell.card = last.number if last else None
    if not cell.ok:
        cell.suggest = "end on the treatment's ending image"


FILLERS = {"turn": _turn, "other": _other, "irony": _irony, "subtext": _subtext, "stake": _stake,
           "baseline": _baseline, "key": _key, "plant": _plant, "ending": _ending}


def check(scene: SceneScript, plan: AdamPlan) -> dict[str, Any]:
    """The grid for a plan: every required cell, which are filled, the holes, and the beats × people page."""
    g = Grid(scene, plan.analysis, plan.treatment, plan.moments, plan.cards)
    cells = fill(required(scene, plan.analysis, plan.treatment), g)
    holes = [{"cell": c.id, "kind": c.kind, "who": c.who, "blocks": c.blocks, "why": c.why, "card": c.card,
              "suggest": c.suggest} for c in cells if not c.ok]
    filled = sum(1 for c in cells if c.ok)
    return {"cells": [c.row() for c in cells], "holes": holes, "required": len(cells), "filled": filled,
            "coverage": round(filled / len(cells), 4) if cells else 1.0, "grid": page(g)}


def page(g: Grid) -> dict[str, Any]:
    """Rows are the beats, columns the people of the cast; each cell lists the cards that show that face on the beat."""
    cast = list(g.scene.cast)
    rows = []
    for i, beat in enumerate(g.analysis.beats):
        here = g.on(set(beat.blocks))
        rows.append({"beat": i, "blocks": list(beat.blocks), "turn": beat.turn,
                     "faces": {name: [c.number for c in here if norm(name) in g.faces(c)] for name in cast}})
    return {"people": cast, "beats": rows}


def lines(cells: list[Cell]) -> list[str]:
    """The required cells as the lines the shot designer is told to meet."""
    return [c.why for c in cells]
