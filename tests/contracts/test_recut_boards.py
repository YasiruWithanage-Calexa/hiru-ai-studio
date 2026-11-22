"""plan/2026-11-22 phase 4: `scripts/recut_boards.py` against a store in memory. A part cut through its panels is
found, its new crops go to fresh paths, the cell keeps its pin, note, lock and undo history, an approval is cleared, the
first frames are only listed, and a second run finds nothing. Nothing is painted."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from hiru_ai.core import thumbs
from hiru_ai.systems.frame_render import pictures as pics
from tests.contracts.test_board_grid import grid_boxes, sheet

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import recut_boards as recut

Row = dict[str, Any]
BASE = "prod/boards/b1"


class Memory:
    def __init__(self, rows: list[Row], files: dict[str, bytes], frames: list[Row]) -> None:
        self.rows, self.files, self.frames = rows, files, frames
        self.uploads: list[str] = []
        self.patches: list[tuple[Row, dict[str, str]]] = []
        self.audit: list[Row] = []

    def get(self, table: str, **params: str) -> list[Row]:
        if table == "scene_boards":
            return [dict(r) for r in self.rows if r["status"] == params["status"].removeprefix("eq.")]
        return [f for f in self.frames if f["board_id"] == params["board_id"].removeprefix("eq.")]

    def file(self, bucket: str, path: str) -> bytes:
        return self.files[path]

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        assert path not in self.files, f"a stored file is never overwritten: {path}"
        self.files[path] = data
        self.uploads.append(path)

    def patch(self, table: str, values: Row, **params: str) -> None:
        self.patches.append((values, params))
        row = next(r for r in self.rows if r["id"] == params["id"].removeprefix("eq."))
        row.update(values)

    def insert(self, table: str, rows: list[Row] | Row, upsert: bool = False) -> None:
        assert table == "audit_log"
        self.audit.append(rows if isinstance(rows, dict) else rows[0])


def bad_part(approved: bool = True) -> Memory:
    """Six tall shots, asked 3x2, painted 3x3 with an empty row; cut with the old even split, as stored today."""
    cells = grid_boxes(3, 3, 1024, 1536)
    picture = sheet(cells[:6], empty=cells[6:])
    old = pics._even_boxes(picture, 6)
    row_cells = [{"shot_id": f"s{n}", "number": n, "kind": "painted", "panel": i + 1, "box": list(old[i]),
                  "path": f"{BASE}/cell_{n:03d}.png", "pin": f"pin{n}", "note": "tighter" if n == 9 else "",
                  "locked": n == 10, "previous": [{"pin": "p0", "path": "old.png", "panel": {}}] if n == 11 else [],
                  "text": ""} for i, n in enumerate(range(9, 15))]
    row_cells.insert(3, {"shot_id": "black", "number": 12, "kind": "black", "panel": None, "text": "Cut to black."})
    row = {"id": "b1", "production_id": "prod", "scene_id": "sc", "version": 1, "part": 2, "parts": 2,
           "prompt": "A cinematic storyboard sheet for a Sri Lankan television drama: 6 photorealistic film stills ...",
           "status": "done", "cells": row_cells, "storage_path": f"{BASE}/board.png", "sheet_path": f"{BASE}/sheet.png",
           "approved_at": "2026-11-22T00:00:00Z" if approved else None}
    frames = [{"id": "f1", "board_id": "b1", "shot_id": "s12", "stage": "draft", "status": "done", "accepted_at": None}]
    return Memory([row], {f"{BASE}/board.png": picture}, frames)


def test_a_part_cut_through_its_panels_is_found_with_its_first_frames():
    store = bad_part()
    mends, skipped = recut.find(store)
    assert skipped == 0 and len(mends) == 1
    m = mends[0]
    assert m.was and not m.still, (m.was, m.still)
    assert [f["id"] for f in m.frames] == ["f1"]


def test_apply_stores_fresh_paths_keeps_the_cell_and_clears_the_approval():
    store = bad_part()
    (m,), _ = recut.find(store)
    fields = recut.apply(store, m, tag="abcd1234")
    row = store.rows[0]
    by_shot = {c["shot_id"]: c for c in row["cells"]}
    assert by_shot["s9"]["path"] == f"{BASE}/cell_009-recut-abcd1234.png"
    assert all(p.startswith(f"{BASE}/") and "recut-abcd1234" in p for p in store.uploads)
    assert f"{BASE}/cell_009-recut-abcd1234.png{thumbs.SUFFIX}" in store.uploads, "every new picture has its thumb"
    assert row["sheet_path"] == f"{BASE}/sheet-recut-abcd1234.png" and fields["approved_at"] is None
    assert by_shot["s9"]["pin"] == "pin9" and by_shot["s9"]["note"] == "tighter" and by_shot["s10"]["locked"]
    assert by_shot["s11"]["previous"] == [{"pin": "p0", "path": "old.png", "panel": {}}], "the bad crop is not undo"
    assert by_shot["black"] == {"shot_id": "black", "number": 12, "kind": "black", "panel": None,
                                "text": "Cut to black."}, "a black cell is left as it is"
    crop = Image.open(io.BytesIO(store.files[by_shot["s14"]["path"]]))
    assert crop.height < 700, "shot 14 is its own panel now, not half a panel and an empty cell"
    assert pics.cut_problems(store.files[f"{BASE}/board.png"], [c["box"] for c in recut.grid_cells(row)]) == []
    assert len(store.patches) == 1, "the part is written once"
    (audit,) = store.audit
    assert audit["action"] == "board.recut" and audit["entity_id"] == "b1" and audit["diff"]["approval_cleared"]
    assert audit["diff"]["first_frames"] == ["f1"]


def test_a_part_that_was_not_approved_stays_so_and_a_second_run_finds_nothing():
    store = bad_part(approved=False)
    (m,), _ = recut.find(store)
    fields = recut.apply(store, m)
    assert "approved_at" not in fields
    assert recut.find(store) == ([], 0)


def test_panels_painted_alone_are_left_and_the_grid_cells_beside_them_are_mended():
    """The case of 2026-11-22: Update board painted shots 9 and 14 alone; shots 10-13 still held the bad crops."""
    store = bad_part()
    solo = Image.new("RGB", (340, 600), (120, 40, 40))
    buf = io.BytesIO()
    solo.save(buf, format="PNG")
    for c in store.rows[0]["cells"]:
        if c["shot_id"] in ("s9", "s14"):
            c.update(box=None, panel=1, source="panel", path=f"{BASE}/cell_{c['shot_id']}-solo.png")
            store.files[c["path"]] = buf.getvalue()
    (m,), skipped = recut.find(store)
    assert skipped == 0 and sorted(m.boxes) == ["s10", "s11", "s12", "s13"] and not m.still
    recut.apply(store, m, tag="feed0001")
    by_shot = {c["shot_id"]: c for c in store.rows[0]["cells"]}
    assert by_shot["s9"]["path"] == f"{BASE}/cell_s9-solo.png" and by_shot["s9"]["box"] is None, "left as it is"
    assert by_shot["s12"]["path"].endswith("-recut-feed0001.png")
    assert store.audit[0]["diff"]["shots"] == [10, 11, 12, 13]
    assert recut.find(store) == ([], 0)


def test_a_part_with_no_grid_cell_or_no_panel_count_is_skipped():
    store = bad_part()
    for c in store.rows[0]["cells"]:
        c.update(source="panel", box=None)
    assert recut.find(store) == ([], 1)
    store = bad_part()
    store.rows[0]["prompt"] = ""
    assert recut.find(store) == ([], 1)
