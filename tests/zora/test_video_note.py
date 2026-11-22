"""plan/2026-11-22c: Zora saves a video note (how a shot plays) without moving the shot's version or its board
panel, and an author keeps to a performance task. Fakes only: no model, no network."""
from __future__ import annotations

from contracts.board import plan_pin
from contracts.producer import PersonEdits
from hiru_ai.systems.zora.zora_chat.turn import fence
from tests.zora.rows_world import Recorded, RowsWorld
from tests.zora.test_rows_turn import conductor, scene

SOFTER = {"op": "video_note", "shot": "S01", "value": "softer voice, calm and romantic"}


def first(w: RowsWorld) -> dict:
    return dict(w.scenes.shots(w.scene_id)[0])


def test_the_persons_video_note_is_saved_and_the_first_frame_and_board_stay_current() -> None:
    w = RowsWorld()
    was = first(w)
    out = w.turn("Make S01 a softer voice, calm and romantic.", Recorded(conductor("edit", ops=[SOFTER])))
    assert "plan" in out
    now = first(w)
    assert PersonEdits.of(now).video_note == "softer voice, calm and romantic"
    assert int(now.get("version") or 1) == int(was.get("version") or 1)  # the frame's pin holds
    assert plan_pin(now) == plan_pin(was)  # no Update board for a note


def test_undo_takes_the_note_back_and_keeps_the_version() -> None:
    w = RowsWorld()
    was = first(w)
    w.turn("Make S01 a softer voice, calm and romantic.", Recorded(conductor("edit", ops=[SOFTER])))
    w.turn("undo", Recorded())
    now = first(w)
    assert PersonEdits.of(now).video_note == ""
    assert int(now.get("version") or 1) == int(was.get("version") or 1)


def test_a_video_note_is_a_performance_change_and_nothing_else() -> None:
    cov = scene()
    performance = [{"writes": ["performance"], "scope": [], "instruction": "softer"}]
    picture = [{"writes": ["picture"], "scope": [], "instruction": "the car"}]
    assert fence([SOFTER], performance, cov)[0] == [SOFTER]
    assert fence([SOFTER], picture, cov)[0] == []
    size = {"op": "set", "shot": "S01", "field": "size", "value": "CU"}
    assert fence([size], performance, cov)[0] == []
