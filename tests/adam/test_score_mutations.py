"""Phase 1 exit (plan/2026-11-04c §5): the craft score can be trusted.

Every gold master is broken on purpose (tests/adam/mutants.py) and the score must notice, by at least one point of
100. A mutant that survives is a blind spot and fails under its own name. The numbers of §2.1 are held here too: the
bare master no longer scores 100 %, and the saved plan of the third live run reads well below the master.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from tests.adam import gold, mutants

from contracts.adam.stored import StoredPlan
from hiru_ai.core import parts

NAMES = gold.names()
MIN_DROP = 1.0  # points of 100


def cases() -> list[tuple[str, str]]:
    return [(name, label) for name in NAMES for label in mutants.mutants(name)]


def score(scene: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", "adam_score", "step").run({"scene": scene, "plan": plan}))


@pytest.mark.parametrize(("name", "label"), cases())
def test_the_score_notices_every_mutant(name: str, label: str):
    scene, master = gold.scene(name), gold.master(name)
    base, broken = mutants.percent(scene, master), mutants.percent(scene, mutants.mutants(name)[label])
    if (name, label) in mutants.BLIND_SPOTS:
        assert base - broken < MIN_DROP, f"{name}/{label} is now caught: remove it from BLIND_SPOTS"
        return
    assert base - broken >= MIN_DROP, f"mutant {label} of {name} survives: {base} -> {broken}"


def test_a_blind_spot_names_a_mutant_that_exists():
    for name, label in mutants.BLIND_SPOTS:
        assert (name, label) in cases()


def test_the_master_outscores_every_mutant_and_the_mutation_score_is_full():
    killed = total = 0
    for name in NAMES:
        for label, (base, broken) in mutants.killed(name).items():
            total += 1
            killed += int(base - broken >= MIN_DROP)
            assert base > broken or (name, label) in mutants.BLIND_SPOTS, f"{name}/{label}"
    assert total >= 25
    assert total - killed == len(mutants.BLIND_SPOTS)  # only the named blind spots survive


def test_merges_that_stay_on_one_face_and_one_beat_are_not_faults():
    # The plan's rule is one main job per card; two cards on the same face and beat were one job to begin with. They are
    # listed, not scored, so nobody can say a mutant was quietly dropped.
    assert mutants.equivalent_merges("phone_call") == ["merge_cards_1_2", "merge_cards_4_5", "merge_cards_9_10"]


def test_the_bare_master_no_longer_scores_a_hundred():
    scene = gold.scene("phone_call")
    assert score(scene, gold.master("phone_call"))["percent"] == 100.0
    assert mutants.percent(scene, mutants.mutants("phone_call")["bare"]) < 80.0  # it was 100 % before plan 2026-11-04c


def test_the_third_live_runs_plan_reads_far_below_the_master():
    saved = json.loads((gold.GOLD / "live" / "phone_call.json").read_text(encoding="utf-8"))
    plan = StoredPlan.model_validate(saved).plan().model_dump(mode="json", by_alias=True)
    scene = gold.scene("phone_call")
    run3, master = score(scene, plan), score(scene, gold.master("phone_call"))
    assert master["percent"] - run3["percent"] >= 15.0, (master["percent"], run3["percent"])
    assert run3["fidelity_breaks"] == 0  # the fidelity check was happy with it, as it was before
    fit = dict(parts.module("step", "adam_fit", "step").run({"scene": scene, "plan": plan}))
    refused = [(i["code"], i["line_id"]) for i in fit["issues"] if i["level"] == "overrun"]
    assert refused == [("bad_listener", "L6")]  # and now the clock refuses "I'll come" over her own face (F6)
    holes = {c["why"] for s in run3["signals"] if s["signal"] == "coverage" for c in s["checks"] if not c["ok"]}
    assert any("Dasun's face is seen at the turn" in why for why in holes)
    assert any("Dasun has a card of their own before the break" in why for why in holes)
    off = [c["why"] for s in run3["signals"] if s["signal"] == "line_placement" for c in s["checks"] if not c["ok"]]
    assert any("L6" in why and "own face" in why for why in off)  # "I'll come" over her own face
