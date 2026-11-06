"""Phase 4 (plan/2026-11-05e §4.5, §10): after the plan, the camera is decided once.

A shot Jonathan wrote carries its IR and a design whose pins are the ones the shot producer computes from the same
rows, so
`design_stale` is empty for it, the intent agent is skipped (`by = "jonathan"`), and the DoP and the critic are never
asked.
The Veo prompt is then written in code from the IR. Nothing here calls a model.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from contracts.jobs import DispatchPayload, JobKind
from contracts.staging import ScenePlan, ShotIntent
from hiru_ai.core import llm, parts
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeJobs, FakeProducer
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.jonathan.jonathan_shot_planner import graph as jonathan_graph
from hiru_ai.systems.shot_producer import graph as producer_graph
from tests.jonathan import gold
from tests.jonathan.test_system import route, routes_for
from tests.jonathan.world import World


@pytest.fixture
def planned() -> World:
    world = World()
    model = RoutedChatModel(routes=routes_for(), choose=route, model_name="model")
    with llm.use_models(model):
        jonathan_graph.run(world.payload(), world.ctx())
    assert world.jobs.status == "done"
    return world


def producer_inputs(world: World) -> tuple[Any, Any, Any]:
    model = parts.step("serialize", "model")
    row = world.row()
    prod = model.production_input(world.scenes.production(UUID(world.production)) or {}, world.scenes.canon_rows, None)
    scene = model.scene_input(row, world.shots(), world.scenes.lines(world.scene_id), world.scenes.canon_rows, prod,
                              (None, None))
    return model, prod, scene


def test_a_jonathan_shots_design_is_not_stale_so_no_dop_or_critic_is_needed(planned: World):
    model, prod, scene = producer_inputs(planned)
    assert len(scene.shots) == 15
    assert [model.design_stale(s, prod) for s in scene.shots] == [[] for _ in scene.shots]
    assert all(
        s.row["ir"] and s.row["design"]["pins"] and s.row["design"]["planner"] == "jonathan" for s in scene.shots)


def test_the_intent_agent_is_not_asked_about_a_jonathan_shot_or_its_scene(planned: World):
    _, _, scene = producer_inputs(planned)
    assert all(not s.intent_needed() and ShotIntent.of(s.row).by == "jonathan" for s in scene.shots)  # type: ignore[union-attr]
    assert not scene.plan_needed() and ScenePlan.of(planned.row()).by == "jonathan"  # type: ignore[union-attr]


def test_the_shot_producer_designs_nothing_and_calls_no_model_for_a_jonathan_scene(planned: World):
    producer = FakeProducer(scenes=planned.scene_rows, shots=planned.scenes.shot_rows)
    jobs = FakeJobs()
    ctx = RunContext(ports=replace(Ports(), jobs=jobs, scenes=planned.scenes, producer=producer))
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.SHOT_PRODUCE, actor_user_id=uuid4(),
                              production_id=UUID(planned.production), pipeline=[JobKind.SHOT_PRODUCE], cursor=0,
                              state={"scene_ids": [planned.scene_id], "mode": "design"})
    model = RoutedChatModel(routes={}, choose=lambda m: "none", model_name="model")
    with llm.use_models(model):
        out = producer_graph.run(payload, ctx)
    assert out["designed"] == 0 and out["prompts"] == 0 and "intents" not in out
    assert not model.calls and not producer.intents and not producer.coverage


def test_the_design_goes_stale_when_what_it_was_made_against_changes_and_not_before(planned: World):
    model, prod, scene = producer_inputs(planned)
    canon = planned.scenes.canon_rows
    anudi = next(c for c in canon if c["name"] == "Anudi")
    anudi["current"] = {**anudi["current"], "version": 2}  # a new card for a person in the shot: the DoP's rule, kept
    _, prod, scene = producer_inputs(planned)
    stale = [model.design_stale(s, prod) for s in scene.shots]
    assert any(stale) and all("Anudi" in " ".join(r) for r in stale if r)  # the DoP's rule, kept: a new card is a flag


def test_a_persons_camera_override_still_wins_over_the_authors_camera(planned: World):
    _, _, scene = producer_inputs(planned)
    shot = scene.shots[0]
    assert shot.camera(scene).lens == shot.recommended(scene).lens
    shot.row = {**shot.row, "camera_overrides": {"lens": "85mm"}}
    assert shot.camera(scene).lens == "85mm"


def test_the_authors_camera_reaches_the_panels_words_where_there_is_an_exact_equivalent(planned: World):
    _, _, scene = producer_inputs(planned)
    assert scene.shots[0].recommended(scene).movement == "Static"  # "locked-off" in the IR
    assert scene.shots[0].recommended(scene).framing == "Wide shot"  # the size is the author's, never the DoP's


def test_the_veo_prompts_written_in_code_from_the_authors_ir_pass_the_lint(planned: World):
    _, prod, scene = producer_inputs(planned)
    design = parts.step("serialize", "design")
    lint = parts.step("prompt_lint", "step")
    lines = planned.scenes.lines(planned.scene_id)
    for shot in scene.shots:
        prompt = design.write_prompt(shot, scene, prod, None, "job-1", "actor-1")
        found = lint.run({"prompt": prompt, "shot": shot.row, "lines": lines})
        assert found["ok"], f"{shot.code}: {found['findings']}"
        assert prompt["sections"] and prompt["prose"]


def test_the_words_of_a_line_reach_the_prompt_only_from_the_script_never_from_the_authors_free_text(planned: World):
    _, prod, scene = producer_inputs(planned)
    design = parts.step("serialize", "design")
    shot = scene.shots[1]  # Dasun's line
    prompt = design.write_prompt(shot, scene, prod, None, "job-1", "actor-1")
    line = gold.raw()["blocks"][1]["text"]
    assert prompt["prose"].count(line) == 1
