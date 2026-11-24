"""Repaint paints, it does not write again (the person, 2026-11-24): a whole repaint paints the board's pictures from
the panel words already written; the board writer runs for a first board, or when a person asks to rewrite. A shot that
changed since its words were written (a chat or a planner moved its plan pin), or a note on its panel, makes a rewrite
needed. Fakes only."""
from __future__ import annotations

from contracts import board as kit
from hiru_ai.core.fakes import FakeImages
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, reply, run
from tests.services.frame_render.test_frame_render import shots

WRITER = "frame_render.board_writer"


def first_board(store: BoardStore) -> str:
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    result, (_jobs, recorded) = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    assert result["status"] == "done" and recorded.phases.count(WRITER) == 1
    return bid


def repaint(store: BoardStore, saved: list[str], rewrite: bool = False, replies: list | None = None):
    bid = store.add_board(version=2)
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    result, (_jobs, recorded) = run(store, {"board_id": bid, "saved": saved, "rewrite": rewrite,
                                            "carry": saved}, replies or [], painter)
    return bid, result, recorded, painter


def test_a_written_board_stamps_each_panel_with_its_shot_and_pin():
    store = BoardStore()
    bid = first_board(store)
    panels = kit.Writer.of(store.board_rows[bid]["writer"]).panels
    by_number = {int(s["number"]): s for s in shots(store)}
    assert all(p.shot_id == str(by_number[p.shot]["id"]) and p.pin == kit.plan_pin(by_number[p.shot]) for p in panels)


def test_a_repaint_paints_from_the_saved_words_without_the_writer():
    store = BoardStore()
    first = first_board(store)
    bid, result, recorded, painter = repaint(store, [first])
    row = store.board_rows[bid]
    assert result["status"] == "done", (result, row.get("error"))
    assert WRITER not in recorded.phases, "the board writer does not run for a repaint"
    assert len(painter.calls) == 1, "the pictures are painted again"
    assert kit.Writer.of(row["writer"]).dump() == kit.Writer.of(store.board_rows[first]["writer"]).dump()
    assert row["colours"] == store.board_rows[first]["colours"], "the mannequins keep their colours"


def test_a_shot_changed_since_needs_its_words_written_again():
    store = BoardStore()
    first = first_board(store)
    changed = shots(store)[1]
    changed["framing"] = "extreme close-up, a new framing"
    assert kit.rewrite_needed([store.board_rows[first]], shots(store)) == [int(changed["number"])]
    assert kit.reuse_writer([store.board_rows[first]], shots(store), [str(s["id"]) for s in shots(store)]) is None


def test_a_rewrite_runs_the_writer_again():
    store = BoardStore()
    first = first_board(store)
    _bid, result, recorded, _painter = repaint(store, [first], rewrite=True, replies=[reply(numbers(store))])
    assert result["status"] == "done" and recorded.phases.count(WRITER) == 1


def test_a_note_on_a_panel_asks_for_new_words():
    store = BoardStore()
    first = first_board(store)
    row = store.board_rows[first]
    row["cells"][0]["note"] = "Have her face the door."
    assert kit.rewrite_needed([row], shots(store)) == [int(row["cells"][0]["number"])]
    row["cells"][0]["locked"] = True
    assert kit.rewrite_needed([row], shots(store)) == [], "a locked panel is never repainted, so its note waits"


def test_a_board_written_before_the_stamps_is_reused_through_its_cells():
    store = BoardStore()
    first = first_board(store)
    row = store.board_rows[first]
    old = kit.Writer.of(row["writer"])
    row["writer"] = {**old.dump(stamps=False)}
    assert kit.rewrite_needed([row], shots(store)) == []
    reused = kit.reuse_writer([row], shots(store), [str(s["id"]) for s in shots(store)])
    assert reused is not None and [p.shot for p in reused.panels] == numbers(store)


def test_a_failed_part_keeps_its_words_for_the_repaint():
    store = BoardStore()
    first = first_board(store)
    store.board_rows[first].update(status="failed", cells=[])  # the cut failed: no cells, the words are stored
    assert kit.saved_board(list(store.board_rows.values())) == [store.board_rows[first]]
    _bid, result, recorded, _painter = repaint(store, [first])
    assert result["status"] == "done" and WRITER not in recorded.phases


def test_nothing_written_means_every_shot_needs_words():
    store = BoardStore()
    assert kit.saved_board([]) == []
    assert kit.rewrite_needed([], shots(store)) == numbers(store)


def test_a_board_job_reports_progress_so_the_sweeper_does_not_stop_it():
    """2026-11-24: v17 of scene 4 was ended at 10 minutes while painting part 3 (no job event since it started)."""
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    _result, (jobs, _recorded) = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    texts = jobs.texts("stage")
    assert texts[:2] == ["Writing the panels", "Painting part 1 of 1"], texts
