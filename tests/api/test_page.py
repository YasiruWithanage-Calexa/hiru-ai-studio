"""The shot page's one read equals the five reads it replaces (plan/2026-11-08c phase 4)."""
from __future__ import annotations

from tests.api.conftest import World
from tests.api.test_production import approved_scene, design
from tests.api.test_scenes import url


def test_page_answers_what_the_five_routes_answer(world: World) -> None:
    s = approved_scene(world)
    design(world, s)
    h = world.headers(world.producer)
    scene_id, episode_id = s["scene"]["id"], s["scene"]["episode_id"]
    page = world.client.get(url(world, f"/scenes/{scene_id}/page"), headers=h)
    assert page.status_code == 200, page.text
    body = page.json()
    one = lambda tail: world.client.get(url(world, tail), headers=h).json()  # noqa: E731
    assert body["view"] == one(f"/scenes/{scene_id}")
    assert body["production"] == one(f"/scenes/{scene_id}/production")
    assert body["episode"] == one(f"/episodes/{episode_id}")
    assert body["threads"] == one(f"/scenes/{scene_id}/threads")
    assert body["access"] == one("/access")
    assert body["access"]["role"] == "producer"
    assert body["messages"] == []


def test_page_for_a_scene_that_is_not_here_is_404(world: World) -> None:
    s = approved_scene(world)
    r = world.client.get(url(world, f"/scenes/{world.admin}/page"), headers=world.headers(world.producer))
    assert r.status_code == 404
    assert s  # the scene exists; this id does not


def test_a_stranger_gets_404(world: World) -> None:
    s = approved_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/page"), headers=world.headers(world.outsider))
    assert r.status_code == 404
