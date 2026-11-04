from __future__ import annotations

import copy

import pytest
from tests.hiru_ai.steps_fixtures import CAST, felt_scene
from tests.services.production_fixture import PHONE_CANON

from hiru_ai.steps.shot_joins import logic, step


def case(scene, lines, shots, number=1, **extra):
    return {"scene": scene, "lines": lines, "shots": shots, "number": number, "cast": CAST, **extra}


def test_a_scene_whose_people_stay_where_they_are_has_nothing_to_report():
    out = step.run(case(*felt_scene()))
    assert out["first"] == "S01" and out["second"] == "S02" and out["ok"] and out["findings"] == []


def test_the_last_shot_has_no_join():
    out = step.run(case(*felt_scene(), number=2))
    assert out["second"] is None and out["ok"] and "last shot" in out["note"]


def kasun_on_both_sides(second_mark):
    """The phone scene with Kasun in the first block of S02 too, and a staging map that puts him where `second_mark`
    says."""
    from tests.services.production_fixture import phone_scene

    from contracts import sceneplan, stagemap

    scene, lines, shots = phone_scene()
    scene["script"][2]["text"] = "Kasun nods. Anudi smiles back."
    items = sceneplan.items_for(scene["script"], lines)
    marks = [{"block": 0, "who": "Kasun", "zone": "stall", "facing": "right", "frame_side": "left",
              "holding": "a ladle"},
             {"block": 2, "who": "Anudi", "zone": "street", "facing": "left", "frame_side": "right", "holding": ""},
             {"block": 2, "who": "Kasun", **second_mark}]
    staging = stagemap.validate({"zones": ["stall", "street"], "marks": marks}, items, CAST, version=1, by="model")
    return {**scene, "staging": staging.model_dump(mode="json")}, lines, shots


STAY = {"zone": "stall", "facing": "right", "frame_side": "left", "holding": "a ladle"}


def test_a_person_who_changes_zone_across_the_cut_is_a_position_finding():
    out = step.run(case(*kasun_on_both_sides({**STAY, "zone": "street"})))
    assert [f["code"] for f in out["findings"]] == ["position"]
    assert "ends S01 in the stall and opens S02 in the street" in out["findings"][0]["message"]


def test_a_person_who_stays_put_with_the_same_hands_is_fine():
    out = step.run(case(*kasun_on_both_sides(STAY)))
    assert out["ok"], out["findings"]


def test_the_other_side_of_the_frame_is_a_side_finding():
    out = step.run(case(*kasun_on_both_sides({**STAY, "frame_side": "right"})))
    assert [f["code"] for f in out["findings"]] == ["side"]


def test_something_put_down_or_picked_up_across_the_cut_is_a_prop_finding():
    out = step.run(case(*kasun_on_both_sides({**STAY, "holding": ""})))
    assert [f["code"] for f in out["findings"]] == ["prop"] and "a ladle" in out["findings"][0]["message"]


def test_a_continuous_join_in_another_size_is_a_join_size_finding():
    scene, lines, shots = felt_scene()
    shots = copy.deepcopy(shots)
    shots[1].update(camera_link="continuous", framing="WIDE")
    out = step.run(case(scene, lines, shots))
    assert [f["code"] for f in out["findings"]] == ["join_size"] and "WIDE" in out["findings"][0]["message"]


def test_a_cut_in_another_size_is_fine():
    scene, lines, shots = felt_scene()
    shots = copy.deepcopy(shots)
    shots[1].update(camera_link="cut", framing="WIDE")
    assert step.run(case(scene, lines, shots))["ok"]


def test_two_shots_designed_on_different_cards_of_the_same_person_are_a_card_finding():
    scene, lines, shots = felt_scene()
    shots = copy.deepcopy(shots)
    anudi = next(c["id"] for c in PHONE_CANON if c["code"] == "C02")
    shots[0]["design"] = {"pins": {"shot_version": 1, "script_hash": "x", "canon": {anudi: 1}}}
    shots[1]["design"] = {"pins": {"shot_version": 1, "script_hash": "x", "canon": {anudi: 2}}}
    out = step.run(case(scene, lines, shots, canon=PHONE_CANON))
    assert [f["code"] for f in out["findings"]] == ["card"] and "C02 Anudi" in out["findings"][0]["message"]


def test_a_scene_with_no_staging_map_gets_no_position_findings():
    scene, lines, shots = felt_scene()
    out = step.run(case({**scene, "staging": {}}, lines, shots))
    assert out["ok"] and out["staging_map"] is False


def test_an_unknown_shot_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="no shot S09"):
        logic.joins(*felt_scene()[:1], felt_scene()[1], felt_scene()[2], 9, CAST)
