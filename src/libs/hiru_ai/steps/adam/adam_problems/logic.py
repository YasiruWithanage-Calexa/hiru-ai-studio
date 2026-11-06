"""What is wrong with a plan, as problems the fixer ladder can take one at a time (plan/2026-11-05 T3), and the faults
code
mends itself (rung 0). Pure code; no model.

`mend` binds a script line to the card that shows its moment: the one fault a rung-0 mend can fix with no judgement (the
take wrote a line on the wrong card, or on none). It moves a line, never changes it, and never adds a moment or a card.
Every other fault goes to `sort`, which names it, tells its kind and puts the cards it concerns beside it.
"""
from __future__ import annotations

import re
from typing import Any

from contracts.adam.plan import CardLine, Moment, SceneScript, ShotCard
from contracts.adam.problems import MAX_PROBLEMS, Problem, kind_of_hole, kind_of_note

# Continuity faults a card can answer; a teleport or a prop that changes hands unseen is the staging's, which no fixer
# operation writes, so it stays in the report for a person.
CARD_CONTINUITY = ("axis_cross", "screen_direction", "eyeline")


def _card_in(where: str) -> int:
    found = re.search(r"\d+", where or "")
    return int(found.group()) if found else 0


def mend(scene: SceneScript, moments: list[Moment], cards: list[ShotCard]) -> tuple[list[ShotCard], list[str]]:
    """Cards with every script line on the card that shows its moment, once. -> (the cards, what was moved).

    A line that no card binds goes to the card of its moment; a line on a card that does not show its moment moves to
    the one that does; a line bound twice keeps its place on the card of its moment. A line whose moment is in no card
    is
    left alone (that is a send-back, not a mend)."""
    carrier = {ln: m.id for m in moments if m.tier == "script" for ln in m.lines}
    home = {m: c.number for c in cards for m in c.moments}
    speaker = {b.line_id: b.speaker for b in scene.lines if b.line_id}
    lines_of = {c.number: list(c.lines) for c in cards}
    said: list[str] = []
    for ln, moment in carrier.items():
        want = home.get(moment)
        if want is None:
            continue
        placed = [n for n, rows in lines_of.items() if any(x.line_id == ln for x in rows)]
        if placed == [want]:
            continue
        keep = next((x for n in placed for x in lines_of[n] if x.line_id == ln), None)
        for n in placed:
            lines_of[n] = [x for x in lines_of[n] if x.line_id != ln]
        lines_of[want].append(keep or CardLine(line_id=ln, on_speaker=True, over_whom=""))
        said.append(f"line {ln} ({speaker.get(ln, '')}) is bound to card {want}, which shows its moment {moment}"
                    + (f" (it was on card {', '.join(map(str, placed))})" if placed else " (no card bound it)"))
    if not said:
        return cards, []
    order = {ln: i for i, ln in enumerate(carrier)}  # script order inside a card
    out = [c.model_copy(update={"lines": sorted(lines_of[c.number], key=lambda x: order.get(x.line_id, 0))})
           for c in cards]
    return out, said


def sort(reports: dict[str, Any], notes: list[dict[str, Any]], *, limit: int = MAX_PROBLEMS) -> dict[str, Any]:
    """The problems of a plan, the ones to work on first, and those left over (reported, not worked on).

    `reports` holds the code steps' answers (`fit`, `coverage`, `continuity`, `feasibility`); `notes` the merged critic
    notes (`adam_notes` "kept"). A high note is a problem; a lower one is not. An `add` note that names a hole's cell is
    that hole's problem (one fix answers both, and the note's id goes on it so the notes ledger answers it)."""
    rows: list[Problem] = []
    cover = reports.get("coverage") or {}
    cells = {str(c["id"]) for c in cover.get("cells") or []}
    by_cell: dict[str, Problem] = {}

    def add(**fields: Any) -> Problem:
        problem = Problem(id=f"p{len(rows) + 1}", **fields)
        rows.append(problem)
        return problem

    for h in cover.get("holes") or []:
        by_cell[str(h["cell"])] = add(kind=kind_of_hole(str(h["cell"])), source="code", code=f"hole:{h['cell']}",
                                      card=int(h.get("card") or 0), cell=str(h["cell"]),
                                      text=f"{h['why']}: give it a card ({h.get('suggest') or 'a single'})")
    for i in (reports.get("fit") or {}).get("issues") or []:
        if i.get("level") == "overrun":
            add(kind="local", source="code", code=str(i["code"]), card=int(i.get("card") or 0),
                text=f"{i['message']} (a line is never trimmed: a longer take, or a moment to a card of its own)")
    for i in (reports.get("continuity") or {}).get("issues") or []:
        if i.get("code") in CARD_CONTINUITY:
            add(kind="local", source="code", code=str(i["code"]), card=_card_in(str(i.get("where"))),
                text=f"{i['message']} ({i['where']})")
    for f in (reports.get("feasibility") or {}).get("flags") or []:
        if not f.get("addressed"):
            add(kind="local", source="code", code=str(f["code"]), card=int(f.get("card") or 0),
                text=f"{f['risk']}: {f['why']}; the known fix: {f['fix']}")
    for n in notes:
        if n.get("severity") != "high":
            continue
        cell = str(n.get("cell") or "")
        mine = by_cell.get(cell) if n.get("kind") == "add" and cell else None
        if mine is not None and not mine.note_id:
            mine.note_id, mine.note_kind = str(n["id"]), str(n["kind"])
            continue
        add(kind=kind_of_note(str(n["kind"]), cell, cells), source="note", code="", card=int(n.get("card") or 0),
            cell=cell, note_id=str(n["id"]), note_kind=str(n["kind"]), text=str(n["note"]))
    return {"problems": [p.model_dump() for p in rows[:limit]], "left": [p.model_dump() for p in rows[limit:]],
            "counts": {k: sum(p.kind == k for p in rows) for k in ("mechanical", "local", "creative")}}
