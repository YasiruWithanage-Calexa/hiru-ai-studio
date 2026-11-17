"""The shot page's one read equals the five reads it replaces (plan/2026-11-08c phase 4)."""
from __future__ import annotations

from tests.api.conftest import World
from tests.api.test_production import design, open_scene
from tests.api.test_scenes import url


def test_page_answers_what_the_five_routes_answer(world: World) -> None:
    s = open_scene(world)
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
    s = open_scene(world)
    r = world.client.get(url(world, f"/scenes/{world.admin}/page"), headers=world.headers(world.producer))
    assert r.status_code == 404
    assert s  # the scene exists; this id does not


def test_a_stranger_gets_404(world: World) -> None:
    s = open_scene(world)
    r = world.client.get(url(world, f"/scenes/{s['scene']['id']}/page"), headers=world.headers(world.outsider))
    assert r.status_code == 404


def test_page_reads_the_scene_rows_once(world: World) -> None:
    """plan/2026-11-13b phase 1: the loaders under /page share one read of the scene, shots, lines and episode."""
    from typing import Any

    from api.repositories.memo import MEMOISED, MemoRepo

    s = open_scene(world)
    design(world, s)
    calls: dict[str, int] = {}

    class Spy:
        def __init__(self, inner: Any, name: str) -> None:
            self.inner, self.name = inner, name

        def __getattr__(self, attr: str) -> Any:
            target = getattr(self.inner, attr)
            if attr not in MEMOISED[self.name]:
                return target

            async def counted(*a: Any, **k: Any) -> Any:
                key = f"{self.name}.{attr}"
                calls[key] = calls.get(key, 0) + 1
                return await target(*a, **k)

            return counted

    # Every repository goes through the memo, as `build_supabase_repos` does: a read the memo does not know as one
    # (plan/2026-11-13d F13: `direction.series`) clears it, and this test then sees the repeated reads.
    for name, repo in list(vars(world.repos).items()):
        setattr(world.repos, name, MemoRepo(Spy(repo, name) if name in MEMOISED else repo, name))
    scene_id = s["scene"]["id"]
    r = world.client.get(url(world, f"/scenes/{scene_id}/page"), headers=world.headers(world.producer))
    assert r.status_code == 200, r.text
    assert calls["scenes.get"] == 1
    assert calls["shots.list"] == 1
    assert calls["lines.list"] == 1
    assert calls["episodes.get"] == 1
    assert calls["canon.list"] == 1


def test_page_carries_the_planner_and_the_cast_looks(world: World) -> None:
    """plan/2026-11-13b phases 2 and 3: what the director page used to ask for in 4 + 1 + N requests."""
    s = open_scene(world)
    design(world, s)
    scene_id = s["scene"]["id"]
    h = world.headers(world.producer)
    body = world.client.get(url(world, f"/scenes/{scene_id}/page"), headers=h).json()
    assert body["shot_planner"] in {"classic", "adam", "david", "jonathan", "raphael"}
    assert set(body["planners_with_plans"]) <= {"adam", "david", "jonathan", "raphael"}
    cast = [c["id"] for c in body["view"]["canon"] if c["kind"] == "character"]
    assert set(body["cast_looks"]) == set(cast)
    for cid, looks in body["cast_looks"].items():
        assert looks == world.client.get(url(world, f"/canon/{cid}/looks"), headers=h).json()
    assert body["scene_looks"] == world.client.get(url(world, f"/scenes/{scene_id}/looks"), headers=h).json()


def test_planners_with_plans_counts_only_a_plan_its_own_planner_wrote() -> None:
    from api.routers.page import planners_with_plans

    scene = {"adam": {}, "david": {"planner": "david"}, "jonathan": {"planner": "adam"}, "raphael": None}
    assert planners_with_plans(scene) == ["david"]


def test_the_page_carries_the_scenes_packet_or_says_there_is_none(world: World) -> None:
    """plan/2026-11-13d phase 4 (F12): the director page asked `/packet` on every open and got a 404 without one."""
    s = open_scene(world)
    design(world, s)
    sid = s["scene"]["id"]
    h = world.headers(world.producer)
    assert world.client.get(url(world, f"/scenes/{sid}/page"), headers=h).json()["packet"] is None
    world.repos.packets.rows[sid] = {"scene_id": sid, "production_id": str(world.production),  # type: ignore[attr-defined]
                                     "scene_key": "E01-S01", "packet": {"scene": {"heading": "EXT."}},
                                     "waits": ["a person's dialogue check"], "script_version": 1}
    got = world.client.get(url(world, f"/scenes/{sid}/page"), headers=h).json()["packet"]
    assert got == world.client.get(url(world, f"/scenes/{sid}/packet"), headers=h).json()
    assert got["waits"] == ["a person's dialogue check"] and got["ready"] is False
