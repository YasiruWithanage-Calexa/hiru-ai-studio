"""Phase 0 and 1 exit checks (plan/2026-11-04b §10) on the gold set (tests/eval/adam/).

* every master passes the code rules (fidelity, fit, continuity, feasibility) and out-scores the classic baseline;
* the test scene is the §9 plan: 13 cards, 66 s, nothing in it new story;
* a hand-made plan with an invented line, person or event is refused with its reason.

They show the masters are consistent and that the code tells a vivid plan from a flat one. Whether a master is GOOD
is a Hiru director's judgement, recorded in its `status` (all are drafts today; see tests/eval/adam/README.md).
"""
from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from tests.adam import gold

from contracts.adam.plan import AdamPlan, SceneScript
from contracts.veo import VEO_DURATIONS
from hiru_ai.core import parts

NAMES = gold.names()


def run(step_id: str, scene: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", step_id, "step").run({"scene": scene, "plan": plan}))


def test_there_are_at_least_five_masters_in_the_card_format():
    assert len(NAMES) >= 5 and "phone_call" in NAMES
    for name in NAMES:
        AdamPlan.model_validate(gold.master(name))
        SceneScript.model_validate(gold.scene(name))
        assert (gold.GOLD / "baselines" / f"{name}.yaml").is_file()


def test_every_master_says_whether_a_director_has_approved_it():
    for name in NAMES:
        header = yaml.safe_load((gold.GOLD / "masters" / f"{name}.yaml").read_text(encoding="utf-8"))
        assert header["status"] in ("draft", "approved"), name
        assert header["director_note"].strip(), f"{name} has no director's note on WHY"
        assert header["scene"] == name


@pytest.mark.parametrize("name", NAMES)
def test_a_master_passes_every_code_rule(name: str):
    scene, plan = gold.scene(name), gold.master(name)
    fidelity = run("adam_fidelity", scene, plan)
    assert fidelity["ok"], fidelity["breaks"]
    fit = run("adam_fit", scene, plan)
    assert fit["ok"], fit["issues"]
    assert all(card["take_s"] in VEO_DURATIONS for card in fit["cards"])
    continuity = run("adam_continuity", scene, plan)
    assert continuity["ok"], continuity["issues"]
    feasibility = run("adam_feasibility", scene, plan)
    assert feasibility["ok"], [f for f in feasibility["flags"] if not f["addressed"]]


@pytest.mark.parametrize("name", NAMES)
def test_a_master_never_trims_a_line_and_binds_every_line_once(name: str):
    scene, plan = gold.scene(name), gold.master(name)
    bound = [cl["line_id"] for card in plan["cards"] for cl in card.get("lines", [])]
    assert bound == [b["line_id"] for b in scene["blocks"] if b["kind"] == "dialogue"]
    fit = run("adam_fit", scene, plan)
    assert all(ln["overrun_s"] == 0 for card in fit["cards"] for ln in card["lines"])


@pytest.mark.parametrize("name", NAMES)
def test_a_master_beats_the_classic_baseline_on_craft(name: str):
    scene, master, base = gold.scene(name), gold.master(name), gold.baseline_plan(name)
    adam, classic = run("adam_score", scene, master), run("adam_score", scene, base)
    assert not adam["loss"], adam["loss_reasons"]
    assert adam["percent"] == 100.0, [(s["signal"], c["why"]) for s in adam["signals"] for c in s["checks"]
                                      if not c["ok"]]
    assert adam["score"] > classic["score"], (adam["percent"], classic["percent"])
    chosen = parts.module("step", "adam_score", "step").run({"scene": scene, "plans": [base, master]})["chosen"]
    assert chosen == 1  # the master wins the pick, whichever order they come in


@pytest.mark.parametrize("name", NAMES)
def test_the_baseline_is_a_valid_plan_that_follows_the_script(name: str):
    assert run("adam_fidelity", gold.scene(name), gold.baseline_plan(name))["ok"]


def test_the_test_scene_is_the_plans_section_nine():
    plan = AdamPlan.model_validate(gold.master("phone_call"))
    assert len(plan.cards) == 13
    assert [c.take_s for c in plan.cards] == [6, 4, 4, 4, 6, 4, 8, 4, 4, 4, 4, 6, 8]
    assert sum(c.take_s for c in plan.cards) == 66  # "Total 66 s"
    assert [c.size for c in plan.cards][:3] == ["MWS", "CU", "CU"] and plan.cards[3].size == "INSERT"
    fit = run("adam_fit", gold.scene("phone_call"), gold.master("phone_call"))
    assert fit["runtime_s"] == 66
    assert plan.cards[7].rhythm_break and plan.cards[7].size == "ECU"  # "the rhythm break (shot 8)"
    assert plan.treatment.plant and plan.treatment.plant.payoff_moment == "m13"
    # IMPLIED and ELABORATION are labelled; nothing is invention
    assert {m.tier for m in plan.moments} == {"script", "implied", "elaboration"}


def test_the_classic_baseline_for_the_test_scene_is_five_or_six_shots():
    assert 5 <= len(gold.baseline_shots("phone_call")) <= 6  # "5-6" (plan §1)


# ── Phase 1 exit: an invented line, person or event is refused with its reason ──────────────────


def hand_made(**edit: Any) -> dict[str, Any]:
    """The test scene's master with one thing added or changed by hand."""
    plan = copy.deepcopy(gold.master("phone_call"))
    plan["moments"].append({"id": "x1", "tier": "elaboration", "serves": ["b9"], **edit})
    return plan


def refusals(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out = run("adam_fidelity", gold.scene("phone_call"), plan)
    assert not out["ok"]
    return out["breaks"]


def test_a_new_person_is_refused_with_its_reason():
    breaks = refusals(hand_made(kind="reaction", who=["Anudi's mother"], seen="her mother watches from the path"))
    assert [b["code"] for b in breaks] == ["new_person"]
    assert "not in the scene" in breaks[0]["reason"] and breaks[0]["fix"] == "drop"


def test_an_invented_line_is_refused_whichever_way_it_is_smuggled_in():
    quoted = refusals(hand_made(kind="reaction", who=["Dasun"], heard='Dasun murmurs "I always knew about this"'))
    assert [b["code"] for b in quoted] == ["invented_line"]
    spoken = refusals(hand_made(kind="reaction", who=["Dasun"], lines=["L1"]))
    assert "has_line" in [b["code"] for b in spoken]
    plan = hand_made(kind="reaction", who=["Dasun"])
    plan["moments"][3]["lines"] = ["L1", "L77"]  # m4 is a script moment: a line the script does not have
    codes = [b["code"] for b in run("adam_fidelity", gold.scene("phone_call"), plan)["breaks"]]
    assert "unknown_line" in codes


def test_an_invented_event_is_refused_as_invention_or_as_a_kind_off_the_list():
    labelled = refusals(hand_made(tier="invention", seen="the father arrives in person"))
    assert [b["code"] for b in labelled] == ["invention"] and "new story" in labelled[0]["reason"]
    off_list = refusals(hand_made(kind="flashback", who=["Anudi"], seen="a flashback to her wedding"))
    assert [b["code"] for b in off_list] == ["bad_kind"] and "allowed elaboration" in off_list[0]["reason"]
    stray = refusals(hand_made(kind="insert_detail", objects=["a pistol"], seen="a pistol on the bench"))
    assert [b["code"] for b in stray] == ["new_object"] and "fit the place" in stray[0]["reason"]


def test_dropping_what_was_refused_leaves_a_plan_that_passes():
    scene = gold.scene("phone_call")
    plan = hand_made(kind="reaction", who=["Anudi's mother"], seen="her mother watches")
    out = run("adam_fidelity", scene, plan)
    assert out["dropped"] == ["x1"]
    cleaned = {**plan, "moments": out["kept"]}
    assert run("adam_fidelity", scene, cleaned)["ok"]


def test_dropping_a_script_moment_sends_the_plan_back():
    plan = copy.deepcopy(gold.master("phone_call"))
    plan["moments"] = [m for m in plan["moments"] if m["id"] != "m9"]  # the father's line
    plan["cards"] = [c for c in plan["cards"] if c["number"] != 7]
    out = run("adam_fidelity", gold.scene("phone_call"), plan)
    assert out["send_back"] and {"script_missing", "line_missing"} <= {b["code"] for b in out["breaks"]}
