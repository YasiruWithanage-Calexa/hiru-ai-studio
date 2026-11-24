"""Fixed marks on the Scene board job (plan/2026-11-24d phase 3), on the `frame_render` system with fakes: the
stretches from the staging map, the writer's spots checked, one blocking plate painted BEFORE the parts and attached
to them, a repaint that keeps the plate, Repaint marks that paints it again, and a board that paints as before when
anything is missing. Nothing is paid for."""
from __future__ import annotations

from typing import Any

from contracts import board as kit
from contracts import marks as mk
from hiru_ai.core.fakes import FakeImages
from hiru_ai.core.ports import Picture, Reference
from hiru_ai.systems.frame_render import board as system
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, reply, run

SPOT = {"stretch": 1, "who": "Kamala", "spot": "on the kitchen floor, one step right of the stove"}


def still(store: BoardStore, *names: str) -> None:
    """Everyone named stands in the kitchen from block 0 and never moves."""
    store.scene_row["staging"] = {"by": "model", "marks": [
        {"block": 0, "who": n, "zone": "kitchen", "posture": "standing"} for n in names]}


def answer(store: BoardStore, marks: list[dict] | None = None) -> dict[str, Any]:
    return {**reply(numbers(store)), "marks": [SPOT] if marks is None else marks}


def painter() -> FakeImages:
    p = FakeImages()
    p.picture = board_png(2, 2)
    return p


def is_plate(prompt: str) -> bool:
    return "the blocking plate of a scene" in prompt


def test_a_still_stretch_paints_one_plate_first_and_every_part_carries_it():
    store = BoardStore()
    still(store, "Kamala")
    bid = store.add_board()
    paint = painter()
    result, _ = run(store, {"board_id": bid}, [answer(store)], paint)
    row = store.board_rows[bid]
    assert result["status"] == "done", (result, row.get("error"))
    plate_call, board_call = paint.calls[0], paint.calls[-1]
    assert is_plate(plate_call[0]) and not is_plate(board_call[0]), "the plate is painted before the parts"
    assert "Ground marks: Small movements" in plate_call[0] and "Kamala (the red mannequin) stands on the kitchen " \
        "floor, one step right of the stove." in plate_call[0]
    assert "The camera: the location plate's own camera" in plate_call[0], "a place with no views sheet"
    labels = [r.label for r in board_call[2]]
    assert labels[0] == "the location plate for Kamala's house" and labels[1].startswith(mk.PLATE_HEAD), \
        "the plate comes after the place"
    n = len(numbers(store))
    assert f"Ground marks ({mk.shots_label(range(1, n + 1))}): nobody walks" in board_call[0]
    assert "— Marks: on the ground mark of shots 1 to" in board_call[0]
    writer = kit.Writer.of(row["writer"])
    assert writer.marks == [{**SPOT, "apart": ""}]
    (plate,) = writer.plates
    assert plate["n"] == 1 and plate["path"].startswith(f"{row['production_id']}/boards/{bid}/plate_1-")
    assert ("frames", plate["path"]) in store.uploads and plate["pin"] and plate["shots"] == numbers(store)


def test_without_a_staging_map_the_board_paints_as_before_and_says_so():
    store = BoardStore()
    store.scene_row.pop("staging", None)
    bid = store.add_board()
    paint = painter()
    result, _ = run(store, {"board_id": bid}, [answer(store, [])], paint)
    row = store.board_rows[bid]
    assert result["status"] == "done" and len(paint.calls) == 1 and not is_plate(paint.calls[0][0])
    assert "Ground marks" not in paint.calls[0][0] and "Marks:" not in paint.calls[0][0]
    assert system.NO_MAP in row["writer"]["conflicts"] and "plates" not in row["writer"]


