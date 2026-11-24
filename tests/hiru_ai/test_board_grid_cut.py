"""plan/2026-11-22 phase 2: a board painted in another grid than asked is cut panel by panel; one that cannot be cut
into one panel per shot fails its part, with nothing stored as a cell and no repaint by itself. Fakes only."""
from __future__ import annotations

from hiru_ai.core.fakes import FakeImages
from hiru_ai.systems.frame_render import board as graph_board
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, reply, run


def test_asked_two_by_two_painted_four_across_is_cut_panel_by_panel():
    store = BoardStore()
    bid = store.add_board()
    assert len(numbers(store)) == 4, "the fixture scene has four shots: a 2x2 grid is asked for"
    painter = FakeImages()
    painter.picture = board_png(4, 1)  # the model painted one row of four
    result, _ = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    row = store.board_rows[bid]
    assert result["status"] == "done" and row["status"] == "done", (result, row.get("error"))
    painted = [c for c in row["cells"] if c["kind"] == "painted"]
    assert [c["number"] for c in painted] == numbers(store)
    widths = [c["box"][2] - c["box"][0] for c in painted]
    heights = [c["box"][3] - c["box"][1] for c in painted]
    assert all(w < 400 for w in widths) and all(h > 1000 for h in heights), [c["box"] for c in painted]
    assert len(painter.calls) == 1, "nothing is repainted"


def test_a_board_that_cannot_be_cut_fails_its_part_and_stores_no_cell():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(3, 1)  # three panels for four shots: no grid holds one panel per shot
    result, _ = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    row = store.board_rows[bid]
    assert result["status"] == "failed" and row["status"] == "failed"
    assert row["error"] == graph_board.bad_cut(numbers(store))
    assert row["error"] == ("Shots 1, 2, 3 and 4 came out in a different layout than was asked. "
                            "Paint the board again.")
    assert not row.get("cells"), "no crop of a bad cut becomes a cell"
    assert not any("/cell_" in path for _bucket, path in store.uploads), "no crop is stored"
    assert row["prompt"] and row["writer"], "the prompt and the writer are kept, as for any failed part"
    assert len(painter.calls) == 1, "D1: a bad cut is never repainted by itself"


def test_a_bad_cut_keeps_the_rejected_picture_and_the_cut_drawn_on_it():
    """2026-11-24: the picture of a rejected part is stored (never as a cell) so a person can see why it failed."""
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(3, 1)
    run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    row = store.board_rows[bid]
    [entry] = row["checks"]
    assert entry["kind"] == graph_board.REJECTED_CUT and entry["problems"] and len(entry["boxes"]) == 4
    assert entry["path"].endswith(f"/boards/{bid}/rejected.png")
    assert entry["cut_path"].endswith(f"/boards/{bid}/rejected-cut.png")
    stored = {path for _bucket, path in store.uploads}
    assert {entry["path"], entry["cut_path"]} <= stored


def test_the_cut_is_drawn_on_the_picture():
    from hiru_ai.systems.frame_render import pictures as pics

    png = board_png(2, 1)
    boxes = pics.cell_boxes(png, 2)
    drawn = pics.draw_cut(png, boxes, ["panel 2: two panels in one crop (a gutter across it, columns)"])
    assert pics.image_size(drawn) == pics.image_size(png) and drawn != png


def test_the_bad_cut_words_name_the_shots():
    assert graph_board.bad_cut([6, 7, 8]) == ("Shots 6, 7 and 8 came out in a different layout than was asked. "
                                              "Paint the board again."), "named by its shots, never its part"
