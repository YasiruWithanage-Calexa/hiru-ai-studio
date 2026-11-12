"""The canon refine's API (plan/2026-11-12c phase 5): "Refine canon" starts a job for a canon editor; it and every plan
lock each other out (409); a proposal is accepted (after unlocking) or dismissed; a region, a spot or an unseen place
gets no reference plate; a scene look carries the scene's condition, which a person edits."""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.workers import task_manager
from contracts.jobs import JobKind
from tests.api.conftest import World
from tests.api.test_build import fired  # noqa: F401  (the fixture)
from tests.api.test_canon import add_entity, url


def _refine(world: World, who: str = "director") -> object:
    return world.client.post(url(world, "refine"), headers=world.headers(getattr(world, who)))


def _job(world: World, kind: JobKind, status: str = "running") -> str:
    jid = str(uuid4())
    world.repos.jobs.rows[jid] = {"id": jid, "kind": kind.value, "status": status,  # type: ignore[attr-defined]
                                  "production_id": str(world.production), "updated_at": "2026-11-12T00:00:00+00:00"}
    return jid


def test_a_canon_editor_starts_a_refine(world: World, fired: list[dict]) -> None:  # noqa: F811
    assert _refine(world, "crew").status_code == 403
    r = _refine(world)
    assert r.status_code == 202, r.text
    assert fired[-1]["kind"] == "canon_refine" and fired[-1]["url"].endswith(":8205/")


@pytest.mark.parametrize("kind", [JobKind.STRUCTURE_BUILD, JobKind.PLAN_SCENE_RAPHAEL, JobKind.CANON_REFINE])
def test_no_refine_while_a_build_or_a_plan_runs(world: World, fired: list[dict], kind: JobKind) -> None:  # noqa: F811
    _job(world, kind)
    r = _refine(world)
    assert r.status_code == 409 and r.json()["detail"] == task_manager.BUSY_FOR_REFINE


def test_a_finished_job_does_not_block_a_refine(world: World, fired: list[dict]) -> None:  # noqa: F811
    _job(world, JobKind.PLAN_SCENE_RAPHAEL, status="done")
    assert _refine(world).status_code == 202


@pytest.mark.parametrize("kind", [*sorted(task_manager.PLANNING), JobKind.STRUCTURE_BUILD])
def test_no_plan_while_the_canon_is_refined(world: World, kind: JobKind) -> None:
    import asyncio

    _job(world, JobKind.CANON_REFINE)
    with pytest.raises(task_manager.Busy, match="Canon is being refined"):
        asyncio.run(task_manager.dispatch(kind, world.repos, actor_user_id=uuid4(), production_id=world.production))


def test_frames_and_renders_are_not_held_by_a_refine(world: World, fired: list[dict]) -> None:  # noqa: F811
    import asyncio

    _job(world, JobKind.CANON_REFINE)
    asyncio.run(task_manager.dispatch(JobKind.FRAME_RENDER, world.repos, actor_user_id=uuid4(),
                                      production_id=world.production))
    assert fired[-1]["kind"] == "frame_render"


def _propose(world: World, eid: str, version: int = 2) -> str:
    canon = world.repos.canon  # type: ignore[attr-defined]
    vid = str(uuid4())
    canon.version_rows[vid] = {"id": vid, "entity_id": eid, "production_id": str(world.production),
                               "version": version, "card": {"age": "30"}, "source": "refine",
                               "provenance": {"age": {"source": "script", "line": 17, "reason": ""}},
                               "wardrobe_anchor": "", "voice_pin": "", "reference_prompt": "", "created_by": None,
                               "created_at": "2026-11-12T00:00:00+00:00"}
    return vid


