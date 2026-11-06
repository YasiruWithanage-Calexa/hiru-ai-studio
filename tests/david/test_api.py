# ruff: noqa: F811  (the pytest fixtures are re-imported and then named as arguments)
"""Phase 5 (plan/2026-11-05e §4.7): the API side of Shot Planner David, with the repositories faked.

"Plan with David", changing a plan with a note, taking an addition out, reading the plan, and the one branch in the
build that
chooses a planner. The function itself is `test_system.py`; nothing here calls a model."""
from __future__ import annotations

import pytest

from contracts.david.stored import StoredPlan
from contracts.production import ProductionSettings
from tests.api.conftest import World, _settings, world  # noqa: F401  (the fixtures: settings are autouse there)
from tests.api.test_build import fired as build_fired  # noqa: F401
from tests.api.test_build import ready_doc, start
from tests.api.test_scenes import fired, seed_scene, url  # noqa: F401
from tests.david import gold


def david_scene(world: World) -> dict:
    """The seeded scene, planned by David: the hand-written plan stored on it and its shots marked as David's."""
    seeded = seed_scene(world)
    stored = StoredPlan(plan=gold.phone_call(), end_state=gold.phone_call().end_state)
    seeded["scene"]["david"] = stored.data()
    for row in world.repos.shots.rows.values():  # type: ignore[attr-defined]
        row["planner"] = "david"
    return {**seeded, "stored": stored}


def post(world: World, path: str, user=None, **body):
    return world.client.post(url(world, path), json=body, headers=world.headers(user or world.director))


def test_plan_with_david_sends_one_scene_to_the_david_function(world: World, fired: list[dict]):
    s = seed_scene(world)
    r = post(world, f"/scenes/{s['scene']['id']}/david/plan")
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "plan_scene_david" and fired[0]["url"].endswith(":8210/")
    assert fired[0]["state"] == {"scene_ids": [s["scene"]["id"]], "edit": {}, "replan": True}
    assert world.repos.jobs.rows[str(r.json()["job_id"])]["kind"] == "plan_scene_david"  # type: ignore[attr-defined]


def test_a_note_travels_in_the_state_and_only_on_a_scene_david_planned(world: World, fired: list[dict]):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    assert post(world, f"/scenes/{sid}/david/plan", note="Start closer on Anudi.").status_code == 409 and not fired
    d = david_scene(world)
    assert post(world, f"/scenes/{d['scene']['id']}/david/plan", note=" Start closer on Anudi. ").status_code == 202
    assert fired[0]["state"]["edit"] == {"note": "Start closer on Anudi."}
    assert post(world, f"/scenes/{sid}/david/plan", note="x" * 1001).status_code == 422


def test_only_someone_who_directs_may_plan_and_an_approved_scene_or_one_with_no_script_is_refused(
        world: World, fired: list[dict]):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    assert post(world, f"/scenes/{sid}/david/plan", user=world.writer).status_code == 403
    s["scene"]["status"] = "approved"
    assert post(world, f"/scenes/{sid}/david/plan").status_code == 409
    s["scene"]["status"], s["scene"]["script"] = "split", []
    assert post(world, f"/scenes/{sid}/david/plan").status_code == 409 and not fired


def test_a_scene_david_never_planned_reads_as_classic_with_no_plan(world: World):
    s = seed_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/david"), headers=world.headers(world.reviewer))
    assert r.status_code == 200 and r.json()["planner"] == "classic" and r.json()["plan"] is None


def test_the_plan_of_a_david_scene_comes_back_whole(world: World):
    s = david_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/david"), headers=world.headers(world.reviewer))
    body = r.json()
    assert r.status_code == 200 and body["planner"] == "david"
    assert len(body["plan"]["plan"]["shots"]) == 10 and body["plan"]["end_state"]["time"] == "late afternoon"
    assert StoredPlan.model_validate(body["plan"]).plan == s["stored"].plan


def test_the_scene_view_names_the_planner_of_each_shot(world: World):
    s = david_scene(world)
    s["scene"]["fit_report"] = {"planner": "david"}
    view = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.reviewer)).json()
    assert view["planner"] == "david" and {sh["planner"] for sh in view["shots"]} == {"david"}


def test_taking_an_addition_out_starts_a_job_with_no_model_and_a_shot_of_the_script_is_protected(
        world: World, fired: list[dict]):
    s = david_scene(world)
    sid = s["scene"]["id"]
    r = post(world, f"/scenes/{sid}/david/added/1/remove")
    assert r.status_code == 202 and fired[0]["state"] == {"scene_ids": [sid], "edit": {"remove_added": 1}}
    assert post(world, f"/scenes/{sid}/david/added/9/remove").status_code == 404
    assert post(world, f"/scenes/{sid}/david/added/1/remove", user=world.writer).status_code == 403
    assert len(fired) == 1
    on_script = s["stored"].model_copy(deep=True)
    on_script.plan.added[0] = on_script.plan.added[0].model_copy(update={"shot": 2})  # shot 2 shows block 1
    s["scene"]["david"] = on_script.data()
    assert post(world, f"/scenes/{sid}/david/added/1/remove").status_code == 422 and len(fired) == 1


def test_a_scene_david_did_not_plan_has_nothing_to_take_an_addition_out_of(world: World, fired: list[dict]):
    s = seed_scene(world)
    assert post(world, f"/scenes/{s['scene']['id']}/david/added/1/remove").status_code == 409 and not fired


@pytest.mark.parametrize(("setting", "last"), [(None, "script_split"), ("classic", "script_split"),
                                               ("david", "plan_scene_david")])
def test_the_build_plans_shots_with_the_planner_the_production_chose(
        world: World, build_fired: list[dict], setting: str | None, last: str):
    if setting:
        settings = ProductionSettings(shot_planner=setting).model_dump(mode="json")  # type: ignore[arg-type]
        world.repos.productions.rows[str(world.production)]["settings"] = settings  # type: ignore[attr-defined]
    ready_doc(world)
    assert start(world).status_code == 202
    assert build_fired[0]["pipeline"] == ["canon_extract", "structure_build", last]
