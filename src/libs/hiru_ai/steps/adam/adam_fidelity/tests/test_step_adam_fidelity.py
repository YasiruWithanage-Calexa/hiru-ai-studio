"""adam_fidelity: Adam may elaborate the picture and never invent the story (plan/2026-11-04b §4, §6.1)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_fidelity import step

HERE = Path(__file__).resolve().parents[1]

SCENE: dict[str, Any] = {
    "cast": ["Anudi", "Dasun"],
    "place": {"name": "a bench", "objects": ["bench", "lake", "phone"]},
    "blocks": [
        {"index": 0, "kind": "action", "text": "Anudi laughs on the bench, her phone face-down."},
        {"index": 1, "kind": "dialogue", "speaker": "Dasun", "line_id": "L1", "text": "hello there"},
        {"index": 2, "kind": "action", "text": "She picks up the phone."},
    ],
}
MOMENTS: list[dict[str, Any]] = [
    {"id": "m1", "tier": "script", "serves": ["b0"]},
    {"id": "m2", "tier": "script", "serves": ["b1"], "lines": ["L1"]},
    {"id": "m3", "tier": "script", "serves": ["b2"], "objects": ["phone"]},
]


def run(moments: list[dict[str, Any]], cards: list[dict[str, Any]] | None = None, scene: dict[str, Any] = SCENE):
    payload: dict[str, Any] = {"scene": scene, "moments": moments}
    if cards is not None:
        payload["cards"] = cards
    return step.run(payload)


def codes(result: dict[str, Any]) -> list[str]:
    return [b["code"] for b in result["breaks"]]


def with_extra(**moment: Any) -> list[dict[str, Any]]:
    return [*copy.deepcopy(MOMENTS), {"id": "x1", **moment}]


def test_the_example_runs_alone_and_passes():
    case = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    out = step.run(case)
    assert out["ok"] and out["breaks"] == [] and out["dropped"] == []


def test_a_plan_that_follows_the_script_passes():
    assert run(MOMENTS)["ok"]


def test_an_allowed_elaboration_with_a_person_present_passes():
    out = run(with_extra(tier="elaboration", kind="reaction", who=["Dasun"], serves=["b1"]))
    assert out["ok"], out["breaks"]
    assert out["counts"]["elaboration"] == 1


def test_a_new_person_is_refused_and_the_moment_is_dropped():
    out = run(with_extra(tier="elaboration", kind="reaction", who=["A stranger"], serves=["b1"]))
    assert codes(out) == ["new_person"] and out["dropped"] == ["x1"] and not out["send_back"]
    assert "stranger" in out["breaks"][0]["reason"] and "people present" in out["breaks"][0]["reason"]
    assert [m["id"] for m in out["kept"]] == ["m1", "m2", "m3"]


def test_the_tier_invention_is_refused_with_its_reason():
    out = run(with_extra(tier="invention", serves=["b1"], seen="her mother walks in"))
    assert codes(out) == ["invention"] and out["dropped"] == ["x1"]
    assert "new story" in out["breaks"][0]["reason"]


def test_a_kind_off_the_list_is_refused():
    out = run(with_extra(tier="elaboration", kind="flashback", who=["Anudi"], serves=["b0"]))
    assert codes(out) == ["bad_kind"]
    out = run(with_extra(tier="elaboration", serves=["b0"]))
    assert codes(out) == ["no_kind"]


def test_a_moment_that_serves_nothing_is_refused():
    out = run(with_extra(tier="elaboration", kind="atmosphere"))
    assert codes(out) == ["serves_nothing"]
    out = run(with_extra(tier="elaboration", kind="atmosphere", serves=["b9"]))
    assert codes(out) == ["unknown_serves"]


def test_an_object_that_does_not_fit_the_place_is_refused():
    out = run(with_extra(tier="elaboration", kind="insert_detail", objects=["a gun"], serves=["b0"]))
    assert codes(out) == ["new_object"]
    out = run(with_extra(tier="elaboration", kind="insert_detail", objects=["lake"], serves=["b0"]))
    assert out["ok"]  # on the location card
    out = run(with_extra(tier="elaboration", kind="plant", objects=["phone"], serves=["b2"]))
    assert out["ok"]  # named in the script
    out = run(with_extra(tier="elaboration", kind="plant", serves=["b2"]))
    assert codes(out) == ["no_object"]


def test_an_added_moment_may_not_carry_a_line():
    out = run(with_extra(tier="implied", serves=["b1"], who=["Dasun"], lines=["L1"]))
    assert "has_line" in codes(out)


def test_a_quoted_sentence_the_script_never_says_is_a_new_line_in_disguise():
    out = run(with_extra(tier="elaboration", kind="reaction", who=["Dasun"], serves=["b1"],
                         heard='he whispers "I never loved you"'))
    assert codes(out) == ["invented_line"]
    out = run(with_extra(tier="elaboration", kind="reaction", who=["Dasun"], serves=["b1"],
                         heard='he says "hello there" again'))
    assert out["ok"]  # the script's own words are not new


def test_a_script_block_left_out_repeated_or_reordered_sends_the_plan_back():
    out = run(MOMENTS[:2])
    assert "script_missing" in codes(out) and out["send_back"]
    out = run([*MOMENTS, {"id": "m4", "tier": "script", "serves": ["b0"]}])
    assert "script_repeated" in codes(out)
    out = run([MOMENTS[1], MOMENTS[0], MOMENTS[2]])
    assert "script_order" in codes(out)


def test_a_line_left_out_or_that_the_script_does_not_have_is_refused():
    no_line = copy.deepcopy(MOMENTS)
    no_line[1]["lines"] = []
    assert "line_missing" in codes(run(no_line))
    new_line = copy.deepcopy(MOMENTS)
    new_line[1]["lines"] = ["L1", "L99"]
    out = run(new_line)
    assert "unknown_line" in codes(out) and out["send_back"]
    assert "new line is never allowed" in next(b["reason"] for b in out["breaks"] if b["code"] == "unknown_line")


def test_cards_must_use_every_script_moment_once_and_bind_each_line_to_its_moment():
    cards = [{"number": 1, "moments": ["m1", "m2"], "size": "MS", "take_s": 6,
              "lines": [{"line_id": "L1"}]},
             {"number": 2, "moments": ["m3"], "size": "INSERT", "take_s": 4}]
    assert run(MOMENTS, cards)["ok"]
    assert "moment_missing" in codes(run(MOMENTS, cards[:1]))
    twice = [cards[0], {**cards[1], "moments": ["m3", "m1"]}]
    assert "moment_repeated" in codes(run(MOMENTS, twice))
    bad_line = [{**cards[0], "lines": [{"line_id": "L1"}, {"line_id": "L7"}]}, cards[1]]
    assert "unknown_line" in codes(run(MOMENTS, bad_line))
    unbound = [{**cards[0], "lines": []}, cards[1]]
    assert "line_missing" in codes(run(MOMENTS, unbound))
    spans = [cards[0], {**cards[1], "lines": [{"line_id": "L1"}]}]
    assert "line_repeated" in codes(run(MOMENTS, spans))
    elsewhere = [{**cards[0], "moments": ["m1"], "lines": []}, {**cards[1], "moments": ["m2", "m3"],
                                                                "lines": [{"line_id": "L1"}]}]
    assert run(MOMENTS, elsewhere)["ok"]
    misplaced = [{**cards[0], "moments": ["m1", "m3"], "lines": [{"line_id": "L1"}]},
                 {**cards[1], "moments": ["m2"], "lines": []}]
    assert "line_misplaced" in codes(run(MOMENTS, misplaced))


def test_a_malformed_plan_is_reported_not_raised():
    out = step.run({"scene": SCENE, "moments": [{"id": "m1"}]})
    assert not out["ok"] and out["breaks"][0]["code"] == "malformed" and out["send_back"]
