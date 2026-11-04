"""director_board against the engine it replaces, and the rules of a panel (members come and go in YAML)."""
from __future__ import annotations

import dataclasses
from typing import Any

from director_chat.engine import agents as legacy

from contracts.directorops import OP_FIELDS
from hiru_ai.core import llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.registry import Registry
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.panels.director_board import graph

SCENE = "S01 WIDE 6s\nS02 CU 8s"
CHARTERS = {"cinematography": "You are the cinematographer", "timing": "You are the editor",
            "sound": "You are the sound designer", "continuity": "You are the continuity supervisor"}


def op(**kw: Any) -> dict[str, Any]:
    return {**dict.fromkeys(OP_FIELDS), "op": "set", **kw}


def route_of(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return next((craft for craft, mark in CHARTERS.items() if mark in system), "advisor")


def model(**routes: list[Any]) -> RoutedChatModel:
    return RoutedChatModel(routes={k: list(v) for k, v in routes.items()}, choose=route_of)


def run(tasks: list[dict[str, Any]], replies: dict[str, list[Any]], manifest: PanelManifest | None = None,
        registry: Registry | None = None) -> Any:
    with llm.use_models(model(**replies)):
        return graph.build(RunContext(), registry, manifest).invoke(
            {"brief": {"scene_text": SCENE, "lead_charter": "Warm."}, "tasks": tasks})


def legacy_run(tasks: list[dict[str, Any]], replies: dict[str, list[Any]]) -> Any:
    queues = {k: list(v) for k, v in replies.items()}

    def ask_for(agent: str) -> Any:
        def ask(system: str, user: str) -> dict[str, Any]:
            if not queues.get(agent):
                raise RuntimeError("down")
            return queues[agent].pop(0)  # type: ignore[no-any-return]
        return ask

    outputs = legacy.run_specialists(ask_for, tasks, scene_text=SCENE, lead_charter="Warm.")
    return outputs, legacy.settle(outputs)


TASKS = [{"agent": "cinematography", "shots": [1, 2], "instruction": "frame"},
         {"agent": "sound", "shots": [1], "instruction": "quiet"},
         {"agent": "timing", "shots": [], "instruction": "cuts"}]
REPLIES = {
    "cinematography": [{"ops": [op(shot=1, field="framing", value="CU"),
                                op(shot=2, field="sound_mode", value="ambient")],
                        "note": "Closer."}],
    "sound": [{"ops": [op(shot=1, field="sound_mode", value="silent"), op(shot=3, field="framing", value="MS")],
               "note": "Quiet, and I tried shot 3."}],
    "timing": [{"ops": [op(op="split", shot=2, at_block=1)], "note": "Cut early."}],
}


def test_the_panel_gives_the_same_outcome_as_the_engine():
    got = run(TASKS, REPLIES)
    outputs, settled = legacy_run(TASKS, REPLIES)
    assert [(o.agent, o.ops, o.note) for o in got["outputs"]] == [(o.agent, o.ops, o.note) for o in outputs]
    assert got["settled"].ops == settled.ops and got["settled"].disagreements == settled.disagreements
    # shot 2's sound mode was written by the cinematographer alone, so it lands; shot 1's is the sound designer's
    assert [(a, o["shot"], o["value"]) for a, o in got["settled"].ops if o.get("field") == "sound_mode"] == [
        ("cinematography", 2, "ambient"), ("sound", 1, "silent")]


def test_a_collision_goes_to_the_owner_and_the_rival_is_heard():
    replies = {"cinematography": [{"ops": [op(shot=1, field="sound_mode", value="ambient")],
                                   "note": "Keep the street."}],
               "sound": [{"ops": [op(shot=1, field="sound_mode", value="silent")], "note": "Quiet."}]}
    tasks = TASKS[:2]
    got = run(tasks, replies)
    _, settled = legacy_run(tasks, replies)
    assert [(a, o["value"]) for a, o in got["settled"].ops] == [("sound", "silent")]
    assert got["settled"].ops == settled.ops and got["settled"].disagreements == settled.disagreements
    assert [p["who"] for p in got["settled"].disagreements[0]["positions"]] == ["Sound", "Cinematography"]


def test_a_specialist_that_cannot_answer_adds_nothing_and_the_others_still_count():
    replies = {k: v for k, v in REPLIES.items() if k != "sound"}
    got = run(TASKS, replies)
    outputs, settled = legacy_run(TASKS, replies)
    assert [(o.agent, o.ops) for o in got["outputs"]] == [(o.agent, o.ops) for o in outputs]
    assert got["outputs"][1].ops == [] and got["settled"].ops == settled.ops


def test_operations_outside_the_task_are_dropped_and_a_task_gets_six_at_most():
    many = {"cinematography": [{"ops": [op(shot=n, field="framing", value="CU") for n in range(1, 10)],
                                "note": "x" * 400}]}
    task = [{"agent": "cinematography", "shots": list(range(1, 9)), "instruction": ""}]
    got = run(task, many)
    assert len(got["outputs"][0].ops) == 6 and len(got["outputs"][0].note) == 300
    assert got["outputs"][0].ops == legacy_run(task, many)[0][0].ops


def test_the_ownership_table_is_the_manifest_and_agrees_with_the_built_in_rule():
    kit = graph.PanelKit(graph.ID)
    owners = graph.ownership(kit)
    rules = parts.step("board_settle")
    cases = [op(field="sound_mode"), op(field="framing"), op(field="title"), op(op="beat.set", field="camera"),
             op(op="beat.set", field="action"), op(op="split"), op(op="merge"), op(op="regroup"),
             op(op="set_join"), op(op="insert")]
    for case in cases:
        assert rules.owner_by_table(case, owners) == rules.owner_of(case), case


def test_allowed_operations_come_from_the_manifest():
    kit = graph.PanelKit(graph.ID)
    assert graph.allowed_ops(kit.manifest) == legacy.ALLOWED


def test_removing_a_member_removes_it_from_the_graph_and_the_rest_still_runs():
    manifest = graph.PanelKit(graph.ID).manifest
    smaller = manifest.model_copy(update={"members": [m for m in manifest.members if m.label != "sound"]})
    got = run(TASKS, REPLIES, smaller)
    assert [o.agent for o in got["outputs"]] == ["cinematography", "sound", "timing"]
    assert got["outputs"][1].ops == [] and got["outputs"][1].note == ""  # no member for that craft
    assert {o["field"] for _, o in got["settled"].ops if o["op"] == "set"} == {"framing", "sound_mode"}


def test_a_member_switched_off_is_left_out_without_failing():
    reg = parts._registry()
    clone = Registry(reg.root, reg.package)
    clone.components = dict(reg.components)
    comp = clone.components[("agent", "sound_designer")]
    clone.components[("agent", "sound_designer")] = dataclasses.replace(
        comp, manifest=comp.manifest.model_copy(update={"status": "disabled"}))
    got = run(TASKS, REPLIES, registry=clone)
    assert got["outputs"][1].ops == []
    assert "sound_designer" not in [m.agent for m in graph.PanelKit(graph.ID, registry=clone).members()]
    assert not [p for p in clone.validate() if p.where == "panel director_board" and p.level == "error"]


def test_no_tasks_settle_to_nothing():
    got = run([], {})
    assert got["outputs"] == [] and got["settled"].ops == [] and got["settled"].disagreements == []


def test_advisors_are_heard_only_when_they_disagree():
    reviews = [{"name": "Nimali", "charter": "Spare.", "summary": "S01 CU"},
               {"name": "Ruwan", "charter": "Lush.", "summary": "S01 CU"},
               {"name": "Mala", "charter": "Brief.", "summary": "S01 CU"}]
    replies = [{"agrees": False, "view": "I would hold the wide." + " x" * 300},
               {"agrees": True, "view": "fine"}, {"agrees": False, "view": "   "}]
    out = []
    for review, reply in zip(reviews, replies, strict=True):  # one at a time: parallel advisors answer in no set order
        with llm.use_models(model(advisor=[reply])):
            out += graph.build(RunContext()).invoke({"brief": {"scene_text": SCENE}, "reviews": [review]})["advice"]
    assert out[0]["who"] == "Nimali" and len(out[0]["text"]) == 400 and out[1:] == [None, None]
    again = iter([replies[0]])
    assert legacy.advisor_review(lambda s, u: next(again), advisor_name="Nimali", advisor_charter="Spare.",
                                 scene_text=SCENE, summary="S01 CU") == out[0]


def test_an_advisor_that_cannot_answer_is_left_out():
    got = graph.build(RunContext()).invoke(
        {"brief": {"scene_text": SCENE}, "reviews": [{"name": "A", "charter": "c", "summary": "s"}]})
    assert got["advice"] == [None]


def test_a_manifest_that_wins_a_path_that_is_not_an_operation_does_not_validate():
    reg = parts._registry()
    clone = Registry(reg.root, reg.package)
    clone.components = dict(reg.components)
    comp = clone.components[("panel", "director_board")]
    members = [comp.manifest.members[0].model_copy(update={"wins": ["nonsense"]}), *comp.manifest.members[1:]]
    clone.components[("panel", "director_board")] = dataclasses.replace(
        comp, manifest=comp.manifest.model_copy(update={"members": members}))
    assert any("nonsense" in str(p) for p in clone.validate(imports=False))
