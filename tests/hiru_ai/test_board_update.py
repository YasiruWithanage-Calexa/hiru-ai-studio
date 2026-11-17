"""plan/2026-11-17 phase 2: Update board, on the `frame_render` system with fakes. An edited or added shot's panel is
painted ALONE with its neighbours attached; every other cell keeps its path and bytes; removed and moved shots paint
nothing; a locked panel is left; a failed panel keeps its old cell; an undo comes back with no call; the overlap panel
updates both parts. A scripted writer and a fake painter: nothing is paid for."""
from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

from contracts import board as kit
from hiru_ai.core.fakes import FakeImages
from hiru_ai.systems.frame_render import board as graph_board
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, png, reply, run
from tests.services.frame_render.test_frame_render import shots

APPROVED = {"approved_at": "2026-11-17T09:00:00Z", "approved_by": "u-1"}


def one(number: int, picture: str = "The red mannequin turns to the door.") -> dict[str, Any]:
    """A one-panel answer: `world` and `geography` empty, the writer's own number not trusted."""
    return {"world": "", "geography": "", "conflicts": ["The door is on the left in shot 2."],
            "panels": [{"shot": 99, "zone": "kitchen", "camera": f"New camera {number}.", "background": "the door",
                        "picture": picture, "people": [{"name": "Kamala", "state": ""}]}]}


def painted_board() -> tuple[BoardStore, str, FakeImages]:
    """A whole board painted and approved, as the person left it."""
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    result, _ = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    assert result["status"] == "done", result
    store.board_rows[bid].update(APPROVED)
    return store, bid, painter


def queue(store: BoardStore, ids: list[str], wanted: list[str] | None = None) -> dict[str, Any]:
    """What the API does: every part `queued`, its approval cleared and carried in the job's state."""
    approvals = {}
    for i in ids:
        row = store.board_rows[i]
        approvals[i] = {"approved_at": row.get("approved_at"), "approved_by": row.get("approved_by")}
        row.update(status="queued", approved_at=None, approved_by=None)
    return {"update": True, "scene_id": store.board_rows[ids[0]]["scene_id"], "board_ids": ids,
            "shots": wanted or [], "approvals": approvals}


def snapshot(store: BoardStore, bid: str) -> dict[str, tuple[str, bytes]]:
    """shot id → (path, bytes) of every painted cell."""
    return {c["shot_id"]: (c["path"], store.uploads[("frames", c["path"])])
            for c in store.board_rows[bid]["cells"] if c.get("path")}


def change(store: BoardStore, number: int, setting: str = "the yard at night") -> str:
    row = next(s for s in shots(store) if s["number"] == number)
    row["ir"] = {**(row.get("ir") or {}), "setting": setting}
    return str(row["id"])


def panel_words(store: BoardStore, bid: str) -> dict[str, str]:
    """shot id → its writer panel's picture, read by the cell's number (what a first frame reads)."""
    row = store.board_rows[bid]
    w = kit.Writer.of(row["writer"])
    return {c["shot_id"]: w.panel(int(c["number"])).picture for c in row["cells"]  # type: ignore[union-attr]
            if c.get("kind") == "painted"}


