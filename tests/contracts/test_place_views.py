"""plan/2026-11-24c phase 1: place views by type. Three answers pick one of four fixed templates; code checks the
writer's answer; the sheet prompt is the lab's (lab/place_views r2) with dry, even light. Tests from the lab's six
written answers (`lab/place_views/runs/r1|r2/written`, recorded in the views_writer's evals). Pure: no model call."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from contracts import canon

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "src/libs/hiru_ai/agents/views_writer/evals/cases.yaml").read_text(encoding="utf-8"))


def case(start: str) -> dict[str, Any]:
    """The lab place whose case name starts with `start` ("colombo", "kasun's r", "kasun's p", "family")."""
    return next(c for c in CASES if c["name"].lower().startswith(start))


def findings(c: dict[str, Any], **over: Any) -> list[str]:
    written = {**copy.deepcopy(c["reply"]), **over}
    return canon.view_findings(written, c["input"]["place"]["look"], c["input"]["scenes"])


@pytest.mark.parametrize(("word", "template"), [("colombo", "outside"), ("kasun's r", "both"), ("family", "vehicle")])
def test_the_answers_pick_the_template(word, template):
    assert canon.view_template(case(word)["reply"]["answers"]) == template


def test_the_rule_vehicle_when_it_moves_else_by_sides():
    assert canon.view_template({"sides": "both", "moves": True, "size": "small"}) == "vehicle"
    assert canon.view_template({"sides": "inside", "moves": False, "size": "room"}) == "inside"
    assert canon.view_template(None) == "outside"
    assert all(len(slots) == canon.VIEWS_COUNT for slots in canon.VIEW_TEMPLATES.values()), "always one 3x2 sheet"
    assert canon.template_slots("both") == ["Outside wide", "Entrance", "Inside wide", "Inside reverse", "Detail 1",
                                            "Detail 2"]


def test_the_r2_restaurants_sign_text_and_plain_table_are_found():
    out = findings(case("kasun's r"))
    assert len(out) == 2
    assert out[0].startswith("Outside wide gives words to read (\"KASUN'S — SRI LANKAN FOOD & COFFEE\")")
    assert out[1].startswith("Detail 2 is close on a plain table that no scene uses")


def test_the_r2_roadsides_empty_bay_is_accepted_and_a_bay_with_no_place_is_not():
    roadside = case("colombo")
    assert roadside["reply"]["empty"] == ["compact vending/three-wheeler bay (kept empty for a three-wheeler)"]
    assert findings(roadside) == []
    lost = findings(roadside, empty=["a loading space (kept empty)"])
    assert lost == ["The empty space \"a loading space (kept empty)\" does not say where it is: name its side or "
                    "what it is beside, and what its bare ground looks like."]


def test_a_table_the_scenes_use_is_a_fine_detail():
    """The prep room's desk-table holds the papers in its scenes ("on the table"): the restaurant's does not."""
    assert findings(case("kasun's p")) == []


def test_slots_out_of_order_and_sign_wording_without_quotes_are_found():
    car = case("family")
    views = copy.deepcopy(car["reply"]["views"])
    views[0], views[1] = views[1], views[0]
    assert findings(car, views=views)[0].startswith("The views are ['Side', 'Front three-quarter'")
    said = findings(car, layout="A chrome badge plate reads BMW SPORT LINE above the grille.")
    assert any("BMW SPORT LINE" in f for f in said)


def test_the_sheet_is_dry_and_keeps_the_empty_spaces_lab_words():
    roadside = case("colombo")["reply"]
    prompt = canon.views_sheet_prompt("Colombo roadside", "look", "the location plate for Colombo roadside",
                                      "outside", roadside["layout"], roadside["empty"], roadside["views"])
    assert ("Reference images, in order: image 1 is the location plate for Colombo roadside. Take from image 1 the "
            "place itself: its ground, walls, buildings and fixtures") in prompt
    assert ("Light (every view): soft, even, dry daylight that shows the place clearly; dry ground, no rain, no "
            "puddles, no reflections; the same light in every view. No vehicle is parked anywhere in the place. These "
            "spaces are EMPTY in every view, bare, with nothing standing in them: compact vending/three-wheeler bay "
            "(kept empty for a three-wheeler). Leave out anything image 1 shows standing in them.") in prompt
    assert "VIEW 4 (row 2, column 1) — Reverse: Same anchor spot as Wide, turned 180 degrees" in prompt
    assert prompt.endswith("no borders other than the gutters.")


def test_a_place_without_a_plate_is_painted_from_its_words():
    rest = case("kasun's r")
    prompt = canon.views_sheet_prompt("KASUN'S Restaurant", rest["input"]["place"]["look"], "", "both",
                                      rest["reply"]["layout"], [], rest["reply"]["views"])
    assert "Reference images" not in prompt
    assert "There is no picture of this place: paint it from these words: A modest-sized modern" in prompt


def test_a_vehicle_sheet_stands_the_vehicle_alone():
    car = case("family")["reply"]
    prompt = canon.views_sheet_prompt("Family car", "look", "the vehicle plate for Family car", "vehicle",
                                      car["layout"], [], car["views"])
    assert prompt.startswith("A vehicle reference sheet for a Sri Lankan television drama: six photorealistic film "
                             "stills of ONE real vehicle")
    assert "its make and model, body, colour, wheels, lights, windows and its inside" in prompt
    assert ("The vehicle stands alone on a plain, empty, light-grey concrete floor of a large covered parking area "
            "for every outside view; nothing else is near it.") in prompt
    assert "No vehicle is parked" not in prompt


def test_a_views_key_words_are_its_first_sentence():
    view = {"sees": "The road and the far side, the frontage out of frame. Reflections on the tarmac."}
    assert canon.view_key_words(view) == "The road and the far side, the frontage out of frame"
    assert canon.view_key_words({"what": "Old words."}) == "Old words"
    assert canon.view_words({"camera": "From the kerb.", "sees": "The road."}) == "From the kerb. The road."
