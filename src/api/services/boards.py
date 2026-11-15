"""The Scene board's rules for the API (plan/2026-11-14 §3.3, §3.5): which rows are the scene's current board, which
panel feeds a shot's first frame, and whether a shot may be painted at all (D3).

  current board   the newest version's parts (a whole repaint makes a new version; repainting some panels changes a
                  part in place and clears its approval)
  a shot's panel  the first part that paints it; it feeds a frame only when that part is done and approved and the
                  panel still shows the shot (`contracts.board.stale_cells`)
  a black plate   needs no board: it is made by code (the same rule as the engine's `World.plate`)
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from contracts import board as kit
from contracts.frame_brief import black_plate

Row = dict[str, Any]

NO_BOARD = "Paint and approve the scene board first: every first frame is painted from its panel."
NOT_APPROVED = "Approve the scene board first: every first frame is painted from its panel."
PAINTING = "The scene board is being painted. Approve it when it is ready."
FAILED = "The scene board could not be painted. Paint it again."
NOT_ON_BOARD = "This shot is not on the scene board (shots were added or moved). Paint the whole board again."
STALE = "This shot changed since its panel was painted. Repaint its panel and approve the board again."


def current(rows: Sequence[Row]) -> list[Row]:
    """The scene's current board: every part of the newest version, in part order."""
    if not rows:
        return []
    top = max(int(r.get("version") or 1) for r in rows)
    return sorted((r for r in rows if int(r.get("version") or 1) == top), key=lambda r: int(r.get("part") or 1))


def next_version(rows: Sequence[Row]) -> int:
    return 1 + max((int(r.get("version") or 1) for r in rows), default=0)


def is_plate(items: Sequence[Any], cast: Sequence[Any]) -> bool:
    """A cut to black or a title card with no one in it (the engine's `World.plate`): made by code, no board."""
    return (not cast and not any(getattr(i, "kind", "") == "dialogue" for i in items)
            and black_plate(str(getattr(i, "text", "") or "") for i in items))


def cells(parts: Sequence[Row]) -> list[Row]:
    """Every cell of the board, in part order (the overlap panel appears twice; its first part owns it)."""
    return [c for p in parts for c in p.get("cells") or []]


def stale(parts: Sequence[Row], shots: Sequence[Row]) -> kit.Stale:
    done = [p for p in parts if p.get("status") == "done"]
    return kit.stale_cells(cells(done), shots) if done else kit.Stale()


@dataclass
class ShotPanel:
    """What the board gives one shot's first frame. `ready`: a frame may be painted (from `board_id`'s panel, or as a
    black plate with no board). `reason` says why not, in words for the shot screen."""

    ready: bool
    reason: str = ""
    plate: bool = False
    board_id: str = ""
    cell: Row | None = None
    state: str = "missing"  # plate | ready | missing | painting | failed | unapproved | stale | absent


def shot_panel(parts: Sequence[Row], shot: Row, *, plate: bool) -> ShotPanel:
    if plate:
        return ShotPanel(ready=True, plate=True, state="plate")
    if not parts:
        return ShotPanel(ready=False, reason=NO_BOARD, state="missing")
    owner = kit.owner_cell(parts, str(shot["id"]))
    if owner is None:
        if any(p.get("status") in ("queued", "running") for p in parts):
            return ShotPanel(ready=False, reason=PAINTING, state="painting")
        if all(p.get("status") in ("failed", "refused") for p in parts):
            return ShotPanel(ready=False, reason=FAILED, state="failed")
        return ShotPanel(ready=False, reason=NOT_ON_BOARD, state="absent")
    part, cell = owner
    if cell.get("kind") == "black":
        return ShotPanel(ready=True, plate=True, state="plate", board_id=str(part["id"]), cell=dict(cell))
    if part.get("status") in ("queued", "running"):
        return ShotPanel(ready=False, reason=PAINTING, state="painting", board_id=str(part["id"]), cell=dict(cell))
    if part.get("status") != "done" or not cell.get("path"):
        return ShotPanel(ready=False, reason=FAILED, state="failed", board_id=str(part["id"]), cell=dict(cell))
    if cell.get("pin") and cell.get("pin") != kit.plan_pin(shot):
        return ShotPanel(ready=False, reason=STALE, state="stale", board_id=str(part["id"]), cell=dict(cell))
    if not part.get("approved_at"):
        return ShotPanel(ready=False, reason=NOT_APPROVED, state="unapproved", board_id=str(part["id"]),
                         cell=dict(cell))
    return ShotPanel(ready=True, state="ready", board_id=str(part["id"]), cell=dict(cell))
