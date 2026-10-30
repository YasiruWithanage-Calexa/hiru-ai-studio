from __future__ import annotations

from uuid import uuid4

import pytest

from api.workers import task_manager
from tests.api.conftest import World
from tests.api.test_canon import add_entity


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: calls.append({"url": u, **payload.model_dump(mode="json")}))
    return calls


VILLAGE = {"name": "Village girl", "ranges": [{"from": 1, "to": 20}], "outfit": "faded blue frock",
           "hair": "long plait", "accessories": "silver chain, a straw cap"}


def url(world: World, entity_id: str, suffix: str = "") -> str:
    return f"/v1/productions/{world.production}/canon/{entity_id}/looks{suffix}"


def give_base_sheet(world: World, entity_id: str) -> None:
    canon = world.repos.canon  # type: ignore[attr-defined]
    canon.version_rows[canon.rows[entity_id]["current_version_id"]]["reference_assets"] = [
        {"path": f"{world.production}/{entity_id}/base.png"}]


def make_look(world: World, entity_id: str, **fields) -> dict:
    r = world.client.post(url(world, entity_id), json={**VILLAGE, **fields}, headers=world.headers(world.director))
    assert r.status_code == 201, r.text
    return r.json()


def test_a_director_writes_looks_and_everyone_reads_them(world: World):
    eid = add_entity(world)
    for number in (1, 2, 3):
        world.repos.episodes.add(production_id=str(world.production), number=number)  # type: ignore[attr-defined]
    look = make_look(world, eid)
    assert look["status"] == "draft" and look["sheet_url"] == ""
    assert look["ranges"] == [{"from": 1, "to": 20}] and look["accessories"] == "silver chain, a straw cap"
    seen = world.client.get(url(world, eid), headers=world.headers(world.reviewer)).json()
    assert seen["episode_count"] == 3 and [x["name"] for x in seen["looks"]] == ["Village girl"]
    assert world.client.post(url(world, eid), json={**VILLAGE, "name": "Other"},
                             headers=world.headers(world.crew)).status_code == 403
    assert world.client.get(url(world, eid), headers=world.headers(world.outsider)).status_code == 404


def test_a_look_needs_a_unique_name_and_real_episode_ranges(world: World):
    eid = add_entity(world)
    make_look(world, eid)
    h = world.headers(world.director)
    same = world.client.post(url(world, eid), json={**VILLAGE, "name": "  village GIRL "}, headers=h)
    assert same.status_code == 409
    backwards = world.client.post(url(world, eid), json={**VILLAGE, "name": "A", "ranges": [{"from": 9, "to": 3}]},
                                  headers=h)
    assert backwards.status_code == 422
    assert world.client.post(url(world, eid), json={**VILLAGE, "name": "B", "ranges": []}, headers=h).status_code == 422


def test_only_characters_have_looks(world: World):
    harbour = add_entity(world, "L01", "Harbour", "location")
    h = world.headers(world.director)
    assert world.client.get(url(world, harbour), headers=h).status_code == 409
    assert world.client.post(url(world, harbour), json=VILLAGE, headers=h).status_code == 409
    assert world.client.get(url(world, str(uuid4())), headers=h).status_code == 404


def test_a_look_is_edited_and_a_ready_look_returns_to_draft_when_its_clothes_change(world: World):
    eid = add_entity(world)
    look = make_look(world, eid)
    h = world.headers(world.director)
    world.repos.looks.rows[look["id"]].update(  # type: ignore[attr-defined]
        status="ready", sheet_assets=[{"path": f"{world.production}/{eid}/looks/a.png"}])
    renamed = world.client.patch(url(world, eid, f"/{look['id']}"), json={"ranges": [{"from": 1, "to": 5}]}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["status"] == "ready", "episodes do not change the sheet"
    assert renamed.json()["sheet_url"].startswith("http://localhost:8000/files/")
    assert "a.png" not in renamed.json()["sheet_url"]
    changed = world.client.patch(url(world, eid, f"/{look['id']}"), json={"outfit": "a green frock"}, headers=h)
    assert changed.json()["status"] == "draft" and changed.json()["outfit"] == "a green frock"
    nothing = world.client.patch(url(world, eid, f"/{look['id']}"), json={"outfit": "a green frock"}, headers=h)
    assert nothing.status_code == 200 and nothing.json()["outfit"] == "a green frock"
    other = make_look(world, eid, name="Office")
    clash = world.client.patch(url(world, eid, f"/{other['id']}"), json={"name": "Village Girl"}, headers=h)
    assert clash.status_code == 409


def test_a_look_sheet_is_made_from_the_base_sheet(world: World, fired: list[dict]):
    eid = add_entity(world)
    look = make_look(world, eid)
    h = world.headers(world.director)
    path = url(world, eid, f"/{look['id']}/sheet")
    no_base = world.client.post(path, headers=h)
    assert no_base.status_code == 409 and "base sheet" in no_base.json()["detail"]
    give_base_sheet(world, eid)
    assert world.client.post(path, headers=world.headers(world.crew)).status_code == 403
    r = world.client.post(path, headers=h)
    assert r.status_code == 202 and fired[-1]["state"] == {"look_id": look["id"]}
    bare = make_look(world, eid, name="Bare", outfit="", hair="", accessories="")
    nothing = world.client.post(url(world, eid, f"/{bare['id']}/sheet"), headers=h)
    assert nothing.status_code == 409 and "what they wear" in nothing.json()["detail"]
    assert world.client.post(url(world, eid, f"/{uuid4()}/sheet"), headers=h).status_code == 404


def test_a_look_is_ready_only_once_it_has_a_sheet_and_can_go_back_to_draft(world: World):
    eid = add_entity(world)
    look = make_look(world, eid)
    h = world.headers(world.director)
    ready = url(world, eid, f"/{look['id']}/ready")
    assert world.client.post(ready, headers=h).status_code == 409
    world.repos.looks.rows[look["id"]]["sheet_assets"] = [{"path": "p/a.png"}]  # type: ignore[attr-defined]
    assert world.client.post(ready, headers=h).json()["status"] == "ready"
    assert world.client.post(ready, headers=h).json()["status"] == "ready", "marking twice changes nothing"
    assert world.client.post(url(world, eid, f"/{look['id']}/draft"), headers=h).json()["status"] == "draft"


def test_a_look_can_be_deleted(world: World):
    eid = add_entity(world)
    look = make_look(world, eid)
    h = world.headers(world.director)
    assert world.client.delete(url(world, eid, f"/{look['id']}"), headers=world.headers(world.crew)).status_code == 403
    assert world.client.delete(url(world, eid, f"/{look['id']}"), headers=h).status_code == 204
    assert world.client.get(url(world, eid), headers=h).json()["looks"] == []
    assert world.client.delete(url(world, eid, f"/{look['id']}"), headers=h).status_code == 404
