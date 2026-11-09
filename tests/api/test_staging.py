"""The Production panel, plan/2026-11-01: who is seen, a person's intent and coverage plan, the
staging and coverage checks, and the checks a painted frame carries."""
from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import World
from tests.api.test_production import design, fired, open_scene, shot_url  # noqa: F401
from tests.api.test_scenes import seed_scene, url


def scene_url(world: World, s: dict, tail: str = "") -> str:
    return url(world, f"/scenes/{s['scene']['id']}{tail}")


def test_the_view_says_who_is_seen_and_flags_a_scene_of_one_size(world: World):
    s = open_scene(world)
    v = world.client.get(scene_url(world, s, "/production"), headers=world.headers(world.reviewer)).json()
    assert v["coverage"] is None and v["shots"][1]["intent"] is None
    assert v["shots"][1]["people"] == [{"id": s["lines"][0]["character_id"], "code": "C02", "name": "Nimal",
                                        "seen": True}]
    first = {c["label"]: c for c in v["shots"][0]["checks"]}
    assert first["Every shot in the scene is a medium shot"]["code"] == "coverage"
    assert v["shots"][0]["frames"] == []


def test_a_person_writes_the_intent_and_can_hand_it_back(world: World):
    s = open_scene(world)
    design(world, s)
    nimal = s["lines"][0]["character_id"]
    h = world.headers(world.admin)
    r = world.client.patch(shot_url(world, s, 1, "/intent"), headers=h,
                           json={"purpose": "Nimal finally speaks", "what_we_see": "  Nimal in the doorway,\n waiting ",
                                 "on_screen": [nimal]})
    assert r.status_code == 200, r.text
    it = r.json()["intent"]
    assert it["by"] == "person" and it["purpose"] == "Nimal finally speaks"
    assert it["what_we_see"] == "Nimal in the doorway, waiting" and it["on_screen"] == [nimal] and not it["stale"]
    stored = world.repos.shots.rows[s["shots"][1]["id"]]["intent"]  # type: ignore[attr-defined]
    assert stored["by"] == "person" and stored["written_at"]

    # Nobody on screen: Nimal's line is now a voice without a face, and the card says so.
    r = world.client.patch(shot_url(world, s, 1, "/intent"), headers=h, json={"on_screen": []})
    view = r.json()
    assert view["people"][0]["seen"] is False and view["intent"]["heard_only"] == [nimal]
    labels = {c["label"] for c in view["checks"]}
    assert "Speaker not on screen · Nimal" in labels

    bad = world.client.patch(shot_url(world, s, 1, "/intent"), headers=h, json={"on_screen": [str(uuid4())]})
    assert bad.status_code == 422 and "already in the shot" in bad.json()["detail"]

    reset = world.client.patch(shot_url(world, s, 1, "/intent"), headers=h, json={"reset": True})
    assert reset.json()["intent"] is None and reset.json()["people"][0]["seen"] is True


def test_changing_the_intent_makes_the_design_out_of_date(world: World):
    s = open_scene(world)
    design(world, s)
    sid = s["shots"][1]["id"]
    row = world.repos.shots.rows[sid]  # type: ignore[attr-defined]
    world.client.patch(shot_url(world, s, 1, "/intent"), headers=world.headers(world.admin),
                       json={"purpose": "first"})
    row["design"]["intent"] = row["intent"] and __import__("contracts.staging", fromlist=["ShotIntent"]) \
        .ShotIntent.model_validate(row["intent"]).stamp()
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert v["design"]["state"] == "current"
    world.client.patch(shot_url(world, s, 1, "/intent"), headers=world.headers(world.admin),
                       json={"purpose": "second"})
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert v["design"]["state"] == "stale" and "What the shot is for changed." in v["design"]["stale_reasons"]


def test_a_person_writes_the_coverage_plan(world: World):
    s = open_scene(world)
    h = world.headers(world.admin)
    r = world.client.patch(scene_url(world, s, "/coverage"), headers=h,
                           json={"axis": "stay on the stove side", "progression": "wide to close"})
    assert r.status_code == 200, r.text
    assert r.json()["coverage"] == {"axis": "stay on the stove side", "motif": "", "progression": "wide to close",
                                    "by": "person", "stale": False}
    assert world.client.patch(scene_url(world, s, "/coverage"), headers=h,
                              json={"reset": True}).json()["coverage"] is None


def test_intent_and_coverage_need_an_unlocked_scene_and_a_role(world: World):
    s = seed_scene(world)
    s["scene"]["status"] = "approved"  # locked: the picture work is closed
    h = world.headers(world.admin)
    assert world.client.patch(shot_url(world, s, 1, "/intent"), headers=h, json={"purpose": "x"}).status_code == 409
    assert world.client.patch(scene_url(world, s, "/coverage"), headers=h, json={"axis": "x"}).status_code == 409
    s2 = open_scene(world)
    assert world.client.patch(shot_url(world, s2, 1, "/intent"), headers=world.headers(world.reviewer),
                              json={"purpose": "x"}).status_code == 403


def test_a_frames_checks_reach_the_panel(world: World):
    s = open_scene(world)
    design(world, s)
    fid = str(uuid4())
    world.repos.frames.rows[fid] = {  # type: ignore[attr-defined]
        "id": fid, "production_id": str(world.production), "shot_id": s["shots"][1]["id"], "status": "done",
        "storage_path": "p/x.png", "pins": {}, "created_at": "2026-11-01T00:00:00+00:00",
        "checks": [{"label": "2 people in frame, expected 1", "tone": "advisory"}, {"bad": True}]}
    v = world.client.get(shot_url(world, s, 1), headers=world.headers(world.reviewer)).json()
    assert v["frames"][0]["checks"] == [{"label": "2 people in frame, expected 1", "tone": "advisory"}]
