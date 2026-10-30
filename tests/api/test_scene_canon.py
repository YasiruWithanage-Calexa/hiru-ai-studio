"""The Director panel's Canon tab: a person adds canon to a scene or takes it out."""
from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import World
from tests.api.test_scenes import seed_scene


def url(world: World, scene_id: str, suffix: str = "") -> str:
    return f"/v1/productions/{world.production}/scenes/{scene_id}/canon{suffix}"


def codes(view: dict) -> list[str]:
    return [c["code"] for c in view["canon"]]


def add_prop(world: World) -> str:
    row = world.repos.canon.add(production_id=str(world.production), kind="prop", code="P01", name="Steel lunchbox",  # type: ignore[attr-defined]
                                aliases=[], core=False, locked=False)
    return str(row["id"])


def edits(world: World, s: dict) -> list[dict]:
    return [world.repos.shots.rows[x["id"]].get("person_edits") or {} for x in s["shots"]]  # type: ignore[attr-defined]


def test_a_director_adds_canon_to_every_shot_of_the_scene_and_takes_it_out_again(world: World):
    s = seed_scene(world)
    scene, prop, h = str(s["scene"]["id"]), add_prop(world), world.headers(world.director)
    assert world.client.get(f"/v1/productions/{world.production}/scenes/{scene}", headers=h).json()["canon"]
    added = world.client.put(url(world, scene, f"/{prop}"), headers=h)
    assert added.status_code == 200, added.text
    assert codes(added.json())[-1] == "P01"
    assert all(e["cast"] == {"add": [prop], "remove": []} for e in edits(world, s))

    again = world.client.put(url(world, scene, f"/{prop}"), headers=h)
    assert again.status_code == 200 and codes(again.json()).count("P01") == 1
    assert all(e["cast"]["add"] == [prop] for e in edits(world, s)), "adding twice marks nothing twice"

    removed = world.client.delete(url(world, scene, f"/{prop}"), headers=h)
    assert removed.status_code == 200 and "P01" not in codes(removed.json())
    assert edits(world, s) == [{}, {}, {}, {}], "a mark that undoes itself leaves nothing behind"


def test_taking_out_what_the_script_puts_in_the_scene_is_a_mark_and_adding_it_back_undoes_it(world: World):
    s = seed_scene(world)
    scene, h = str(s["scene"]["id"]), world.headers(world.director)
    house, nimal = str(s["house"]["id"]), next(c["id"] for c in world.client.get(
        f"/v1/productions/{world.production}/scenes/{scene}", headers=h).json()["canon"] if c["code"] == "C02")

    no_place = world.client.delete(url(world, scene, f"/{house}"), headers=h).json()
    assert "L01" not in codes(no_place) and {"C01", "C02"} <= set(codes(no_place))
    assert all(e["cast"] == {"add": [], "remove": [house]} for e in edits(world, s))

    no_nimal = world.client.delete(url(world, scene, f"/{nimal}"), headers=h).json()
    assert "C02" not in codes(no_nimal)
    removed_from = [i for i, e in enumerate(edits(world, s)) if nimal in e["cast"]["remove"]]
    assert 1 in removed_from and 3 not in removed_from, "only the shots the script puts Nimal in are marked"

    back = world.client.put(url(world, scene, f"/{house}"), headers=h).json()
    assert "L01" in codes(back)
    assert world.client.put(url(world, scene, f"/{nimal}"), headers=h).status_code == 200
    assert edits(world, s) == [{}, {}, {}, {}]


def test_adding_what_a_shot_already_has_stores_nothing(world: World):
    s = seed_scene(world)
    scene, h = str(s["scene"]["id"]), world.headers(world.director)
    assert world.client.put(url(world, scene, f"/{s['house']['id']}"), headers=h).status_code == 200
    assert edits(world, s) == [{}, {}, {}, {}]


def test_it_keeps_a_shots_own_marks(world: World):
    s = seed_scene(world)
    scene, prop, h = str(s["scene"]["id"]), add_prop(world), world.headers(world.director)
    world.repos.shots.rows[s["shots"][0]["id"]]["person_edits"] = {"dop_note": "Hold wide."}  # type: ignore[attr-defined]
    world.client.put(url(world, scene, f"/{prop}"), headers=h)
    world.client.delete(url(world, scene, f"/{prop}"), headers=h)
    assert edits(world, s)[0] == {"dop_note": "Hold wide."}


def test_changing_a_scenes_canon_needs_the_right_an_open_scene_and_a_real_item(world: World):
    s = seed_scene(world)
    scene, prop, h = str(s["scene"]["id"]), add_prop(world), world.headers(world.director)
    assert world.client.put(url(world, scene, f"/{prop}"), headers=world.headers(world.crew)).status_code == 403
    assert world.client.delete(url(world, scene, f"/{prop}"), headers=world.headers(world.crew)).status_code == 403
    assert world.client.put(url(world, scene, f"/{prop}"), headers=world.headers(world.outsider)).status_code == 404
    assert world.client.put(url(world, str(uuid4()), f"/{prop}"), headers=h).status_code == 404
    assert world.client.put(url(world, scene, f"/{uuid4()}"), headers=h).status_code == 404

    world.repos.scenes.rows[scene]["status"] = "approved"  # type: ignore[attr-defined]
    locked = world.client.put(url(world, scene, f"/{prop}"), headers=h)
    assert locked.status_code == 409 and "approved" in locked.json()["detail"]
    assert edits(world, s) == [{}, {}, {}, {}]


def test_a_scene_without_shots_cannot_have_its_canon_changed(world: World):
    seed_scene(world)
    other = next(x for x in world.repos.scenes.rows.values() if x["number"] == 2)  # type: ignore[attr-defined]
    prop = add_prop(world)
    r = world.client.put(url(world, str(other["id"]), f"/{prop}"), headers=world.headers(world.director))
    assert r.status_code == 409 and "shots" in r.json()["detail"]