def test_a_changed_shot_paints_one_picture_and_no_other_cell_moves():
    store, bid, painter = painted_board()
    before = snapshot(store, bid)
    words = panel_words(store, bid)
    sid = change(store, 2)
    calls = len(painter.calls)
    painter.picture = png((200, 30, 30))
    result, (jobs, recorded) = run(store, queue(store, [bid]), [one(2)], painter)
    row = store.board_rows[bid]
    assert result["status"] == "done" and result["updated"] == [2], result
    assert len(painter.calls) == calls + 1, "ONE picture: no grid, no mask, no whole repaint"
    prompt, aspect, refs = painter.calls[-1]
    assert painter.masks[-1] is None and aspect == "16:9" and painter.qualities[-1] == "low"
    assert prompt.startswith("ONE photorealistic film still") and kit.CAMERA_RULE in prompt
    assert [r.label for r in refs][-2:] == [kit.neighbour_label("before", 1), kit.neighbour_label("after", 3)]
    message = str(recorded.calls[-1])
    assert "being_replaced" in message and "ONE PANEL" in message, "the one-panel writer, the system prompt unchanged"
    after = snapshot(store, bid)
    assert {k: v for k, v in after.items() if k != sid} == {k: v for k, v in before.items() if k != sid}, \
        "every other cell keeps its path and its bytes"
    new = next(c for c in row["cells"] if c["shot_id"] == sid)
    assert new["path"] != before[sid][0] and new["path"].endswith(".png") and f"cell_{sid}-" in new["path"]
    assert new["source"] == "panel" and new["box"] is None and new["pin"] == kit.plan_pin(store.shot_rows[sid])
    assert new["previous"][0]["path"] == before[sid][0], "the old picture is kept for an undo"
    assert [c["shot_id"] for c in row["cells"] if c.get("fresh")] == [sid], "the card names what this update did"
    assert after[sid][1] == png((200, 30, 30)), "the picture painted is the cell, whole"
    assert panel_words(store, bid)[sid] == "The red mannequin turns to the door."
    assert {k: v for k, v in panel_words(store, bid).items() if k != sid} == \
        {k: v for k, v in words.items() if k != sid}
    assert row["status"] == "done" and row["approved_at"] is None, "a changed part is approved again by a person"
    assert "/sheet-" in row["sheet_path"] and ("frames", row["sheet_path"]) in store.uploads, \
        "the numbered sheet is drawn again from the cells"
    assert any(e.get("text") == "Scene board updated" and e.get("board_id") == bid for e in jobs.events)
    assert "The door is on the left in shot 2." in row["writer"]["conflicts"]
    assert not kit.stale_cells(row["cells"], shots(store)).any


def test_an_added_shot_is_inserted_in_order_and_every_number_moves_with_its_panel():
    store, bid, painter = painted_board()
    before = snapshot(store, bid)
    words = panel_words(store, bid)
    for s in shots(store):
        if s["number"] >= 3:
            s["number"] += 1
    template = next(s for s in shots(store) if s["number"] == 2)
    new_id = str(uuid4())
    store.shot_rows[new_id] = {**copy.deepcopy(template), "id": new_id, "number": 3}
    painter.picture = png((30, 200, 30))
    result, (_, recorded) = run(store, queue(store, [bid]), [one(3, "The red mannequin lifts the lid.")], painter)
    row = store.board_rows[bid]
    assert result["status"] == "done" and result["updated"] == [3], result
    assert [c["number"] for c in row["cells"]] == [1, 2, 3, 4, 5]
    assert row["cells"][2]["shot_id"] == new_id and row["cells"][2]["source"] == "panel"
    assert "ADD. Shot 3 is a new shot, between shot 2 and shot 4." in str(recorded.calls[-1])
    got = panel_words(store, bid)
    assert got[new_id] == "The red mannequin lifts the lid."
    assert {k: got[k] for k in words} == words, "each panel's words follow its shot, whatever its number now"
    assert {k: v for k, v in snapshot(store, bid).items() if k != new_id} == before
    assert not kit.stale_cells(row["cells"], shots(store)).any


def test_a_removed_shot_paints_nothing_and_keeps_the_approval_d2():
    store, bid, painter = painted_board()
    words = panel_words(store, bid)
    gone = str(shots(store)[1]["id"])
    store.shot_rows.pop(gone)
    for s in shots(store):
        if s["number"] > 2:
            s["number"] -= 1
    calls = len(painter.calls)
    result, (_, recorded) = run(store, queue(store, [bid]), [], painter)
    row = store.board_rows[bid]
    assert result["status"] == "done" and len(painter.calls) == calls and not recorded.calls, "nothing painted"
    assert [c["number"] for c in row["cells"]] == [1, 2, 3] and gone not in {c["shot_id"] for c in row["cells"]}
    assert panel_words(store, bid) == {k: v for k, v in words.items() if k != gone}
    assert row["approved_at"] == APPROVED["approved_at"], "D2 (recommended): no picture changed, the approval stays"
    assert not kit.stale_cells(row["cells"], shots(store)).any


