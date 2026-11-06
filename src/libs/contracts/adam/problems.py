"""A problem the fixer ladder is asked to fix, and how a plan's problems are told apart (plan/2026-11-05 T3).

A fault code finds in a plan (a face not seen, an overrun, a continuity break, something Veo renders badly) and a HIGH
note a critic wrote are both a PROBLEM: one thing wrong, in words, with the card it is about. Problems are sorted by
KIND, and each kind starts on its own rung of the ladder (code, then a small model, then a bigger one;
`adam/fixer.yaml`):

    mechanical   code can mend it with no judgement: a line no card binds, a line on a card that does not show its
    moment
    local        one card or its neighbours need a change: a face not yet seen, a crowded card, a note on one card
    creative     a moment must be imagined: a baseline, a subtext or an irony the plan never shows, a new picture a note
    asks for

A problem does not decide anything about the story: a fixer answers it with the reviser's operations and code checks the
whole plan again (`adam_fidelity`, `adam_fit`, `adam_coverage`, `adam_score`). Pure standard library + pydantic (the
`contracts` rule).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.adam.screening import Severity

ProblemKind = Literal["mechanical", "local", "creative"]
PROBLEM_KINDS: tuple[str, ...] = ("mechanical", "local", "creative")
# A coverage cell of these kinds can only be filled by a picture the plan does not have: a new moment must be imagined.
CREATIVE_CELLS: tuple[str, ...] = ("baseline", "subtext", "irony", "plant")
MAX_PROBLEMS = 6  # what one scene's ladder works on; the rest are reported (plan/2026-11-05 T3 rule 3)


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str  # p1, p2 ...: the fixer answers a problem by its id, as the reviser answers a note
    kind: ProblemKind
    source: Literal["code", "note"]
    code: str = ""  # the code's name for it ("hole:stake:dasun:before", "line_overrun"); empty for a note
    card: int = 0  # the card it is about; 0 = the scene as a whole
    cell: str = ""  # the coverage cell it would fill, or the kind of moment a note asks for; else ""
    severity: Severity = "high"
    note_id: str = ""  # a critic's note (n3) this problem is, so the notes ledger answers it
    note_kind: str = ""  # that note's kind: add, remove, change or risk
    text: str  # what is wrong and what would answer it, in a sentence or two


def cell_kind(cell: str) -> str:
    """The kind of a coverage cell id ("stake:dasun:before" -> "stake"); a moment kind is its own kind."""
    return cell.split(":", 1)[0]


def kind_of_hole(cell: str) -> ProblemKind:
    """A face the plan never shows by its own picture is creative; a face that only needs a card is local."""
    return "creative" if cell_kind(cell) in CREATIVE_CELLS else "local"


def kind_of_note(note_kind: str, cell: str, cells: set[str]) -> ProblemKind:
    """An `add` note naming a coverage cell asks for a card; naming a moment kind asks for a picture to be imagined. Any
    other note changes or removes what is there."""
    if note_kind == "add":
        return "local" if cell in cells else "creative"
    return "local"


def problem_line(p: Problem) -> str:
    """A problem as the fixer reads it."""
    where = f"card {p.card}" if p.card else "the scene"
    aim = f" -> {p.cell}" if p.cell else ""
    return f"{p.id} [{p.kind}, {p.source}{aim}] {where}: {p.text.strip()}"
