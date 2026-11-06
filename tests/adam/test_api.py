# ruff: noqa: F811  (the pytest fixtures are re-imported and then named as arguments)
"""Phase 6 (plan/2026-11-04b §5.5): the API side of Shot Planner Adam, with the repositories faked.

"Plan with Adam", switching a treatment, taking an added moment out, reading the plan, and the one branch in the build
that chooses a planner. The function itself is `test_system.py`; nothing here calls a model."""
from __future__ import annotations

import pytest
from tests.adam import stages
from tests.api.conftest import World, _settings, world  # noqa: F401  (the fixtures: settings are autouse there)
from tests.api.test_build import fired as build_fired  # noqa: F401
from tests.api.test_build import ready_doc, start
from tests.api.test_scenes import fired, seed_scene, url  # noqa: F401

from contracts.adam.stored import StoredPlan
from contracts.production import ProductionSettings


def adam_scene(world: World) -> dict:
    """The seeded scene, planned by Adam: the master's plan stored on it and its shots marked as Adam's."""
    seeded = seed_scene(world)
    p = stages.master_with_stance("phone_call")
    stored = StoredPlan(chosen=p.treatment.stance, analysis=p.analysis, treatment=p.treatment, moments=p.moments,
                        staging=p.staging, cards=p.cards, sound_map=p.sound_map)
    seeded["scene"]["adam"] = stored.data()
    for row in world.repos.shots.rows.values():  # type: ignore[attr-defined]
        row["planner"] = "adam"
    return {**seeded, "stored": stored}


def post(world: World, path: str, user=None, **body):
    return world.client.post(url(world, path), json=body, headers=world.headers(user or world.director))


def test_plan_with_adam_sends_one_scene_to_the_adam_function(world: World, fired: list[dict]):
    s = seed_scene(world)
    r = post(world, f"/scenes/{s['scene']['id']}/adam/plan")
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "plan_scene_adam" and fired[0]["url"].endswith(":8209/")
    assert fired[0]["state"] == {"scene_ids": [s["scene"]["id"]], "edit": {}, "screening": True, "replan": True}
    assert world.repos.jobs.rows[str(r.json()["job_id"])]["kind"] == "plan_scene_adam"  # type: ignore[attr-defined]


def test_a_treatment_and_no_screening_travel_in_the_state_and_a_bad_stance_is_refused(world: World, fired: list[dict]):
    s = seed_scene(world)
    assert post(world, f"/scenes/{s['scene']['id']}/adam/plan", treatment="heightened",
                screening=False).status_code == 202
    assert fired[0]["state"]["edit"] == {"treatment": "heightened"} and fired[0]["state"]["screening"] is False
    assert post(world, f"/scenes/{s['scene']['id']}/adam/plan", treatment="loud").status_code == 422


def test_only_someone_who_directs_may_plan_and_an_approved_scene_or_one_with_no_script_is_refused(
        world: World, fired: list[dict]):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    assert post(world, f"/scenes/{sid}/adam/plan", user=world.writer).status_code == 403
    s["scene"]["status"] = "approved"
    assert post(world, f"/scenes/{sid}/adam/plan").status_code == 409
    s["scene"]["status"], s["scene"]["script"] = "split", []
    assert post(world, f"/scenes/{sid}/adam/plan").status_code == 409 and not fired


def test_a_scene_adam_never_planned_reads_as_classic_with_no_plan(world: World):
    s = seed_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/adam"), headers=world.headers(world.reviewer))
    assert r.status_code == 200 and r.json()["planner"] == "classic" and r.json()["plan"] is None


def test_the_plan_of_an_adam_scene_comes_back_whole_with_the_analysis_key_the_plan_uses(world: World):
    s = adam_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/adam"), headers=world.headers(world.reviewer))
    body = r.json()
    assert r.status_code == 200 and body["planner"] == "adam"
    assert len(body["plan"]["cards"]) == 13 and body["plan"]["analysis"]["break"]["block"] is not None
    assert StoredPlan.model_validate(body["plan"]).cards == s["stored"].cards


def test_the_scene_view_names_the_planner_of_each_shot(world: World):
    s = adam_scene(world)
    s["scene"]["fit_report"] = {"planner": "adam"}
    view = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.reviewer)).json()
    assert view["planner"] == "adam" and {sh["planner"] for sh in view["shots"]} == {"adam"}


def test_taking_an_added_moment_out_starts_a_job_with_no_model_and_the_script_is_protected(
        world: World, fired: list[dict]):
    s = adam_scene(world)
    sid = s["scene"]["id"]
    added = next(m for m in s["stored"].moments if m.tier == "elaboration")
    script = next(m for m in s["stored"].moments if m.tier == "script")
    r = post(world, f"/scenes/{sid}/adam/moments/{added.id}/remove")
    assert r.status_code == 202 and fired[0]["state"] == {"scene_ids": [sid], "edit": {"remove_moment": added.id}}
    assert post(world, f"/scenes/{sid}/adam/moments/{script.id}/remove").status_code == 422
    assert post(world, f"/scenes/{sid}/adam/moments/m404/remove").status_code == 404
    assert post(world, f"/scenes/{sid}/adam/moments/{added.id}/remove", user=world.writer).status_code == 403
    assert len(fired) == 1


def test_a_scene_adam_did_not_plan_has_nothing_to_take_a_moment_out_of(world: World, fired: list[dict]):
    s = seed_scene(world)
    assert post(world, f"/scenes/{s['scene']['id']}/adam/moments/m1/remove").status_code == 409 and not fired


@pytest.mark.parametrize(("setting", "last"), [(None, "script_split"), ("classic", "script_split"),
                                               ("adam", "plan_scene_adam")])
def test_the_build_plans_shots_with_the_planner_the_production_chose(
        world: World, build_fired: list[dict], setting: str | None, last: str):
    if setting:
        settings = ProductionSettings(shot_planner=setting).model_dump(mode="json")  # type: ignore[arg-type]
        world.repos.productions.rows[str(world.production)]["settings"] = settings  # type: ignore[attr-defined]
    ready_doc(world)
    assert start(world).status_code == 202
    assert build_fired[0]["pipeline"] == ["canon_extract", "structure_build", last]