def test_a_missing_spot_paints_no_plate_and_is_reported():
    store = BoardStore()
    still(store, "Kamala")
    bid = store.add_board()
    paint = painter()
    result, _ = run(store, {"board_id": bid}, [answer(store, [{"stretch": 1, "who": "Nobody", "spot": "x"}])], paint)
    row = store.board_rows[bid]
    assert result["status"] == "done" and len(paint.calls) == 1 and "Ground marks" not in paint.calls[0][0]
    assert any("no ground mark for Kamala" in c for c in row["writer"]["conflicts"])


def test_a_repaint_keeps_the_plate_and_repaint_marks_paints_it_again():
    """§3.6 / D3: Repaint whole board paints the parts against the SAME plate; Repaint marks paints it again first."""
    store = BoardStore()
    still(store, "Kamala")
    first = store.add_board()
    run(store, {"board_id": first}, [answer(store)], painter())
    kept = kit.Writer.of(store.board_rows[first]["writer"]).plates[0]["path"]

    again = store.add_board(version=2)
    paint = painter()
    result, _ = run(store, {"board_id": again, "saved": [first], "carry": [first]}, [], paint)
    assert result["status"] == "done" and len(paint.calls) == 1 and not is_plate(paint.calls[0][0])
    assert kit.Writer.of(store.board_rows[again]["writer"]).plates[0]["path"] == kept
    assert any(r.label.startswith(mk.PLATE_HEAD) for r in paint.calls[0][2]), "the kept plate is still attached"

    marks = store.add_board(version=3)
    paint = painter()
    result, _ = run(store, {"board_id": marks, "saved": [again], "carry": [again], "repaint_plates": [1]}, [], paint)
    assert result["status"] == "done" and is_plate(paint.calls[0][0]) and len(paint.calls) == 2
    assert kit.Writer.of(store.board_rows[marks]["writer"]).plates[0]["path"] != kept, "a new path, never overwritten"


class PlateRefused(FakeImages):
    """Paints the board, refuses the plate."""

    def __call__(self, prompt: str, aspect: str, references: list[Reference], **kw: Any) -> Picture:
        if is_plate(prompt):
            self.calls.append((prompt, aspect, list(references)))
            raise RuntimeError("refused")
        return super().__call__(prompt, aspect, references, **kw)


def test_a_plate_that_cannot_be_painted_never_fails_the_board():
    store = BoardStore()
    still(store, "Kamala")
    bid = store.add_board()
    paint = PlateRefused()
    paint.picture = board_png(2, 2)
    result, _ = run(store, {"board_id": bid}, [answer(store)], paint)
    row = store.board_rows[bid]
    assert result["status"] == "done", (result, row.get("error"))
    assert not any(r.label.startswith(mk.PLATE_HEAD) for r in paint.calls[-1][2])
    assert "Ground marks (" in paint.calls[-1][0], "the words still hold the marks"
    assert any("the blocking plate could not be painted" in c for c in row["writer"]["conflicts"])


def test_a_panel_painted_alone_carries_its_stretchs_saved_plate_and_words():
    """Update board (plan/2026-11-17): the changed shot's panel is painted alone, with the plate the board was painted
    against and its marks; the marks and plates stay on the version's words."""
    from tests.hiru_ai.test_board_update import change, one, queue

    store = BoardStore()
    still(store, "Kamala")
    bid = store.add_board()
    run(store, {"board_id": bid}, [answer(store)], painter())
    saved = kit.Writer.of(store.board_rows[bid]["writer"])
    change(store, 2)
    paint = painter()
    result, _ = run(store, queue(store, [bid]), [one(2)], paint)
    assert result["status"] == "done" and result["updated"] == [2], result
    prompt, _aspect, refs = paint.calls[0]
    assert any(r.label.startswith(mk.PLATE_HEAD) for r in refs) and "THE PANEL — Marks: on the ground mark" in prompt
    assert "Ground marks (" in prompt
    after = kit.Writer.of(store.board_rows[bid]["writer"])
    assert after.marks == saved.marks and after.plates == saved.plates
