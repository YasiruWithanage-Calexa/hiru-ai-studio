"""The scene board as Zora reads it (findings 2026-11-17 C4, C5): is there one, which panels no longer show their shot,
and what a person can press. Zora never paints: the chat offers a card whose button runs Update board (a person
presses it; a board is never repainted by itself, `api/routers/boards.py`).

    view(ctx, scene_id, shot_rows) -> BoardView      read once per turn (no board port → `known` False, says nothing)
    BoardView.sentence()                             the scene board in one sentence, for the conductor and the reply
    card(view, shots, reason)                        the `board` block a message carries, or None

"Board" here is ONLY the scene board, the storyboard picture painted from the shots (not the director's panel of
specialists, `director_board`).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts import board as kit
from hiru_ai.core.context import RunContext

_log = logging.getLogger(__name__)
Row = dict[str, Any]


def code(n: int) -> str:
    return f"S{n:02d}"


@dataclass
class BoardView:
    known: bool = False  # the board could be read
    exists: bool = False  # a current board with at least one finished part
    painting: bool = False
    updatable: bool = False  # Update board can mend it (every part finished, with its cells)
    changed: list[int] = field(default_factory=list)
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    moved: list[int] = field(default_factory=list)
    locked: list[int] = field(default_factory=list)
    on_board: dict[int, str] = field(default_factory=dict)  # shot number → shot id, for the shots a panel shows
    ids: dict[int, str] = field(default_factory=dict)  # shot number → shot id, every shot

    def out_of_date(self) -> list[int]:
        return sorted(set(self.changed) | set(self.added))

    def sentence(self) -> str:
        if not self.known:
            return ""
        if self.painting:
            return "The scene board is being painted right now."
        if not self.exists:
            return "No scene board has been painted for this scene yet (it is painted on the board screen)."
        bits = []
        if self.changed:
            its = "its" if len(self.changed) == 1 else "their"
            bits.append(f"{', '.join(code(n) for n in self.changed)} changed since {its} panel was painted")
        if self.added:
            bits.append(f"{', '.join(code(n) for n in self.added)} {'is' if len(self.added) == 1 else 'are'} not on it")
        if self.removed:
            one = len(self.removed) == 1
            bits.append(f"{len(self.removed)} panel{'' if one else 's'} show{'s' if one else ''} a removed shot")
        if self.moved:
            bits.append("some panels are out of order")
        if self.locked:
            bits.append(f"{', '.join(code(n) for n in self.locked)} {'is' if len(self.locked) == 1 else 'are'} locked "
                        "(left as painted)")
        if not bits:
            return "The scene board is painted and up to date with every shot."
        tail = "" if self.updatable else " Only a whole repaint can mend it (on the board screen)."
        return "The scene board is painted, but " + "; ".join(bits) + "." + tail


def view(ctx: RunContext, scene_id: str, shot_rows: Sequence[Row]) -> BoardView:
    port = ctx.ports.frames
    if port is None:
        return BoardView()
    try:
        rows = port.boards(str(scene_id))
    except Exception:
        _log.warning("the scene board could not be read for Zora", exc_info=True)
        return BoardView()
    ids = {int(s.get("number") or 0): str(s["id"]) for s in shot_rows}
    if not rows:
        return BoardView(known=True, ids=ids)
    top = max(int(r.get("version") or 1) for r in rows)
    parts = sorted((r for r in rows if int(r.get("version") or 1) == top), key=lambda r: int(r.get("part") or 1))
    done = [p for p in parts if p.get("status") == "done"]
    painting = any(p.get("status") in ("queued", "running") for p in parts)
    if not done:
        return BoardView(known=True, painting=painting, ids=ids)
    cells = [c for p in done for c in p.get("cells") or []]
    stale = kit.stale_cells(cells, list(shot_rows))
    seen = {str(c.get("shot_id")) for c in cells}
    return BoardView(known=True, exists=True, painting=painting,
                     updatable=all(p.get("status") == "done" and p.get("cells") for p in parts),
                     changed=sorted(n for n in stale.changed if n not in stale.locked), added=sorted(stale.added),
                     removed=list(stale.removed), moved=list(stale.moved), locked=list(stale.locked),
                     on_board={n: i for n, i in ids.items() if i in seen}, ids=ids)


def card(board: BoardView, numbers: Sequence[int], reason: str) -> Row | None:
    """The block under a message: "Update board" for these shots (their ids, so the button names them to
    `POST …/scenes/{id}/board/update`). None when there is no board to update, or nothing named is on it or new."""
    if not board.exists or not board.updatable or board.painting:
        return None
    wanted = sorted({n for n in numbers if n in board.ids})
    if not wanted:
        return None
    return {"kind": "board", "shots": [code(n) for n in wanted], "shot_ids": [board.ids[n] for n in wanted],
            "reason": reason, "state": ""}
