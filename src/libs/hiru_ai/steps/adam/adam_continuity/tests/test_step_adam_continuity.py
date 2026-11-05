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


def test_a_person_who_leaves_holding_a_prop_keeps_it():
    """A live run (2026-11-04): Anudi walks out with her bag, the next moment marks only Dasun, and the bag was said to
    go from Anudi to nobody. A holder with no mark at a moment still has what they held."""
    gone = run(staging={"marks": [{"moment": "m1", "who": "Anudi", "zone": "off", "holding": ["bag"]},
                                  {"moment": "m3", "who": "Dasun", "zone": "bench"}]})
    assert gone["ok"], gone
    dropped = run(staging={"marks": [{"moment": "m1", "who": "Anudi", "zone": "bench", "holding": ["bag"]},
                                     {"moment": "m3", "who": "Anudi", "zone": "bench"}]})
    assert codes(dropped) == ["prop_unseen"]  # still marked, no longer holding it, and no moment shows the bag


def test_a_mark_on_a_moment_the_plan_does_not_have_is_named():
    out = run(staging={"marks": [{"moment": "m9", "who": "Anudi", "zone": "bench"}]})
    assert codes(out) == ["unknown_moment"]


def scripted(*blocks: str) -> dict[str, Any]:
    return {"cast": ["Anudi"], "place": {"objects": ["bench", "phone", "bag"]},
            "blocks": [{"index": i, "kind": "action", "text": text} for i, text in enumerate(blocks)]}


def questions(*blocks: str) -> list[dict[str, Any]]:
    return list(step.run({"scene": scripted(*blocks), "moments": [], "cards": []})["questions"])


def test_a_prop_put_down_and_left_where_a_person_exits_raises_a_question_for_a_person():
    """Plan 2026-11-04c F7: does Anudi take her phone when she leaves? The script does not say."""
    asked = questions("She ends the call and puts the phone face-down on the bench.",
                      "She picks up her bag and walks out.")
    assert [(q["object"], q["blocks"], q["source"]) for q in asked] == [("phone", [0, 1], "continuity")]
    assert "does it stay, or go with them" in asked[0]["question"]


def test_no_question_when_the_script_says_she_takes_it_and_a_question_is_never_an_issue():
    assert questions("She puts the phone face-down on the bench.",
                     "She picks up her phone and her bag and walks out.") == []
    assert questions("She puts the phone on the bench.", "She sits and waits.") == []  # nobody leaves
    out = step.run({"scene": scripted("She puts the phone down.", "She walks out."), "moments": [], "cards": []})
    assert out["ok"] and out["issues"] == [] and len(out["questions"]) == 1  # a question is for a person, not a fault


def test_a_thing_that_only_shares_the_sentence_is_not_the_thing_put_down():
    assert [q["object"] for q in questions("She puts the phone face-down on the bench.", "She leaves.")] == ["phone"]


def test_a_malformed_plan_is_reported_not_raised():
    out = step.run({"moments": [{"id": "m1"}], "cards": []})
    assert not out["ok"] and out["issues"][0]["code"] == "malformed"
