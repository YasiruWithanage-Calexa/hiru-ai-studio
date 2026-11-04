"""adam_continuity: the 180° line, eyelines, teleports and props that change hands unseen (plan/2026-11-04b §5.3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_continuity import step

HERE = Path(__file__).resolve().parents[1]

MOMENTS: list[dict[str, Any]] = [
    {"id": "m1", "tier": "script", "serves": ["b0"], "who": ["Anudi", "Dasun"]},
    {"id": "m2", "tier": "script", "serves": ["b1"], "who": ["Anudi"], "objects": ["phone"]},
    {"id": "m3", "tier": "script", "serves": ["b2"], "who": ["Dasun"]},
    {"id": "m4", "tier": "script", "serves": ["b3"], "who": ["Anudi"], "objects": ["phone"]},
]


def card(number: int, moments: list[str], **extra: Any) -> dict[str, Any]:
    return {"number": number, "moments": moments, "size": "CU", "take_s": 4, **extra}


def run(cards: list[dict[str, Any]] | None = None, staging: dict[str, Any] | None = None) -> dict[str, Any]:
    return step.run({"moments": MOMENTS, "cards": cards or [], "staging": staging or {}})


def codes(out: dict[str, Any]) -> list[str]:
    return [i["code"] for i in out["issues"]]


def test_the_example_runs_alone():
    assert step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))["ok"]


def test_two_cards_on_opposite_sides_of_the_line_with_no_neutral_shot_cross_it():
    out = run([card(1, ["m2"], axis="A"), card(2, ["m3"], axis="B")])
    assert codes(out) == ["axis_cross"]
    assert run([card(1, ["m2"], axis="A"), card(2, ["m3"], axis="A")])["ok"]
    neutral = run([card(1, ["m2"], axis="A"), card(2, ["m3"], axis="B", size="INSERT")])
    assert neutral["ok"]  # an insert takes no side of the line


def test_two_people_who_face_each_other_sit_on_opposite_sides_of_the_frame():
    both_left = run([card(1, ["m2"], composition={"frame_side": "left"}),
                     card(2, ["m3"], composition={"frame_side": "left"})])
    assert codes(both_left) == ["screen_direction"]
    assert "anudi" in both_left["issues"][0]["message"]
    assert run([card(1, ["m2"], composition={"frame_side": "left"}),
                card(2, ["m3"], composition={"frame_side": "right"})])["ok"]


def test_eyelines_that_do_not_meet_are_found_when_the_frame_side_is_not_given():
    assert codes(run([card(1, ["m2"], eyeline="right"), card(2, ["m3"], eyeline="right")])) == ["eyeline"]
    assert run([card(1, ["m2"], eyeline="right"), card(2, ["m3"], eyeline="left")])["ok"]


def test_the_same_person_in_two_cards_is_not_a_screen_direction_problem():
    assert run([card(1, ["m2"], composition={"frame_side": "left"}),
                card(2, ["m4"], composition={"frame_side": "left"})])["ok"]


def test_a_person_in_two_places_without_a_move_is_a_teleport():
    marks = [{"moment": "m1", "who": "Anudi", "zone": "bench"}, {"moment": "m4", "who": "Anudi", "zone": "gate"}]
    out = run(staging={"marks": marks})
    assert codes(out) == ["teleport"] and "no move is written" in out["issues"][0]["message"]
    moved = run(staging={"marks": marks, "moves": [{"moment": "m3", "who": "anudi", "from_zone": "bench",
                                                    "to_zone": "gate", "why": "exit"}]})
    assert moved["ok"]
    late = run(staging={"marks": marks, "moves": [{"moment": "m1", "who": "Anudi", "to_zone": "gate"}]})
    assert codes(late) == ["teleport"]  # a move before the first mark does not explain the change


def test_a_prop_that_changes_hands_must_be_seen_changing():
    marks = [{"moment": "m1", "who": "Anudi", "zone": "bench"},
             {"moment": "m4", "who": "Anudi", "zone": "bench", "holding": ["phone"]}]
    seen = run(staging={"marks": marks})  # m4 shows the phone
    assert seen["ok"], seen
    unseen = run(staging={"marks": [{"moment": "m1", "who": "Anudi", "zone": "bench"},
                                    {"moment": "m3", "who": "Dasun", "zone": "bench", "holding": ["bag"]}]})
    assert codes(unseen) == ["prop_unseen"]  # no moment between shows the bag
    assert "bag" in unseen["issues"][0]["message"]


def test_a_mark_on_a_moment_the_plan_does_not_have_is_named():
    out = run(staging={"marks": [{"moment": "m9", "who": "Anudi", "zone": "bench"}]})
    assert codes(out) == ["unknown_moment"]


def test_a_malformed_plan_is_reported_not_raised():
    out = step.run({"moments": [{"id": "m1"}], "cards": []})
    assert not out["ok"] and out["issues"][0]["code"] == "malformed"