def test_a_proposal_is_listed_accepted_after_unlocking_and_carries_its_provenance(world: World) -> None:
    eid = add_entity(world)
    world.repos.canon.rows[eid]["locked"] = True  # type: ignore[attr-defined]
    vid = _propose(world, eid)
    director = world.headers(world.director)
    got = world.client.get(url(world, "proposals"), headers=world.headers(world.reviewer)).json()
    assert got == [{"entity_id": eid, "version_id": vid, "version": 2}]
    accept = url(world, eid, f"/versions/{vid}/accept")
    assert world.client.post(accept, headers=director).status_code == 409  # locked: unlock first
    world.client.post(url(world, eid, "/unlock"), headers=director)
    r = world.client.post(accept, headers=director)
    assert r.status_code == 200 and r.json()["current_version"] == 2
    assert r.json()["current"]["provenance"]["age"]["line"] == 17
    assert world.client.get(url(world, "proposals"), headers=director).json() == []


def test_a_proposal_is_dismissed_and_the_card_stays(world: World) -> None:
    eid = add_entity(world)
    vid = _propose(world, eid)
    director = world.headers(world.director)
    assert world.client.post(url(world, eid, f"/versions/{vid}/dismiss"), headers=director).status_code == 204
    detail = world.client.get(url(world, eid), headers=director).json()
    assert detail["current_version"] == 1 and [v["version"] for v in detail["versions"]] == [1]
    assert world.client.post(url(world, eid, f"/versions/{vid}/accept"), headers=director).status_code == 404


def test_an_older_or_current_version_is_no_proposal(world: World) -> None:
    eid = add_entity(world)
    canon = world.repos.canon  # type: ignore[attr-defined]
    current = canon.rows[eid]["current_version_id"]
    canon.version_rows[current].update({"source": "refine", "production_id": str(world.production)})
    assert world.client.get(url(world, "proposals"), headers=world.headers(world.director)).json() == []


@pytest.mark.parametrize("cls, plate", [("region", False), ("spot", False), ("unseen", False), ("set", True),
                                        (None, True)])
def test_only_sets_and_unclassed_places_get_a_plate(world: World, fired: list[dict], cls: str | None,  # noqa: F811
                                                    plate: bool) -> None:
    eid = add_entity(world, "L01", "Colombo", "location")
    canon = world.repos.canon  # type: ignore[attr-defined]
    canon.rows[eid]["class"] = cls
    canon.version_rows[canon.rows[eid]["current_version_id"]]["card"] = {"look": "a wide city street at dusk"}
    row = world.client.get(url(world, eid), headers=world.headers(world.director)).json()
    assert row["canon_class"] == cls and bool(row["no_plate"]) is not plate
    r = world.client.post(url(world, eid, "/reference-sheet"), headers=world.headers(world.director))
    assert r.status_code == (202 if plate else 409)


def test_a_place_without_a_look_is_not_painted_from_its_summary(world: World, fired: list[dict]) -> None:  # noqa: F811
    eid = add_entity(world, "L01", "Garage", "location")
    canon = world.repos.canon  # type: ignore[attr-defined]
    canon.version_rows[canon.rows[eid]["current_version_id"]]["card"] = {"summary": "Nimal and Dinu argue."}
    r = world.client.post(url(world, eid, "/reference-sheet"), headers=world.headers(world.director))
    assert r.status_code == 409 and "no look" in r.json()["detail"]


def test_a_scene_condition_is_edited_by_a_canon_editor(world: World) -> None:
    from tests.api.test_scene_looks import add_scene, ready_look

    eid = add_entity(world)
    scene_id, look_id = add_scene(world), ready_look(world, eid)["id"]
    base = f"/v1/productions/{world.production}/scenes/{scene_id}/looks"
    director = world.headers(world.director)
    world.client.put(f"{base}/{eid}", json={"look_id": look_id}, headers=director)
    r = world.client.patch(f"{base}/{eid}/condition", json={"condition": "wet  from the rain"}, headers=director)
    assert r.status_code == 200 and r.json()["condition"] == "wet from the rain"
    listed = world.client.get(base, headers=world.headers(world.reviewer)).json()["looks"]
    assert listed[0]["condition"] == "wet from the rain" and listed[0]["origin"] == "person"
    assert world.client.patch(f"{base}/{eid}/condition", json={"condition": "x"},
                              headers=world.headers(world.crew)).status_code == 403
    missing = world.client.patch(f"{base}/{uuid4()}/condition", json={"condition": "x"}, headers=director)
    assert missing.status_code == 404
