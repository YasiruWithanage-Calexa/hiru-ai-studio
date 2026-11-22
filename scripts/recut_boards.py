"""Re-cut the Scene boards that were cut through their panels (plan/2026-11-22 §3.5). No model call.

    python scripts/recut_boards.py            # DRY RUN: which parts are cut wrong, and their first frames
    python scripts/recut_boards.py --apply    # store the new crops and the redrawn sheet, write each part once

A board part's picture was cut with the grid that was ASKED for; when the image model painted another grid, crops
hold two panels or an empty cell. This re-cuts each `done` part with the cutter of plan/2026-11-22, but only where the
saved cut fails `pictures.cut_problems` and the new one passes it.

Only GRID cells are re-cut: a cell with a `box` that was not painted alone (`source` is not "panel"), at its grid
position (`panel`) in a grid of as many panels as the part's picture was painted with (its prompt: "N photorealistic
film stills"). A panel painted alone by Update board (plan/2026-11-17) is its own picture and is left as it is; a part
can hold both.

--apply, per part: the new crops go to FRESH paths (`cell_<NNN>-recut-<8 hex>.png`, never over a stored file) with
their `.thumb.webp`; each grid cell's `box` and `path` are replaced and its `pin`, `note`, `locked` and `previous`
are kept (the bad crop is never added to `previous`: an undo must not bring it back); the numbered sheet is redrawn to
a fresh path from every painted cell (panels painted alone included); an approved part loses its approval (D2: its
panels changed, a person looks again); audited as `board.recut`. First frames already painted from a part are only
listed (D3). Re-runnable: a mended part passes the checks, so a second run finds nothing.
"""
from __future__ import annotations

import argparse
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common

from contracts.board import BoardShot
from hiru_ai.core import thumbs
from hiru_ai.systems.frame_render import pictures as pics

Row = dict[str, Any]
FIELDS = "id,production_id,scene_id,version,part,parts,status,prompt,cells,storage_path,sheet_path,approved_at"
_PAINTED_WITH = re.compile(r"(\d+) photorealistic film stills")


class Store(Protocol):
    def get(self, table: str, **params: str) -> list[Row]: ...
    def file(self, bucket: str, path: str) -> bytes: ...
    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None: ...
    def patch(self, table: str, values: Row, **params: str) -> None: ...
    def insert(self, table: str, rows: list[Row] | Row, upsert: bool = False) -> None: ...


@dataclass
class Mend:
    row: Row
    picture: bytes
    boxes: dict[str, pics.Box]  # grid cell's shot id → its new box
    was: list[str]  # why the saved cut is bad
    still: list[str] = field(default_factory=list)  # why the new cut is bad too (then it is not applied)
    frames: list[Row] = field(default_factory=list)


def grid_cells(row: Row) -> list[Row]:
    """The cells cut from the part's picture, by grid position (not the panels painted alone)."""
    cells = [c for c in row.get("cells") or []
             if c.get("panel") and c.get("box") and c.get("source") != "panel" and c.get("kind") == "painted"]
    return sorted(cells, key=lambda c: int(c["panel"]))


def painted_with(row: Row) -> int:
    """How many panels the part's picture was painted with (0 when its prompt does not say)."""
    m = _PAINTED_WITH.search(str(row.get("prompt") or ""))
    return int(m.group(1)) if m else 0


def find(store: Store) -> tuple[list[Mend], int]:
    """→ (the parts whose saved cut is bad, how many parts were skipped: no grid cell left, or no panel count)."""
    out, skipped = [], 0
    for row in store.get("scene_boards", status="eq.done", select=FIELDS, order="created_at.asc"):
        cells, n = grid_cells(row), painted_with(row)
        if not row.get("storage_path"):
            continue
        if not cells or n < max((int(c["panel"]) for c in cells), default=0):
            skipped += 1
            continue
        picture = store.file("frames", str(row["storage_path"]))
        saved = [[int(v) for v in c["box"]] for c in cells]
        was = pics.cut_problems(picture, saved)
        if not was:
            continue
        every = pics.cell_boxes(picture, n)
        boxes = {str(c["shot_id"]): every[int(c["panel"]) - 1] for c in cells}
        m = Mend(row, picture, boxes, was, pics.cut_problems(picture, list(boxes.values())))
        m.frames = store.get("first_frames", board_id=f"eq.{row['id']}", select="id,shot_id,stage,status,accepted_at")
        out.append(m)
    return out, skipped


