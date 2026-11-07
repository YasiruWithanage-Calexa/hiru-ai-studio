"""The gate (the planner's mend and checks by id, only new problems count), the delivery check (Nova W7) and the ledger
(W2, W5) (plan/2026-11-06e §4.6, Phase 2), on the lab's saved plans."""
from __future__ import annotations

import copy

import pytest

from contracts.zora.ledger import Ledger
from contracts.zora.tasks import Task
from hiru_ai.steps.zora.zora_board import gate
from hiru_ai.steps.zora.zora_deliver import step as deliver_step
from hiru_ai.steps.zora.zora_deliver.logic import report, retask, undelivered
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from hiru_ai.steps.zora.zora_ledger import step as ledger_step
from hiru_ai.steps.zora.zora_ledger.logic import change_lines
from tests.zora.world import SCENES, doc

# ── the gate ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SCENES)
def test_the_gate_judges_a_saved_plan_with_the_planners_own_checks(name: str):
    d = doc(name)
    j = gate.judge(d.scene, d.plan)
    assert not j.malformed and j.plan["shots"]
    assert all({"code", "sentence", "fix", "key"} <= set(p) for p in j.problems)


def test_a_problem_the_turn_did_not_cause_keeps_its_key_when_an_insert_renumbers_the_shots():
    k = ZoraKernel(doc("episode1"))
    before_handles = k.handles()
    before = gate.judge(k.scene, k.export(), mend=False)
    k.apply([{"op": "insert", "after": 1, "kind": "atmosphere", "what": "the room, before anyone speaks"}],
            by="conductor")
    after = gate.judge(k.scene, k.export(), mend=False)
    old_keys = {p["key"] for p in before.problems}
    moved = [p for p in after.problems if p["key"] not in old_keys and p["code"] != "added"]
    assert moved, "the insert shifts every later shot's number, so raw keys look new"
    new = gate.new_problems(before.problems, before_handles, after.problems, k.handles())
    assert all(p["shots"] == [2] or p["code"] == "added" for p in new), new


def test_a_fault_the_turn_brings_in_is_new_and_counts():
    k = ZoraKernel(doc("small"))
    handles = k.handles()
    before = gate.judge(k.scene, k.export(), mend=False)
    k.apply([{"op": "set", "shot": 3, "field": "over", "value": "Anudi"}], by="conductor")
    plan = k.export()
    plan["shots"][2]["blocks"] = [3]  # a fault no op can make: b2 is shown by no shot
    after = gate.judge(k.scene, plan, mend=False)
    new = gate.new_problems(before.problems, handles, after.problems, k.handles())
    assert any(p["code"] == "blocks" for p in new)


def test_a_take_the_person_set_is_kept_and_the_overrun_is_reported_with_the_way_out():
    k = ZoraKernel(doc("father_refuses"))  # S12 shows b6, a line that needs a 6 s take
    k.apply([{"op": "retime", "shot": 12, "take_s": 4}], by="conductor")
    plan = k.export()
    judged = gate.judge(k.scene, plan)
    assert judged.plan["shots"][11]["take_s"] == 6  # the mend lengthens it
    kept, notes = gate.protect(plan, judged, {(6,): 4})
    assert kept["shots"][11]["take_s"] == 4
    assert notes and "you set a 4 s take" in notes[0] and "split it at a block" in notes[0]


def test_a_line_longer_than_any_take_is_reported_never_trimmed():
    problems = [{"code": "clock", "fix": "report", "sentence": "S05 needs 9.4 s and cannot be cut.", "shots": [5],
                 "key": "clock:5"},
                {"code": "clock", "fix": "mend", "sentence": "S06 needs 5 s", "shots": [6], "key": "clock:6"}]
    (line,) = gate.overruns(problems)
    assert line.startswith("S05 needs 9.4 s") and "a shorter line in their own words" in line


# ── delivery ──────────────────────────────────────────────────────────────────────────────────────


def test_a_declared_effect_that_did_not_change_is_retasked_once_and_then_reported():
    k = ZoraKernel(doc())
    before = k.export(handles=True)
    k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "135mm"}], by="author")
    after = k.export(handles=True)
    tasks = [Task(("shot.lens", "shot.angle"), (), instruction="colder")]
    missing = undelivered(tasks, before, after)
    assert missing == ["shot.angle"]
    (again,) = retask(missing, tasks, locked=[], handles=k.handles())
    assert again.writes == ("shot.angle",) and again.origin == "delivery"
    assert "HAS NOT CHANGED YET" in again.instruction
    assert report(missing, tasks, locked=[], handles=k.handles()) == ["the shots' angle"]


