"""plan/2026-11-19: the longest take and the take lengths, chosen when a production is created."""
from __future__ import annotations

from tests.api.conftest import World
from tests.api.test_scenes import seed_scene, url

BASE = {"title": "Long takes", "orientation": "vertical", "kind": "daily"}


def test_the_longest_take_and_the_lengths_are_chosen_at_creation_and_never_change(world: World):
    admin = world.headers(world.admin)
    r = world.client.post("/v1/productions", json={**BASE, "settings": {"max_take_s": 15, "take_lengths": "any"}},
                          headers=admin)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (r.json()["settings"]["max_take_s"], r.json()["settings"]["take_lengths"]) == (15, "any")
    for change in ({"max_take_s": 10}, {"take_lengths": "steps"}):
        r = world.client.patch(f"/v1/productions/{pid}", json={"settings": change}, headers=admin)
        assert r.status_code == 422 and "chosen once" in r.text, change
    # other settings save; the longest take they did not send is kept
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"spoken_language": "en"}}, headers=admin)
    assert r.status_code == 200, r.text
    assert (r.json()["settings"]["max_take_s"], r.json()["settings"]["take_lengths"]) == (15, "any")


def test_a_shot_takes_the_productions_lengths_and_the_scene_says_them(world: World):
    s = seed_scene(world, settings={"max_take_s": 10, "take_lengths": "steps"})
    scene = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.director)).json()
    assert scene["take_lengths"] == [4, 6, 8, 10]
    shot = s["shots"][1]["id"]
    r = world.client.patch(url(world, f"/shots/{shot}"), json={"duration_s": 10},
                           headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["shots"] if x["id"] == shot)["duration_s"] == 10
    r = world.client.patch(url(world, f"/shots/{shot}"), json={"duration_s": 7},
                           headers=world.headers(world.director))
    assert r.status_code == 422 and "4, 6, 8 or 10 s, not 7 s" in r.json()["detail"]


def test_an_old_production_keeps_4_6_8(world: World):
    s = seed_scene(world)
    scene = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.director)).json()
    assert scene["take_lengths"] == [4, 6, 8]
    r = world.client.patch(url(world, f"/shots/{s['shots'][1]['id']}"), json={"duration_s": 10},
                           headers=world.headers(world.director))
    assert r.status_code == 422


def test_an_old_production_chooses_once_and_every_shot_keeps_its_length(world: World):
    """Option 3 (the person, 2026-11-19): a production made before the plan may choose the longest take and the take
    lengths once; every shot it has is fixed at its length first, so nothing already made is re-timed."""
    s = seed_scene(world)
    director, admin = world.headers(world.director), world.headers(world.admin)
    before = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=director).json()
    lengths = {x["id"]: x["duration_s"] for x in before["shots"]}
    pid = str(world.production)

    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"take_lengths": "any"}}, headers=admin)
    assert r.status_code == 422 and "longest take" in r.text  # the mode alone is not a choice
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"max_take_s": 15, "take_lengths": "any"}},
                           headers=admin)
    assert r.status_code == 200, r.text
    assert (r.json()["settings"]["max_take_s"], r.json()["settings"]["take_lengths"]) == (15, "any")
    rows = world.repos.shots._scoped(world.production)  # type: ignore[attr-defined]
    assert rows and all(row["duration_locked"] for row in rows)

    after = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=director).json()
    assert after["take_lengths"] == list(range(3, 16))
    assert {x["id"]: x["duration_s"] for x in after["shots"]} == lengths, "no shot is re-timed"
    assert any(a["action"] == "production.take_lengths" for a in world.repos.audit.entries)  # type: ignore[attr-defined]

    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"max_take_s": 10}}, headers=admin)
    assert r.status_code == 422 and "chosen once" in r.text
    shot = s["shots"][1]["id"]
    assert world.client.patch(url(world, f"/shots/{shot}"), json={"duration_s": 13},
                              headers=director).status_code == 200  # a person may still set any length it allows


def test_a_fixed_shot_length_is_no_longer_offered_but_one_already_chosen_is_kept(world: World):
    """plan/2026-11-20 D4: "Always 8 s" is gone. A new or changed fixed length is refused; a production that has one
    keeps it when its other settings are saved, and may drop it."""
    admin = world.headers(world.admin)
    r = world.client.post("/v1/productions", json={**BASE, "settings": {"fixed_shot_seconds": 8}}, headers=admin)
    assert r.status_code == 422 and "no longer offered" in r.text
    pid = str(world.production)
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"fixed_shot_seconds": 8}}, headers=admin)
    assert r.status_code == 422 and "no longer offered" in r.text
    world.repos.productions.rows[pid]["settings"] = {"fixed_shot_seconds": 8}  # type: ignore[attr-defined]
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"fixed_shot_seconds": 8,
                                                                        "spoken_language": "en"}}, headers=admin)
    assert r.status_code == 200 and r.json()["settings"]["fixed_shot_seconds"] == 8, r.text
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"fixed_shot_seconds": 6}}, headers=admin)
    assert r.status_code == 422
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"fixed_shot_seconds": None}}, headers=admin)
    assert r.status_code == 200 and r.json()["settings"]["fixed_shot_seconds"] is None, r.text
