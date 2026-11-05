"""adam_score: code rewards craft; a fidelity break or an overrun loses first (plan/2026-11-04b §6.2)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_score import step

HERE = Path(__file__).resolve().parents[1]

SCENE: dict[str, Any] = {
    "cast": ["Anudi", "Dasun"],
    "place": {"objects": ["bench", "phone"]},
    "blocks": [
        {"index": 0, "kind": "action", "text": "They laugh on the bench, her phone face-down."},
        {"index": 1, "kind": "dialogue", "speaker": "Dasun", "line_id": "L1", "text": "one two three"},
        {"index": 2, "kind": "action", "text": "The phone rings. She turns it face-down."},
    ],
}


def make_plan() -> dict[str, Any]:
    return {
        "analysis": {
            "about": "x", "value": {"start": "joy", "end": "dread"},
            "beats": [{"blocks": [0, 1]}, {"blocks": [2], "turn": True, "reactor": "Anudi"}],
            "pov_owner": {"start": "Anudi"}, "baseline": {"blocks": [0]}, "key_moment": {"block": 2}},
        "treatment": {
            "name": "t", "concept": "c", "off_speaker": True,
            "sections": [{"beats": [0], "size_band": ["MWS", "CU"]}, {"beats": [1], "size_band": ["CU", "ECU"]}],
            "plant": {"object": "phone", "plant_moment": "m2", "payoff_moment": "m5"},
            "rhythm_break": {"moment": "m4", "kind": "silence"}, "ending_moment": "m5"},
        "moments": [
            {"id": "m1", "tier": "script", "serves": ["b0"], "who": ["Anudi", "Dasun"], "seconds_need": 3.0},
            {"id": "m2", "tier": "elaboration", "kind": "plant", "serves": ["b2"], "objects": ["phone"],
             "seconds_need": 0},
            {"id": "m3", "tier": "script", "serves": ["b1"], "who": ["Dasun", "Anudi"], "lines": ["L1"],
             "seconds_need": 2.0},
            {"id": "m4", "tier": "elaboration", "kind": "hold", "serves": ["b2"], "who": ["Anudi"],
             "seconds_need": 2.0},
            {"id": "m6", "tier": "elaboration", "kind": "reaction", "serves": ["b2"], "who": ["Dasun"],
             "seconds_need": 2.0},
            {"id": "m5", "tier": "script", "serves": ["b2"], "who": ["Anudi"], "objects": ["phone"],
             "seconds_need": 2.5}],
        "cards": [
            {"number": 1, "moments": ["m1"], "size": "MWS", "arrangement": "two", "take_s": 4,
             "cut_in": {"link": "cut"}},
            {"number": 2, "moments": ["m2", "m3"], "size": "CU", "subject": "Anudi", "take_s": 4,
             "lines": [{"line_id": "L1", "on_speaker": False, "over_whom": "Anudi"}],
             "cut_in": {"link": "cut", "motive": "line"}},
            {"number": 3, "moments": ["m4"], "size": "ECU", "take_s": 4, "rhythm_break": True,
             "cut_in": {"link": "cut", "motive": "look"}},
            {"number": 4, "moments": ["m6"], "size": "CU", "subject": "Dasun", "take_s": 4,
             "cut_in": {"link": "cut", "motive": "look"}},
            {"number": 5, "moments": ["m5"], "size": "CU", "arrangement": "single", "take_s": 4,
             "cut_in": {"link": "cut", "motive": "action"}}],
        "sound_map": {"silences": ["m4"]},
    }


def run(plan: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return step.run({"scene": SCENE, "plan": plan or make_plan(), **extra})


def signal(out: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in out["signals"] if s["signal"] == name)


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert not out["loss"] and out["max"] > 0


def test_a_well_made_plan_earns_every_point_and_each_point_names_its_card():
    out = run()
    assert not out["loss"], out["loss_reasons"]
    bad = [(s["signal"], c["why"]) for s in out["signals"] for c in s["checks"] if not c["ok"]]
    assert out["score"] == out["max"] and bad == []
    ended = signal(out, "ending")["checks"][0]
    assert ended["card"] == 5 and ended["points"] == 1.0 and "ending image" in ended["why"]


def test_points_add_up_from_the_checks():
    out = run()
    assert round(sum(c["points"] for s in out["signals"] for c in s["checks"]), 3) == out["score"]


def test_a_flat_plan_scores_less_and_says_what_it_lacks():
    plan = make_plan()
    plan["cards"][2]["rhythm_break"] = False
    plan["treatment"]["plant"]["payoff_moment"] = ""
    plan["cards"][4]["cut_in"]["motive"] = ""
    plan["sound_map"] = {}
    flat = run(plan)
    assert flat["score"] < run()["score"] and not flat["loss"]
    assert [c["ok"] for c in signal(flat, "one_rhythm_break")["checks"]] == [False, False, True]
    assert "never pays off" in signal(flat, "plant_paid_off")["checks"][0]["why"]
    assert "no motive" in signal(flat, "motivated_cuts")["checks"][-1]["why"]
    assert "does not change state" in signal(flat, "sound")["checks"][0]["why"]


def test_a_dull_plan_with_no_defects_does_not_beat_a_vivid_one():
    vivid = run()
    dull = make_plan()
    dull["moments"] = [m for m in dull["moments"] if m["tier"] == "script"]
    dull["cards"] = [{"number": 1, "moments": ["m1", "m3"], "size": "MS", "take_s": 6, "lines": [{"line_id": "L1"}]},
                     {"number": 2, "moments": ["m5"], "size": "MS", "take_s": 4, "cut_in": {"motive": "action"}}]
    dull["treatment"].update({"plant": None, "rhythm_break": None, "ending_moment": "", "off_speaker": False})
    out = run(dull)
    assert not out["loss"] and out["score"] < vivid["score"]  # zero defects, no craft


def test_a_fidelity_break_is_a_loss_before_any_craft_counts():
    plan = make_plan()
    plan["moments"].append({"id": "m9", "tier": "elaboration", "kind": "reaction", "who": ["A stranger"],
                            "serves": ["b0"]})
    out = run(plan)
    assert out["loss"] and out["fidelity_breaks"] == 1 and "fidelity" in out["loss_reasons"][0]


def test_an_overrun_is_a_loss():
    plan = make_plan()
    plan["cards"][0]["take_s"] = 4
    plan["moments"][0]["seconds_need"] = 9.0
    out = run(plan)
    assert out["loss"] and out["overruns"] >= 1


def test_a_line_over_its_own_speakers_mouth_is_penalised():
    plan = make_plan()
    plan["cards"][1]["lines"][0]["over_whom"] = "Dasun"  # off the speaker, but the speaker is in frame
    out = run(plan)
    assert [c["ok"] for c in signal(out, "line_placement")["checks"]] == [False, False]
    assert "the speaker's own face" in signal(out, "line_placement")["checks"][1]["why"]


def test_a_line_over_no_one_or_an_object_is_penalised():
    plan = make_plan()
    plan["cards"][1]["lines"][0]["over_whom"] = ""  # over an insert of her hands, over the phone: no listener
    out = run(plan)
    assert [c["ok"] for c in signal(out, "line_placement")["checks"]] == [False, False]
    assert "no one" in signal(out, "line_placement")["checks"][1]["why"]


def test_adjacent_cards_that_repeat_each_other_lose_variety():
    plan = make_plan()
    plan["cards"][3].update({"size": "ECU", "subject": "Anudi"})  # card 3 is ECU on Anudi too
    out = run(plan)
    assert not all(c["ok"] for c in signal(out, "variety")["checks"])


def test_a_signal_that_does_not_apply_to_the_scene_is_left_out_not_given_free():
    plan = make_plan()
    plan["treatment"]["plant"] = None
    out = run(plan)
    sig = signal(out, "plant_paid_off")
    assert not sig["applicable"] and out["max"] == run()["max"] - 1


def test_weights_scale_a_signal():
    out = run(weights={"ending": 3.0})
    assert out["max"] == run()["max"] + 2


def test_the_better_of_two_plans_is_chosen_and_a_tie_keeps_the_first():
    good, flat = make_plan(), make_plan()
    flat["cards"][2]["rhythm_break"] = False
    out = step.run({"scene": SCENE, "plans": [flat, good]})
    assert out["chosen"] == 1 and out["results"][1]["score"] > out["results"][0]["score"]
    assert step.run({"scene": SCENE, "plans": [good, copy.deepcopy(good)]})["chosen"] == 0
    broken = make_plan()
    broken["moments"].append({"id": "m9", "tier": "invention", "serves": ["b0"]})
    assert step.run({"scene": SCENE, "plans": [broken, flat]})["chosen"] == 1  # craft cannot rescue a break


def test_a_malformed_plan_is_a_loss_not_an_exception():
    out = step.run({"scene": SCENE, "plan": {"analysis": {}}})
    assert out["loss"] and out["malformed"]