def _put(store: Store, path: str, data: bytes) -> None:
    store.upload("frames", path, data, "image/png")
    small = thumbs.make(data)
    if small is not None:
        store.upload("frames", thumbs.thumb_path(path), small, thumbs.MIME)


def apply(store: Store, m: Mend, tag: str | None = None) -> Row:
    """Store the new crops and sheet at fresh paths and write the part once. → the fields written."""
    row = m.row
    tag = tag or uuid4().hex[:8]
    base = posixpath.dirname(str(row["storage_path"]))
    crops: dict[str, bytes] = {}
    cells = []
    for c in row.get("cells") or []:
        c = dict(c)
        sid = str(c.get("shot_id"))
        box = m.boxes.get(sid)
        if box is not None:
            data = pics.crop(m.picture, box)
            path = f"{base}/cell_{int(c['number']):03d}-recut-{tag}.png"
            _put(store, path, data)
            crops[sid] = data
            c.update(box=list(box), path=path)
        elif c.get("kind") == "painted" and c.get("path"):  # a panel painted alone: on the sheet as it is
            crops[sid] = store.file("frames", str(c["path"]))
        cells.append(c)
    shots = [BoardShot(id=str(c["shot_id"]), number=int(c["number"]), slate="", painted=c.get("kind") == "painted",
                       text=str(c.get("text") or "")) for c in cells]
    sheet = f"{base}/sheet-recut-{tag}.png"
    _put(store, sheet, pics.scene_sheet(shots, crops))
    fields: Row = {"cells": cells, "sheet_path": sheet}
    if row.get("approved_at"):
        fields.update(approved_at=None, approved_by=None)
    store.patch("scene_boards", fields, id=f"eq.{row['id']}")
    store.insert("audit_log", {
        "action": "board.recut", "entity": "scene_board", "entity_id": str(row["id"]),
        "production_id": str(row["production_id"]), "actor_user_id": None, "actor_agent": "recut_boards",
        "diff": {"shots": sorted(int(c["number"]) for c in cells if str(c["shot_id"]) in m.boxes), "was": m.was,
                 "approval_cleared": bool(row.get("approved_at")), "first_frames": [f["id"] for f in m.frames]}})
    return fields


class RestStore:
    """`_common.Rest` with the two calls this script needs that it lacks: a file read and a PATCH."""

    def __init__(self, rest: _common.Rest) -> None:
        self.rest = rest

    def get(self, table: str, **params: str) -> list[Row]:
        return self.rest.get(table, **params)

    def file(self, bucket: str, path: str) -> bytes:
        r = self.rest.c.get(f"{self.rest.storage}/object/{bucket}/{path}", headers=self.rest.h)
        r.raise_for_status()
        return r.content

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        self.rest.upload(bucket, path, data, content_type)

    def patch(self, table: str, values: Row, **params: str) -> None:
        r = self.rest.c.patch(f"{self.rest.rest}/{table}", headers=self.rest.h, params=params, json=values)
        r.raise_for_status()

    def insert(self, table: str, rows: list[Row] | Row, upsert: bool = False) -> None:
        self.rest.insert(table, rows, upsert)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="store the new cuts (default: only list them)")
    args = parser.parse_args()
    _common.load_env()
    store = RestStore(_common.Rest())
    mends, skipped = find(store)
    for m in mends:
        r = m.row
        verdict = "CAN'T MEND: " + "; ".join(m.still) if m.still else "mend"
        print(f"board {r['id']} part {r['part']}/{r['parts']} (scene {r['scene_id']}, "
              f"{'approved' if r.get('approved_at') else 'not approved'}): {verdict}")
        print(f"  saved cut: {'; '.join(m.was)}")
        for f in m.frames:
            print(f"  first frame {f['id']} (shot {f['shot_id']}, {f['stage']}, {f['status']}"
                  f"{', accepted' if f.get('accepted_at') else ''}) was painted from this part")
    ok = [m for m in mends if not m.still]
    print(f"{len(mends)} part(s) cut wrong; {len(ok)} can be mended; "
          f"{skipped} skipped (no grid cell left, or no panel count in the prompt).")
    if not args.apply:
        print("Dry run: nothing written. Run again with --apply to store the new cuts.")
        return
    for m in ok:
        apply(store, m)
        print(f"mended board {m.row['id']} part {m.row['part']}")


if __name__ == "__main__":
    main()
