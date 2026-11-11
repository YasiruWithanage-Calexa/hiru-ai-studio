# ruff: noqa: F811  (the pytest fixtures are re-imported and then named as arguments)
"""Phase 5 (plan/2026-11-08e): the API side of Shot Planner Raphael, with the repositories faked.

"Plan with Raphael", "More cinematic", reading the result, the length cap a person chooses, and the one branch in the
build that chooses a planner. The function itself is `test_system.py`; nothing here calls a model."""

from __future__ import annotations

import pytest

from contracts.production import ProductionSettings
from contracts.raphael.stored import StoredRaphael
from tests.api.conftest import World, _settings, world  # noqa: F401  (the fixtures: settings are autouse there)
from tests.api.test_build import fired as build_fired  # noqa: F401
from tests.api.test_build import ready_doc, start
from tests.api.test_scenes import fired, seed_scene, url  # noqa: F401
from tests.raphael import gold


def raphael_scene(world: World, *, stage1: str = "finished") -> dict:
    """The seeded scene, planned by Raphael: a result stored on it and its shots marked as Raphael's."""
    seeded = seed_scene(world)
    work = gold.final()
    stored = StoredRaphael(
        stage1=stage1,  # type: ignore[arg-type]
        stage2="finished",
        cap=2,
        edit=work.edit,
        clips=work.clips,
        blend_notes=gold.stage2_result()[0],
        review=gold.stage2_result()[1],
    )
    seeded["scene"]["raphael"] = stored.data()
    for row in world.repos.shots.rows.values():  # type: ignore[attr-defined]
        row["planner"] = "raphael"
    return {**seeded, "stored": stored}


def post(world: World, path: str, user=None, **body):
    return world.client.post(url(world, path), json=body, headers=world.headers(user or world.director))


def test_plan_with_raphael_sends_one_scene_to_the_raphael_function(world: World, fired: list[dict]):
    s = seed_scene(world)
    r = post(world, f"/scenes/{s['scene']['id']}/raphael/plan")
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "plan_scene_raphael" and fired[0]["url"].endswith(":8215/")
    assert fired[0]["state"] == {"scene_ids": [s["scene"]["id"]], "edit": {}, "replan": True}
    assert world.repos.jobs.rows[str(r.json()["job_id"])]["kind"] == "plan_scene_raphael"  # type: ignore[attr-defined]


@pytest.mark.parametrize("cap", [1.5, 2, 2.5, 3])
def test_the_length_cap_a_person_chooses_travels_in_the_state(world: World, fired: list[dict], cap: float):
    s = seed_scene(world)
    assert post(world, f"/scenes/{s['scene']['id']}/raphael/plan", cap=cap, note=" tighter ").status_code == 202
    assert fired[0]["state"]["edit"] == {"cap": cap, "note": "tighter"}


def test_a_cap_that_is_not_one_of_the_four_choices_is_refused_and_nothing_is_sent(world: World, fired: list[dict]):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    for bad in (1, 4, 0, 2.2, -2):
        assert post(world, f"/scenes/{sid}/raphael/plan", cap=bad).status_code == 422
    assert post(world, f"/scenes/{sid}/raphael/plan", note="x" * 1001).status_code == 422
    assert post(world, f"/scenes/{sid}/raphael/plan", price=1).status_code == 422  # no field the plan does not name
    assert not fired


def test_only_someone_who_directs_may_plan_and_an_approved_scene_or_one_with_no_script_is_refused(
    world: World, fired: list[dict]
):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    assert post(world, f"/scenes/{sid}/raphael/plan", user=world.writer).status_code == 403
    s["scene"]["status"] = "approved"
    assert post(world, f"/scenes/{sid}/raphael/plan").status_code == 409
    s["scene"]["status"], s["scene"]["script"] = "split", []
    assert post(world, f"/scenes/{sid}/raphael/plan").status_code == 409 and not fired


def test_more_cinematic_runs_the_cinematic_job_alone_with_the_cap_chosen(world: World, fired: list[dict]):
    s = raphael_scene(world)
    sid = s["scene"]["id"]
    r = post(world, f"/scenes/{sid}/raphael/cinematic", cap=2.5)
    assert r.status_code == 202, r.text
    assert fired[0]["kind"] == "cinematic_scene_raphael" and fired[0]["url"].endswith(":8215/")
    assert fired[0]["state"] == {"scene_ids": [sid], "edit": {"stage": "cinematic", "cap": 2.5}}
    assert post(world, f"/scenes/{sid}/raphael/cinematic", cap=9).status_code == 422
    assert post(world, f"/scenes/{sid}/raphael/cinematic", user=world.writer).status_code == 403
    assert len(fired) == 1


