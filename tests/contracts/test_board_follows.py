"""plan/2026-11-23d part 4: the first frame follows the approved Scene board. Pure: rows in, words out.

The shot prompt and the frame are written from the approved panel (blocking, hands, props), the camera stays the
shot prompt's, a later approved panel makes the shot prompt out of date (D2), and a panel the board's own check found
breaking a fact is never attached."""
from __future__ import annotations

from typing import Any

from contracts import board as kit
from contracts.frame_brief import references_block
from contracts.producer import BLOCKING_LABEL

SHOT = {"id": "s1", "number": 1, "framing": "TWO", "block_start": 0, "block_end": 1,
        "ir": {"first_frame": {"composition": "Kasun left, Anudi right."}}, "intent": {"story": "the phone"}}
PANEL = {"shot": 1, "zone": "roadside", "camera": "Standing eye height, 40mm, waist-up two-shot.",
         "background": "The food three-wheeler at left", "picture": "The blue mannequin holds the clay umbrella open.",
         "people": [{"name": "Anudi", "state": "", "left_hand": "grips the clay umbrella's shaft",
                     "right_hand": "open palm under the clay phone"}],
         "props": [{"name": "umbrella", "held_by": "Anudi", "hand": "left", "frame_side": "right"},
                   {"name": "handbag", "held_by": "Anudi", "hand": "", "rests_on": ""}]}


def part(**over: Any) -> dict[str, Any]:
    return {"id": "b1", "version": 2, "part": 1, "status": "done", "approved_at": "2026-11-23T13:40:00Z",
            "colours": {"c-anudi": "blue"},
            "writer": {"world": "Overcast.", "geography": "Across.", "panels": [PANEL], "conflicts": []},
            "cells": [{"shot_id": "s1", "number": 1, "kind": "painted", "path": "p/cell_001.png",
                       "pin": kit.plan_pin(SHOT)}], **over}


def test_the_approved_panel_is_found_only_when_done_approved_and_current():
    found = kit.approved_panel([part(), part(id="old", version=1)], SHOT)
    assert found is not None and found.stamp == "b1:p/cell_001.png" and found.panel.props[0].name == "umbrella"
    assert kit.approved_panel([part(approved_at=None)], SHOT) is None, "an unapproved board gives nothing"
    assert kit.approved_panel([part(status="running")], SHOT) is None
    stale = part(cells=[{**part()["cells"][0], "pin": "v3:0000"}])
    assert kit.approved_panel([stale], SHOT) is None, "a panel out of date gives nothing"


def test_a_shot_prompt_written_before_the_approved_panel_is_out_of_date():
    """D2: the person approved the panel, so the panel wins over an older shot prompt."""
    assert kit.board_reason({"frame": {}}, [part()], SHOT) == kit.BOARD_CHANGED
    assert kit.board_reason({"frame": {}, "board": "b1:p/cell_001.png"}, [part()], SHOT) == ""
    assert kit.board_reason({"frame": {}}, [part(approved_at=None)], SHOT) == "", "no approved board, no reason"


def test_the_shot_prompter_gets_blocking_hands_and_props_never_the_camera():
    facts = kit.panel_facts(kit.Writer.of(part()["writer"]).panels[0], {"Anudi": "blue"})
    assert facts["hands"] == [{"name": "Anudi", "left_hand": "grips the umbrella's shaft",
                               "right_hand": "open palm under the phone"}]
    assert "Anudi holds the umbrella open" in facts["blocking"] and "40mm" not in facts["blocking"]
    assert facts["props"][0] == {"name": "umbrella", "held_by": "Anudi", "hand": "left", "frame_side": "right"}


def test_a_frame_from_its_shot_prompt_takes_the_blocking_not_the_camera():
    w = kit.Writer.of(part()["writer"])
    sections = kit.frame_sections(w, 1, {"Anudi": "blue"}, [], (), blocking=True)
    text = " ".join(sections)
    assert "approved scene board panel" in sections[0] and "40mm" not in text, "the panel's camera is not given"
    assert "Hands as approved on the scene board: Anudi: left hand grips the umbrella's shaft" in text
    assert "exactly the mannequin's place in the frame, size" not in text
    labels = ["the face sheet for Anudi", BLOCKING_LABEL]
    said = " ".join(references_block(labels))
    assert "this shot's words decide the camera" in said
    assert "keep its composition, framing" not in said, "never the full-draft rule"


def test_a_panel_that_breaks_a_fact_is_not_attached():
    w = kit.Writer.of({**part()["writer"], "conflicts": [
        "Shot 1: Anudi holds the kettle, which neither the plan of this shot nor what they carry through the scene "
        "gives them.", "Shot 2: Kasun is only heard in this shot but is on the board.", "A look disagrees."]})
    assert len(kit.panel_faults(w, 1)) == 1 and kit.panel_faults(w, 3) == []


def test_a_look_sheet_never_puts_a_carried_thing_in_a_hand_by_itself():
    said = " ".join(references_block(["the face sheet for Anudi", "the look sheet for Anudi"]))
    assert "A carried thing on the look sheet (a bag, an umbrella) is held or worn as this shot's words" in said


def test_how_the_board_is_painted_never_reaches_a_real_frame():
    """Scene 4 shot 1, 2026-11-23: the board's World said "Render them without human surface details or clothing" and
    "every portable object is its actual size and outline, without marking"; a frame must not get either."""
    world = ("Fine rain on a Colombo roadside. Render them without human surface details or clothing. Every portable "
             "object is its actual size and outline, without marking. The food three-wheeler stays real.")
    assert kit.frame_world(world) == "Fine rain on a Colombo roadside. The food three-wheeler stays real."
    w = kit.Writer.of(part()["writer"])
    assert all("The approved draft" not in s for s in kit.frame_sections(w, 1, {"Anudi": "blue"}, [], (),
                                                                          blocking=True))