def test_an_effect_asked_for_on_named_shots_must_change_on_those_shots():
    k = ZoraKernel(doc())
    before = k.export(handles=True)
    k.apply([{"op": "set", "shot": 9, "field": "lens", "value": "135mm"}], by="author")
    after = k.export(handles=True)
    on_three = [Task(("shot.lens",), (before["shots"][2]["_h"],))]
    assert undelivered(on_three, before, after) == ["shot.lens"]


def test_a_locked_effect_is_never_retasked_and_says_why_and_the_end_state_is_the_persons():
    k = ZoraKernel(doc(locked=["S03.lens"]))
    before = k.export(handles=True)
    three = before["shots"][2]["_h"]
    tasks = [Task(("shot.lens",), (three,)), Task(("end_state",), ())]
    missing = undelivered(tasks, before, before)
    assert retask(missing, tasks, locked=k.locked, handles=k.handles()) == []
    assert report(missing, tasks, locked=k.locked, handles=k.handles()) == [
        "the shots' lens (you set it yourself, so the team could not change it)",
        "how the scene ends (what the next scene starts from) (only your own words can change this: say how it "
        "should end)"]


def test_the_deliver_step_reads_handles_from_the_plans():
    k = ZoraKernel(doc("small"))
    before = k.export(handles=True)
    out = deliver_step.run({"before": before, "after": before, "tasks": [{"writes": ["shot.why"], "scope": ["h2"]}]})
    assert out["missing"] == ["shot.why"] and out["retask"][0]["scope"] == ["h2"]


# ── the ledger ────────────────────────────────────────────────────────────────────────────────────


def test_the_ledger_names_what_changed_by_treatment_sequence_and_shot_with_the_numbers_the_person_now_sees():
    k = ZoraKernel(doc())
    before = k.export(handles=True)
    k.apply([{"op": "treatment.set", "field": "key_image", "value": "his hands on the envelope"},
             {"op": "insert", "after": 1, "kind": "atmosphere", "what": "the office, empty"},
             {"op": "set", "shot": 3, "field": "lens", "value": "135mm"},
             {"op": "sequence.set", "id": "B", "field": "title", "value": "The offer"}], by="conductor")
    lines = change_lines(before, k.export(handles=True))
    text = [f"{x.where}: {x.text}" for x in lines]
    assert text[0] == "Treatment: key image is now “his hands on the envelope”"
    assert "Sequence B: title is now “The offer”" in text
    assert any(t.startswith("S02: new shot (atmosphere") for t in text)
    assert any(t.startswith("S04: (was S03) lens") for t in text)
    assert not any(t.startswith(("S05", "S06", "S10")) for t in text)  # renumbered, not changed


def test_a_turn_that_tried_and_changed_nothing_says_so_and_one_that_never_tried_does_not():
    plan = ZoraKernel(doc("small")).export(handles=True)
    out = ledger_step.run({"before": plan, "after": copy.deepcopy(plan), "attempted": True,
                           "refused": ["S09: there is no S09: the scene has S01–S03"]})
    assert out["ops"]["nothing_changed"] is True
    assert any(c.startswith("NOTHING CHANGED THIS TURN") for c in out["context"])
    assert any(c.startswith("REQUESTED BUT NOT APPLIED") for c in out["context"])
    hello = ledger_step.run({"before": plan, "after": copy.deepcopy(plan), "attempted": False})
    assert hello["context"] == [] and hello["ops"]["nothing_changed"] is True


def test_an_overrun_reaches_the_reply_as_a_report_with_its_way_out_and_an_offer_is_not_a_change():
    led = Ledger(overruns=["S05 needs 9.4 s and cannot be cut. The way out is the person's: ..."],
                 offer="it would rewrite 9 of the scene's 15 shots.", attempted=True, undone=True)
    ctx = "\n".join(led.context())
    assert "reported, never trimmed" in ctx and "OFFERED, NOT DONE" in ctx and "NOTHING CHANGED" not in ctx
    assert led.gate()["overruns"] and led.event()["nothing_changed"] is True


def test_one_reason_for_many_refused_ops_is_said_once_and_an_old_fault_is_a_separate_note():
    plan = ZoraKernel(doc("small")).export(handles=True)
    why = "the ir.set: the plan would not read (S07 names a line the scene does not have)"
    out = ledger_step.run({"before": plan, "after": copy.deepcopy(plan), "attempted": True,
                           "team_refused": [why] * 10, "already": ["S07 names a line the scene does not have"] * 2})
    assert out["ops"]["refused"] == [why]
    assert out["gate"]["already"] == ["S07 names a line the scene does not have"]
    assert any(c.startswith("ALREADY IN THE PLAN BEFORE THIS TURN") for c in out["context"])