def test_more_cinematic_needs_a_scene_whose_must_clips_are_finished(world: World, fired: list[dict]):
    s = seed_scene(world)  # never planned by Raphael
    assert post(world, f"/scenes/{s['scene']['id']}/raphael/cinematic").status_code == 409
    stopped = raphael_scene(world, stage1="stopped")
    assert post(world, f"/scenes/{stopped['scene']['id']}/raphael/cinematic").status_code == 409 and not fired


def test_a_scene_raphael_never_planned_reads_as_classic_with_no_result(world: World):
    s = seed_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/raphael"), headers=world.headers(world.reviewer))
    assert r.status_code == 200 and r.json()["planner"] == "classic" and r.json()["result"] is None


def test_the_result_of_a_raphael_scene_comes_back_whole_with_the_caps_and_no_money(world: World):
    s = raphael_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/raphael"), headers=world.headers(world.reviewer))
    body = r.json()
    assert r.status_code == 200 and body["planner"] == "raphael" and body["caps"] == [1.5, 2, 2.5, 3]
    assert body["default_cap"] == 2 and len(body["result"]["clips"]) == 21
    assert StoredRaphael.model_validate(body["result"]).clips == s["stored"].clips
    text = r.text.lower()
    assert "dollar" not in text and "cost" not in text and "price" not in text and "credit" not in text


def test_the_default_cap_is_the_productions(world: World):
    s = raphael_scene(world)
    settings = ProductionSettings(raphael_length_cap=3).model_dump(mode="json")
    world.repos.productions.rows[str(world.production)]["settings"] = settings  # type: ignore[attr-defined]
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/raphael"), headers=world.headers(world.reviewer))
    assert r.json()["default_cap"] == 3


def test_the_scene_view_names_the_planner_and_the_clip_of_each_shot(world: World):
    s = raphael_scene(world)
    s["scene"]["fit_report"] = {"planner": "raphael"}
    for n, row in enumerate(world.repos.shots.rows.values()):  # type: ignore[attr-defined]
        row.update({"slate": f"1A-{n + 1}", "role": "master", "priority": "must", "stage": 1})
    view = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.reviewer)).json()
    assert view["planner"] == "raphael" and {sh["planner"] for sh in view["shots"]} == {"raphael"}
    assert all(sh["slate"] and sh["priority"] == "must" and sh["stage"] == 1 for sh in view["shots"])


@pytest.mark.parametrize(
    ("setting", "last"),
    [(None, "script_split"), ("classic", "script_split"), ("raphael", "plan_scene_raphael")],
)
def test_the_build_plans_shots_with_the_planner_the_production_chose(
    world: World, build_fired: list[dict], setting: str | None, last: str
):
    if setting:
        settings = ProductionSettings(shot_planner=setting).model_dump(mode="json")  # type: ignore[arg-type]
        world.repos.productions.rows[str(world.production)]["settings"] = settings  # type: ignore[attr-defined]
    ready_doc(world)
    assert start(world).status_code == 202
    assert build_fired[0]["pipeline"] == ["canon_extract", "structure_build", last]


def test_the_view_gives_each_shot_its_story_and_states_and_the_state_reports(world: World):
    """plan/2026-11-09 phase 8: by slate, from the shots' intents; the state checks' reports from the stored result."""
    from contracts.raphael.stored import Left

    s = raphael_scene(world)
    left = [
        Left(code="state", sentence="c05: the phone passes from Kasun to Anudi at b9.", clips=["c05"], fix="report"),
        Left(code="clock", sentence="c02 needs 6.5 s.", clips=["c02"], fix="report"),
    ]
    s["scene"]["raphael"] = s["stored"].model_copy(update={"left": left}).data()
    rows = list(world.repos.shots.rows.values())  # type: ignore[attr-defined]
    for n, row in enumerate(rows):
        row["slate"] = f"1A-{n + 1}"
        row["intent"] = (
            {
                "by": "raphael",
                "story": "He gives it back.",
                "opens": "Kasun: phone in right hand",
                "ends": "Anudi: phone in left hand",
            }
            if n == 0
            else {"by": "raphael"}
        )
    body = world.client.get(
        url(world, f"/scenes/{s['scene']['id']}/raphael"), headers=world.headers(world.reviewer)
    ).json()
    assert body["states"] == {
        "1A-1": {
            "story": "He gives it back.",
            "opens": "Kasun: phone in right hand",
            "ends": "Anudi: phone in left hand",
        }
    }
    assert [f["code"] for f in body["state_faults"]] == ["state"]


def test_a_scene_with_no_state_map_has_no_states(world: World):
    s = raphael_scene(world)
    body = world.client.get(
        url(world, f"/scenes/{s['scene']['id']}/raphael"), headers=world.headers(world.reviewer)
    ).json()
    assert body["states"] == {} and body["state_faults"] == []
