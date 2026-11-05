"""Phase 6 (plan/2026-11-04b §5.5): the adam_shot_planner system, end to end on localhost with fakes.

The model is scripted with the gold master's own answers for each stage, so the pipeline's wiring (what is handed on,
what is retried, dropped and written) is shown without a model call. It does not show that a model can write those
answers.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.adam import gold, stages

from contracts.adam.stored import StoredPlan
from contracts.jobs import DispatchPayload, JobKind
from contracts.staging import ScenePlan as ShotPlan
from contracts.staging import ShotIntent
from hiru_ai.core import llm
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeJobs, FakeScenes, FakeSplit
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.adam.adam_shot_planner import graph

NAME = "phone_call"
MARKS = {"adam_dramaturg": "the Dramaturg of", "adam_director": "the Director of", "adam_moment_writer":
         "the Moment Writer", "adam_blocker": "the Blocking Director", "adam_shot_designer": "the Shot Designer",
         "adam_sound_designer": "the Sound Designer", "audience": "Audience Seat critic", "editor": "Editor critic",
         "opportunity": "Opportunity critic", "fidelity": "Fidelity and Feasibility critic",
         "reviser": "the Reviser of Shot Planner Adam"}
STAGES = ("adam_dramaturg", "adam_director", "adam_moment_writer", "adam_blocker", "adam_shot_designer",
          "adam_sound_designer")
LENSES = ("audience", "editor", "opportunity", "fidelity")


class World:
    """A production with one gold scene in memory: the fakes the system reads and writes."""

    def __init__(self, name: str = NAME, *, status: str = "draft", shots: list[dict[str, Any]] | None = None) -> None:
        sc = gold.scene(name)
        self.production, self.episode, self.scene_id = str(uuid4()), str(uuid4()), str(uuid4())
        self.line_ids = {b["index"]: str(uuid4()) for b in sc["blocks"] if b.get("line_id")}
        script = [{"kind": "dialogue", "line_id": self.line_ids[b["index"]]} if b.get("line_id")
                  else {"kind": b["kind"], "text": b["text"]} for b in sc["blocks"]]
        self.scene = {"id": self.scene_id, "production_id": self.production, "episode_id": self.episode, "number": 1,
                      "heading": stages.title(name), "title": "", "location_id": "loc-1", "envelope_s": 90,
                      "script": script, "status": status, "note": "", "adam": {}}
        lines = [{"id": self.line_ids[b["index"]], "production_id": self.production, "scene_id": self.scene_id,
                  "ord": n, "speaker": b["speaker"], "character_id": f"char-{b['speaker']}", "text": b["text"],
                  "delivery": b.get("delivery", "")} for n, b in enumerate(b for b in sc["blocks"] if b.get("line_id"))]
        canon = [{"kind": "prop", "name": o} for o in sc["place"]["objects"]]
        self.scenes = FakeScenes(production={"id": self.production, "settings": {}}, scenes=[self.scene], lines=lines,
                                 canon=canon, shots=shots)
        self.split = FakeSplit(
            episodes=[{"id": self.episode, "number": 1, "title": "Ep 1", "synopsis": "", "status": "draft"}],
            scenes=[self.scene], characters=[{"id": f"char-{c}", "name": c, "code": c, "current": {"card": {
                "summary": f"{c} in the drama"}}} for c in sc["cast"]],
            locations=[{"id": "loc-1", "name": sc["place"]["name"], "current": {"card": {
                "look": ", ".join(sc["place"]["objects"])}}}])
        self.jobs = FakeJobs()

    def ctx(self) -> RunContext:
        return RunContext(ports=replace(Ports(), jobs=self.jobs, scenes=self.scenes, split=self.split))

    def payload(self, **state: Any) -> DispatchPayload:
        """A new job (the fakes forget the last one: a finished job is skipped, as in production)."""
        self.jobs = FakeJobs()
        return DispatchPayload(job_id=uuid4(), kind=JobKind.PLAN_SCENE_ADAM, actor_user_id=uuid4(),
                               production_id=UUID(self.production),
                               pipeline=[JobKind.PLAN_SCENE_ADAM], cursor=0,
                               state={"scene_ids": [self.scene_id], **state})

    def row(self) -> dict[str, Any]:
        return self.scenes.scene_rows[0]

    def shots(self) -> list[dict[str, Any]]:
        return self.scenes.shots(self.scene_id)


def route(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return next(k for k, mark in MARKS.items() if mark in system)


def script_routes(name: str = NAME, *, skip: tuple[str, ...] = ()) -> dict[str, list[Any]]:
    routes: dict[str, list[Any]] = {a: [stages.replies(a, name)] for a in STAGES if a not in skip}
    routes |= {lens: [{"score": 4, "notes": [{"card": 2, "severity": "low", "kind": "change", "cell": "",
                                              "note": f"{lens}: give the face room"}]}]
               for lens in LENSES}
    routes["reviser"] = [{"operations": [], "dispositions": []}]
    return routes


def run(world: World, routes: dict[str, list[Any]], **state: Any) -> tuple[dict[str, Any], RoutedChatModel]:
    state.setdefault("edit", {"treatment": stages.stance_of(NAME)})
    model = RoutedChatModel(routes=routes, choose=route)
    with llm.use_models(model):
        return graph.run(world.payload(**state), world.ctx()), model


def test_the_gold_scene_is_planned_end_to_end_and_written_as_thirteen_shots_with_their_cards():
    world = World()
    out, model = run(world, script_routes())
    assert out == {"scenes": 1, "skipped": 0, "shots": 13, "failed": 0} and world.jobs.status == "done"
    shots = world.shots()
    assert [s["number"] for s in shots] == list(range(1, 14)) and all(s["planner"] == "adam" for s in shots)
    stored = StoredPlan.load(world.row()["adam"])
    master = stages.master_with_stance(NAME)
    assert stored is not None and stored.cards == master.cards and stored.chosen == stages.stance_of(NAME)
    assert stored.chosen_by == "person" and len(stored.alternates) == 2
    assert world.row()["status"] == "split" and world.row()["fit_report"]["planner"] == "adam"
    assert stored.report["score"]["percent"] == 100.0 and not stored.report["score"]["loss"]
    assert stored.report["screening"]["ran"] and stored.report["screening"]["kept"] == "first"
    assert stored.report["fit"]["overruns"] == 0 and stored.report["fidelity"]["ok"]
    assert len(model.calls) == 11  # six stages, four critics, one reviser
    # Phase 7: each shot carries the intent its card makes (so the intent agent is skipped), the scene its coverage plan
    intents = [ShotIntent.of(s) for s in shots]
    assert all(i is not None and i.by == "adam" and i.purpose for i in intents)
    assert world.row()["coverage"]["by"] == "adam"
    assert ShotPlan.of(world.row()) is not None


def test_every_line_is_bound_to_a_shot_and_keeps_its_own_words():
    world = World()
    run(world, script_routes())
    bound = {ln["id"]: ln for ln in world.scenes.line_rows}
    assert all(bound[i]["shot_id"] for i in world.line_ids.values())
    assert [bound[i]["text"] for i in world.line_ids.values()] == [
        b["text"] for b in gold.scene(NAME)["blocks"] if b.get("line_id")]


def test_planning_the_scene_again_replaces_its_shots_and_keeps_what_the_scene_had_before_for_comparing():
    classic = [{"id": str(uuid4()), "scene_id": "", "number": n, "title": f"classic {n}", "framing": "MS",
                "duration_s": 6, "sound_mode": "dialogue", "camera_link": "cut", "block_start": 0, "block_end": 2,
                "words": 5, "planner": "classic"} for n in (1, 2, 3)]
    world = World(shots=classic)
    for s in world.scenes.shot_rows:
        s["scene_id"] = world.scene_id
    run(world, script_routes())
    first = StoredPlan.load(world.row()["adam"])
    assert first is not None and first.previous["planner"] == "classic"
    assert [s["title"] for s in first.previous["shots"]] == ["classic 1", "classic 2", "classic 3"]
    run(world, script_routes())  # a second run (a new job): replaced, never appended, and `previous` is kept
    assert len(world.shots()) == 13 and StoredPlan.load(world.row()["adam"]).previous == first.previous  # type: ignore[union-attr]


def test_with_no_model_the_job_fails_clearly_and_names_the_classic_planner():
    world = World()
    with llm.use_models(None):
        out = graph.run(world.payload(), world.ctx())
    assert world.jobs.status == "failed" and "classic planner" in world.jobs.fields["error"]
    assert "failed" in out and world.row()["adam"] == {} and not world.shots()


def test_an_approved_scene_is_never_touched():
    world = World(status="approved")
    out, model = run(world, {})
    assert out["scenes"] == 0 and out["skipped"] == 1 and not model.calls and not world.shots()


def test_an_added_moment_that_invents_a_person_is_dropped_and_the_plan_still_scores_full():
    world = World()
    routes = script_routes()
    moments = stages.replies("adam_moment_writer", NAME)
    waiter = {**moments["moments"][1], "id": "m90", "tier": "elaboration", "kind": "reaction", "who": ["Waiter"],
              "seen": "a waiter looks up", "lines": [], "serves": ["b0"]}
    routes["adam_moment_writer"] = [{**moments, "moments": [*moments["moments"], waiter]}]
    run(world, routes)
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None and "m90" not in {m.id for m in stored.moments}
    assert stored.report["moments"]["dropped"] == ["m90"] and stored.report["score"]["percent"] == 100.0
    assert stored.report["ledger"]["ok"]  # an invented person is recorded as dropped; the scene's books still close


def test_a_script_fault_is_sent_back_once_with_its_reasons_and_then_planned():
    world = World()
    routes = script_routes()
    good = stages.replies("adam_moment_writer", NAME)
    bad = {**good, "moments": [m for m in good["moments"] if m["lines"] != ["L4"]]}  # a spoken line has no moment
    routes["adam_moment_writer"] = [bad, good]
    _, model = run(world, routes)
    sent_back = [c for c in model.calls if "Moment Writer" in str(c[0].content)][1]
    assert "<notes>" in str(sent_back[1].content) and "L4" in str(sent_back[1].content)
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None and any("sent back" in line for line in stored.report["log"])
    assert world.jobs.status == "done"


def test_a_scene_whose_moments_break_the_script_twice_is_left_as_it_was_and_the_job_says_so():
    world = World()
    routes = script_routes()
    good = stages.replies("adam_moment_writer", NAME)
    bad = {**good, "moments": [m for m in good["moments"] if m["lines"] != ["L4"]]}
    routes["adam_moment_writer"] = [bad, bad]
    run(world, routes)
    assert world.jobs.status == "failed" and "classic planner" in world.jobs.fields["error"]
    assert world.row()["adam"] == {} and not world.shots()


def short_take_replies() -> dict[str, list[Any]]:
    """The designer gives the card with L4 a 4 s take, which is too short for it."""
    routes = script_routes()
    cards = stages.replies("adam_shot_designer", NAME)
    short = {**cards, "cards": [{**c, "take_s": 4} if any(ln["line_id"] == "L4" for ln in c["lines"]) else c
                                for c in cards["cards"]]}
    routes["adam_shot_designer"] = [short, short]
    return routes


def test_a_crowded_card_is_repaired_in_code_before_screening_and_a_line_is_never_trimmed():
    """Plan 2026-11-04c F4: a take too short for its card is given the shortest longer take by code, with no send-back
    to the designer, so the plan enters screening without an overrun that deleting a moment could have ended."""
    world = World()
    _, model = run(world, short_take_replies())
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None and stored.report["fit"]["overruns"] == 0
    assert sum(1 for m in model.calls if route(m) == "adam_shot_designer") == 1  # not sent back
    assert any("repaired in code" in line for line in stored.report["log"])
    split = next(e for e in stored.report["history"]["events"] if e["kind"] == "split")
    assert split["splits"][0]["how"] == "lengthened" and split["splits"][0]["card"] == 7
    text = {r["id"]: r["text"] for r in world.scenes.line_rows}
    assert text[world.line_ids[4]] == next(b["text"] for b in gold.scene(NAME)["blocks"] if b.get("line_id") == "L4")


def test_an_overrun_code_cannot_repair_is_reported_and_never_trimmed():
    world = World()
    routes = script_routes()
    moments = stages.replies("adam_moment_writer", NAME)
    long_one = {**moments, "moments": [{**m, "seconds_need": 9.0} if "L4" in m["lines"] else m
                                       for m in moments["moments"]]}
    routes["adam_moment_writer"] = [long_one]
    routes["adam_shot_designer"] = [stages.replies("adam_shot_designer", NAME)] * 2  # sent back once, still over
    run(world, routes)
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None and stored.report["fit"]["overruns"] >= 1
    assert any("overrun(s) remain: reported, never trimmed" in line for line in stored.report["log"])
    text = {r["id"]: r["text"] for r in world.scenes.line_rows}
    assert text[world.line_ids[4]] == next(b["text"] for b in gold.scene(NAME)["blocks"] if b.get("line_id") == "L4")


def test_the_plan_keeps_its_history_and_every_moment_has_a_record():
    """Plan 2026-11-04c F1: what screening changed can be read back, and the books close."""
    world = World()
    run(world, script_routes())
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None
    history = stored.report["history"]
    assert len(history["first"]["cards"]) == 13 and history["first"]["moments"] == [m.id for m in stored.moments]
    kinds = [e["kind"] for e in history["events"]]
    assert kinds == ["notes", "revision", "kept"] and history["events"][-1]["which"] == "first"
    assert [c["which"] for c in history["events"][-1]["candidates"]] == ["first", "revision"]
    ledger = stored.report["ledger"]
    assert ledger["ok"] and ledger["buckets"]["kept"] == [m.id for m in stored.moments] and ledger["unaccounted"] == []
    assert stored.report["coverage"]["coverage"] == 1.0 and stored.report["coverage"]["holes"] == []
    assert stored.report["score"]["coverage"] == 1.0 and stored.report["score"]["craft_percent"] == 100.0


def test_a_person_takes_an_elaboration_out_with_no_model_and_it_never_comes_back_on_a_re_plan():
    world = World()
    run(world, script_routes())
    before = StoredPlan.load(world.row()["adam"])
    assert before is not None
    gone = next(m for m in before.moments if m.tier == "elaboration" and any(c.moments == [m.id] for c in before.cards))
    model = RoutedChatModel(routes={}, choose=route)
    with llm.use_models(model):
        out = graph.run(world.payload(edit={"remove_moment": gone.id}), world.ctx())
    assert out["scenes"] == 1 and not model.calls
    after = StoredPlan.load(world.row()["adam"])
    assert after is not None and gone.id not in {m.id for m in after.moments} and len(after.cards) < len(before.cards)
    assert [r.kind for r in after.removed] == [gone.kind] and len(world.shots()) == len(after.cards)
    assert after.report["fidelity"]["ok"] and not after.report["score"]["loss"]
    assert after.report["ledger"]["buckets"]["removed_by_person"] == [gone.id] and after.report["ledger"]["ok"]
    assert after.report["history"]["events"][-1]["kind"] == "removed" and \
        after.report["history"]["events"][-1]["moment"] == gone.id  # the plan log keeps what the person did too
    # Planned again: the writer offers the same addition (its moment list is the master's), the designer, as a model
    # would, designs cards without it; the code drops the addition before anything is designed from it.
    routes = script_routes()
    routes["adam_shot_designer"] = [stages.cards_wire(after.plan()).model_dump(mode="json")]
    routes["adam_sound_designer"] = [stages.sound_wire(after.plan()).model_dump(mode="json")]
    run(world, routes)
    again = StoredPlan.load(world.row()["adam"])
    assert again is not None and not any(r.matches(m) for r in again.removed for m in again.moments)
    assert again.report["moments"]["removed_by_a_person"] == [gone.id] and len(again.cards) < len(before.cards)


def test_a_script_moment_cannot_be_removed_and_a_scene_not_planned_by_adam_has_nothing_to_remove():
    world = World()
    run(world, script_routes())
    script = next(m for m in StoredPlan.load(world.row()["adam"]).moments if m.tier == "script")  # type: ignore[union-attr]
    with llm.use_models(RoutedChatModel(routes={}, choose=route)):
        graph.run(world.payload(edit={"remove_moment": script.id}), world.ctx())
    assert world.jobs.status == "failed" and "script" in world.jobs.fields["error"]
    plain = World()
    with llm.use_models(RoutedChatModel(routes={}, choose=route)):
        graph.run(plain.payload(edit={"remove_moment": "m1"}), plain.ctx())
    assert plain.jobs.status == "failed" and "not planned by Adam" in plain.jobs.fields["error"]


def test_switching_the_treatment_keeps_the_analysis_and_plans_only_the_cards_again():
    world = World()
    run(world, script_routes())
    first = StoredPlan.load(world.row()["adam"])
    assert first is not None
    other = first.alternates[0].stance
    master_other = stages.director_wire(NAME)  # the same wire the first run was given, for the alternate's stance
    assert other in {t.stance for t in master_other.treatments}
    # The alternate stance has no scripted moments of its own: the master's moments are reused, which still pass.
    routes = script_routes(skip=("adam_dramaturg", "adam_director"))
    _, model = run(world, routes, edit={"treatment": other})
    called = {route(c) for c in model.calls}
    assert "adam_dramaturg" not in called and "adam_director" not in called and "adam_moment_writer" in called
    again = StoredPlan.load(world.row()["adam"])
    assert again is not None and again.chosen == other and again.chosen_by == "person"
    assert {t.stance for t in [again.treatment, *again.alternates]} == {t.stance for t in [first.treatment,
                                                                                            *first.alternates]}


def test_the_graph_draws_itself_and_the_scene_script_gives_each_line_the_id_of_its_block():
    assert graph.blank() is not None
    world = World()
    from hiru_ai.systems.adam.adam_shot_planner import scene as adam

    script, ids = adam.script_of(world.scene, world.scenes.lines(world.scene_id), cast=["Anudi"], place="x", objects=[])
    assert ids == {f"L{i}": real for i, real in world.line_ids.items()}
    assert [b.line_id for b in script.blocks if b.line_id] == [f"L{i}" for i in world.line_ids]
    assert json.loads(script.model_dump_json())["envelope_s"] == 90


@pytest.mark.parametrize("kind", ["edit", "plain"])
def test_the_build_hop_picks_adam_only_when_the_production_setting_says_so(kind: str):
    from contracts.build import BUILD_PIPELINE, build_pipeline
    from contracts.production import ProductionSettings

    assert ProductionSettings().shot_planner == "classic"
    assert build_pipeline("classic") == BUILD_PIPELINE and build_pipeline("adam")[-1] is JobKind.PLAN_SCENE_ADAM
    assert build_pipeline("adam")[:2] == BUILD_PIPELINE[:2]
