"""adam_feasibility: what Veo renders badly, with the known fix (plan/2026-11-04b §5.3, §7)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_feasibility import step

HERE = Path(__file__).resolve().parents[1]
SCENE: dict[str, Any] = {"cast": ["A", "B"], "blocks": [
    {"index": 0, "kind": "action", "text": "x"},
    {"index": 1, "kind": "dialogue", "speaker": "A", "line_id": "L1", "text": "one two three"}]}


def run(seen: str = "", notes: str = "", who: tuple[str, ...] = ("A",), arrangement: str = "single",
        extra_cards: list[dict[str, Any]] | None = None, scene: dict[str, Any] = SCENE) -> dict[str, Any]:
    moments = [{"id": "m1", "tier": "script", "serves": ["b0"], "who": list(who), "seen": seen}]
    cards = [{"number": 1, "moments": ["m1"], "size": "MS", "arrangement": arrangement, "take_s": 4,
              "veo_notes": notes}, *(extra_cards or [])]
    return step.run({"scene": scene, "moments": moments, "cards": cards})


def codes(out: dict[str, Any]) -> list[str]:
    return [f["code"] for f in out["flags"]]


def test_the_example_runs_alone_and_its_flag_is_answered():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert codes(out) == ["screen_text"] and out["flags"][0]["addressed"] and out["ok"]


def test_readable_screen_text_is_a_high_risk_until_the_card_answers_it():
    out = run(seen="the screen shows her father's name")
    assert codes(out) == ["screen_text"] and not out["ok"] and out["unaddressed_high"] == 1
    assert "reaction" in out["flags"][0]["fix"] and out["by_card"] == {1: 1}
    answered = run(seen="the screen shows her father's name", notes="the name is added in post")
    assert answered["flags"][0]["addressed"] and answered["ok"] and answered["unaddressed"] == 0


def test_a_note_that_does_not_answer_the_flag_leaves_it_open():
    out = run(seen="the screen shows her father's name", notes="slow push-in, warm light")
    assert not out["flags"][0]["addressed"] and not out["ok"]


def test_each_known_risk_is_found():
    for text, code in [("a mirror behind her", "mirror"), ("she is typing quickly", "fast_hands"),
                       ("a crowd fills the square", "crowd"), ("they hug on the bench", "touching")]:
        assert code in codes(run(seen=text)), text


def test_touching_is_a_warning_and_does_not_fail_the_plan():
    out = run(seen="they hug on the bench")
    assert out["flags"][0]["risk"] == "medium" and out["ok"] and out["unaddressed"] == 1


def test_a_plain_shot_has_no_flags():
    assert run(seen="she looks out over the lake")["flags"] == []


def test_many_faces_in_one_frame_are_flagged():
    out = run(who=("A", "B", "C", "D", "E"))
    assert "many_faces" in codes(out) and not out["ok"]
    assert "many_faces" not in codes(run(who=("A", "B")))


def test_a_line_bound_to_two_takes_or_too_long_for_one_is_flagged():
    twice = [{"number": 2, "moments": ["m1"], "size": "CU", "take_s": 4, "lines": [{"line_id": "L1"}]}]
    first = {"number": 1, "moments": ["m1"], "size": "MS", "take_s": 4, "lines": [{"line_id": "L1"}]}
    moments = [{"id": "m1", "tier": "script", "serves": ["b0"], "who": ["A"]}]
    out = step.run({"scene": SCENE, "moments": moments, "cards": [first, *twice]})
    assert "line_spans_takes" in codes(out) and not out["ok"]
    long_scene = {**SCENE, "blocks": [SCENE["blocks"][0], {**SCENE["blocks"][1], "text": " ".join(["w"] * 20)}]}
    out = step.run({"scene": long_scene, "moments": moments, "cards": [first]})
    assert "line_too_long" in codes(out)
    assert "never cut by code" in next(f["fix"] for f in out["flags"] if f["code"] == "line_too_long")


def test_a_malformed_plan_is_reported_not_raised():
    out = step.run({"scene": SCENE, "moments": [{"id": "m1"}], "cards": []})
    assert not out["ok"] and "malformed" in out
