"""adam_coverage: the beats-by-people grid and the faces the analysis says must be seen (plan/2026-11-04c F2)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tests.adam import gold

from hiru_ai.steps.adam.adam_coverage import step

HERE = Path(__file__).resolve().parents[1]
SCENE = gold.scene("phone_call")


def run(plan: dict[str, Any]) -> dict[str, Any]:
    return step.run({"scene": SCENE, "plan": plan})


def holes(plan: dict[str, Any]) -> list[str]:
    return [h["cell"] for h in run(plan)["holes"]]


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["required"] > 0 and out["coverage"] == 1.0


def test_the_master_fills_every_required_cell():
    out = run(gold.master("phone_call"))
    assert out["holes"] == [] and out["coverage"] == 1.0 and out["required"] == out["filled"] == 11
    kinds = {c["kind"] for c in out["cells"]}
    assert {"turn", "other", "irony", "stake", "baseline", "key", "plant", "ending"} <= kinds


def test_the_grid_has_a_row_per_beat_and_a_column_per_person():
    grid = run(gold.master("phone_call"))["grid"]
    assert grid["people"] == ["Anudi", "Dasun"] and len(grid["beats"]) == 5
    assert grid["beats"][2]["turn"] and grid["beats"][2]["faces"]["Anudi"] == [7, 8]
    assert grid["beats"][3]["faces"]["Dasun"] == [11]  # Dasun reading her, the beat after the turn


def test_a_plan_without_dasuns_cards_shows_the_holes_by_name():
    plan = gold.master("phone_call")
    by_id = {m["id"]: m for m in plan["moments"]}
    dasun = {i for i, m in by_id.items() if m["tier"] != "script" and m.get("who") == ["Dasun"]}
    plan["cards"] = [{**c, "moments": [m for m in c["moments"] if m not in dasun]} for c in plan["cards"]]
    plan["cards"] = [c for c in plan["cards"] if c["moments"]]
    plan["cards"] = [{**c, "number": i} for i, c in enumerate(plan["cards"], start=1)]
    assert "other:2:dasun" in holes(plan) and "stake:dasun:before" in holes(plan)
    found = {h["cell"]: h for h in run(plan)["holes"]}
    assert "Dasun" in found["other:2:dasun"]["suggest"] and found["stake:dasun:before"]["who"] == "Dasun"
    assert run(plan)["coverage"] < 1.0


def test_a_two_shot_is_not_a_card_of_ones_own():
    plan = gold.master("phone_call")
    for card in plan["cards"]:
        if card.get("subject") == "Dasun" and card["number"] < 7:
            card["subject"] = "Anudi"  # his cards before the break are now on her; the opening two-shot still has him
    assert "stake:dasun:before" in holes(plan)


def test_the_irony_face_is_the_one_who_does_not_know():
    plan = gold.master("phone_call")
    for card in plan["cards"]:
        if card.get("subject") == "Dasun" and card["number"] >= 7:
            card["subject"] = "Anudi"
    assert "irony:0" in holes(plan)


def test_an_insert_never_shows_a_face():
    plan = gold.master("phone_call")
    plan["cards"][10]["size"] = "INSERT"  # Dasun reading her, as an insert
    assert "stake:dasun:after" not in holes(plan)  # card 13 is still his
    plan["cards"][12]["size"] = "INSERT"
    assert "stake:dasun:after" in holes(plan)


def test_a_plants_block_is_where_it_pays_off_not_where_the_card_is():
    plan = gold.master("phone_call")  # m2 is the plant: it serves b7, card 1 is the opening two-shot on beat 0
    out = run(plan)
    other = next(c for c in out["cells"] if c["id"] == "other:2:dasun")
    assert other["card"] == 11  # not card 1, whose opening two-shot would otherwise count


def test_a_solo_scene_has_no_other_person_and_a_stake_of_its_own():
    out = step.run({"scene": gold.scene("silent_morning"), "plan": gold.master("silent_morning")})
    assert out["holes"] == [] and not any(c["kind"] in ("other", "irony") for c in out["cells"])
    assert [c["id"] for c in out["cells"] if c["kind"] == "stake"] == ["stake:kasun"]  # no break: one stake cell


def test_a_voice_that_is_only_heard_has_no_face_to_cover():
    scene = {**SCENE, "cast": [*SCENE["cast"], "Father (on the phone)"]}
    out = step.run({"scene": scene, "plan": gold.master("phone_call")})
    assert out["holes"] == [] and not any("father" in c["id"] for c in out["cells"])


def test_the_required_faces_are_given_to_the_designer_before_any_card_exists():
    plan = gold.master("phone_call")
    out = step.run({"scene": SCENE, "analysis": plan["analysis"], "treatment": plan["treatment"]})
    assert len(out["required"]) == 11 and any("Dasun's face is seen at the turn" in line for line in out["required"])


def test_a_plan_that_cannot_be_read_is_reported_not_raised():
    out = step.run({"scene": SCENE, "plan": {"analysis": {}}})
    assert out["malformed"] and out["holes"] == [] and out["coverage"] == 1.0


def test_nothing_in_the_plan_is_changed():
    plan = gold.master("phone_call")
    before = copy.deepcopy(plan)
    run(plan)
    assert plan == before
