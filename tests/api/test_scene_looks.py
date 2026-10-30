from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import World
from tests.api.test_canon import add_entity
from tests.api.test_looks import make_look


def add_scene(world: World) -> str:
    pid = str(world.production)
    ep = world.repos.episodes.add(production_id=pid, number=1, title="The Return", synopsis="", status="ready")  # type: ignore[attr-defined]
    scene = world.repos.scenes.add(production_id=pid, episode_id=ep["id"], number=1, heading="INT. HOUSE", title="",  # type: ignore[attr-defined]
                                   envelope_s=60, status="draft", script=[], script_version=1)
    return str(scene["id"])


def url(world: World, scene_id: str, suffix: str = "") -> str:
    return f"/v1/productions/{world.production}/scenes/{scene_id}/looks{suffix}"


def ready_look(world: World, entity_id: str, **fields) -> dict:
    look = make_look(world, entity_id, **fields)
    world.repos.looks.rows[look["id"]].update(status="ready")  # type: ignore[attr-defined]
    return look


def test_a_director_picks_the_look_a_scene_uses_and_everyone_reads_it(world: World):
    eid, scene = add_entity(world), add_scene(world)
    look = ready_look(world, eid)
    assert world.client.get(url(world, scene), headers=world.headers(world.reviewer)).json() == {"looks": []}
    put = world.client.put(url(world, scene, f"/{eid}"), json={"look_id": look["id"]},
                           headers=world.headers(world.director))
    assert put.status_code == 200 and put.json() == {"entity_id": eid, "look_id": look["id"]}
    seen = world.client.get(url(world, scene), headers=world.headers(world.reviewer)).json()
    assert seen == {"looks": [{"entity_id": eid, "look_id": look["id"]}]}
    assert world.client.get(url(world, scene), headers=world.headers(world.outsider)).status_code == 404


def test_a_second_pick_replaces_the_first_and_clearing_goes_back_to_the_episode_rule(world: World):
    eid, scene = add_entity(world), add_scene(world)
    first, second = ready_look(world, eid), ready_look(world, eid, name="Heiress")
    h = world.headers(world.director)
    world.client.put(url(world, scene, f"/{eid}"), json={"look_id": first["id"]}, headers=h)
    world.client.put(url(world, scene, f"/{eid}"), json={"look_id": second["id"]}, headers=h)
    chosen = world.client.get(url(world, scene), headers=h).json()["looks"]
    assert [x["look_id"] for x in chosen] == [second["id"]]
    assert world.client.delete(url(world, scene, f"/{eid}"), headers=h).status_code == 204
    assert world.client.get(url(world, scene), headers=h).json() == {"looks": []}
    assert world.client.delete(url(world, scene, f"/{eid}"), headers=h).status_code == 204, "clearing twice is fine"


def test_only_a_ready_look_of_that_character_can_be_picked(world: World):
    eid, other, scene = add_entity(world), add_entity(world, "C02", "Nimal"), add_scene(world)
    h = world.headers(world.director)
    draft = make_look(world, eid)
    not_ready = world.client.put(url(world, scene, f"/{eid}"), json={"look_id": draft["id"]}, headers=h)
    assert not_ready.status_code == 409 and "ready" in not_ready.json()["detail"]
    theirs = ready_look(world, other)
    wrong = world.client.put(url(world, scene, f"/{eid}"), json={"look_id": theirs["id"]}, headers=h)
    assert wrong.status_code == 404, "a look of another character is not found for this one"
    missing = world.client.put(url(world, scene, f"/{eid}"), json={"look_id": str(uuid4())}, headers=h)
    assert missing.status_code == 404


def test_picking_needs_a_character_a_scene_and_the_right_to_edit_canon(world: World):
    eid, scene = add_entity(world), add_scene(world)
    look = ready_look(world, eid)
    body = {"look_id": look["id"]}
    assert world.client.put(url(world, scene, f"/{eid}"), json=body,
                            headers=world.headers(world.crew)).status_code == 403
    assert world.client.delete(url(world, scene, f"/{eid}"), headers=world.headers(world.crew)).status_code == 403
    h = world.headers(world.director)
    assert world.client.put(url(world, str(uuid4()), f"/{eid}"), json=body, headers=h).status_code == 404
    assert world.client.put(url(world, scene, f"/{uuid4()}"), json=body, headers=h).status_code == 404
    harbour = add_entity(world, "L01", "Harbour", "location")
    assert world.client.put(url(world, scene, f"/{harbour}"), json=body, headers=h).status_code == 409