def test_a_locked_panel_is_left_and_named():
    store, bid, painter = painted_board()
    sid = change(store, 2)
    store.board_rows[bid]["cells"][1]["locked"] = True
    other = change(store, 4)
    before = snapshot(store, bid)
    result, _ = run(store, queue(store, [bid]), [one(4)], painter)
    assert result["updated"] == [4] and result["locked"] == [2]
    assert snapshot(store, bid)[sid] == before[sid] and snapshot(store, bid)[other] != before[other]


def test_a_failed_panel_keeps_its_old_cell_and_its_approval():
    store, bid, _ = painted_board()
    before = snapshot(store, bid)
    change(store, 2)
    result, _ = run(store, queue(store, [bid]), [one(2)], FakeImages(error=RuntimeError("boom")))
    row = store.board_rows[bid]
    assert result["status"] == "failed" and result["failed"] == {2: graph_board.FAILED}
    assert snapshot(store, bid) == before and row["status"] == "done", "the old board stays in force"
    assert row["approved_at"] == APPROVED["approved_at"], "no cell changed: the person's approval comes back"
    assert row["error"].startswith("Shot 2 could not be updated")


def test_an_undo_brings_the_old_panel_back_with_no_call():
    store, bid, painter = painted_board()
    row_before = copy.deepcopy(store.shot_rows)
    sid = change(store, 2)
    old = snapshot(store, bid)[sid]
    old_words = panel_words(store, bid)[sid]
    painter.picture = png((10, 10, 200))
    run(store, queue(store, [bid]), [one(2)], painter)
    store.shot_rows[sid]["ir"] = row_before[sid]["ir"]  # Zora's undo puts the plan back
    calls = len(painter.calls)
    result, (_, recorded) = run(store, queue(store, [bid]), [], painter)
    assert result["updated"] == [2] and len(painter.calls) == calls and not recorded.calls, "no model call"
    assert snapshot(store, bid)[sid] == old and panel_words(store, bid)[sid] == old_words
    other = change(store, 4)
    run(store, queue(store, [bid]), [one(4)], painter)
    assert [c["shot_id"] for c in store.board_rows[bid]["cells"] if c.get("fresh")] == [other], \
        "an earlier update's mark is cleared"


def test_the_overlap_panel_updates_both_parts():
    store, bid, painter = painted_board()
    whole = store.board_rows[bid]
    cells = whole["cells"]
    second = str(uuid4())
    whole["cells"] = cells[:3]
    whole["parts"] = 2
    store.board_rows[second] = {**copy.deepcopy(whole), "id": second, "part": 2, "cells": copy.deepcopy(cells[2:]),
                                **APPROVED}
    sid = change(store, 3)
    calls = len(painter.calls)
    painter.picture = png((90, 10, 90))
    result, _ = run(store, queue(store, [bid, second]), [one(3)], painter)
    assert result["status"] == "done" and len(painter.calls) == calls + 1, "the overlap panel is painted once"
    a = next(c for c in store.board_rows[bid]["cells"] if c["shot_id"] == sid)
    b = next(c for c in store.board_rows[second]["cells"] if c["shot_id"] == sid)
    assert a["path"] == b["path"] and a["source"] == "panel"
    assert store.board_rows[bid]["approved_at"] is None and store.board_rows[second]["approved_at"] is None


def test_an_update_keeps_the_boards_colours():
    store, bid, painter = painted_board()
    store.board_rows[bid]["colours"] = {k: c for k, c in zip(store.board_rows[bid]["colours"],
                                                             ["green", "purple"], strict=True)}
    saved = dict(store.board_rows[bid]["colours"])
    change(store, 2)
    run(store, queue(store, [bid]), [one(2)], painter)
    assert store.board_rows[bid]["colours"] == saved
    assert "is the green mannequin" in painter.calls[-1][0], "the panel is painted in the board's own colours"


def test_a_second_delivery_of_an_update_is_not_paid_for():
    store, bid, painter = painted_board()
    change(store, 2)
    state = queue(store, [bid])
    store.board_rows[bid]["status"] = "running"
    result, _ = run(store, state, [one(2)], painter)
    assert result["status"] == "skipped"
