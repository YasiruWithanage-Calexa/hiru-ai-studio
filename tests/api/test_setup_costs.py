"""Setup costs (plan/2026-11-23b): GET .../setup-cost for a production and an episode. Who sees them, what is in them
(dated entries at final prices, nothing else), and that setup never shows in a scene's figure. No network, no
database."""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from api.services import setup_costs
from contracts.costs import with_margin
from tests.api.conftest import World
from tests.api.test_scenes import seed_scene

ONE = with_margin(1_250_000, "text")  # a 1M-token gpt-5 call at its final price


@pytest.fixture(autouse=True)
def _fresh():
    setup_costs.clear()
    yield
    setup_costs.clear()


def usage(world: World, *, phase: str, scene: str | None = None, job: str | None = None, i: int = 1_000_000,
          at: str = "2026-11-06T00:00:00+00:00") -> None:
    world.repos.costs.usage.append({  # type: ignore[attr-defined]
        "id": len(world.repos.costs.usage) + 1, "production_id": str(world.production),  # type: ignore[attr-defined]
        "scene_id": scene, "job_id": job, "phase": phase, "model": "gpt-5", "input_tokens": i,
        "cached_input_tokens": 0, "output_tokens": 0, "created_at": at})


def job(world: World, kind: str, **request: Any) -> str:
    jid = str(uuid4())
    world.repos.costs.jobs[jid] = {**request, "_created_at": request.pop("_at", "")}  # type: ignore[attr-defined]
    world.repos.costs.job_kinds[jid] = kind  # type: ignore[attr-defined]
    return jid


def episode_url(world: World, episode_id: Any) -> str:
    return f"/v1/productions/{world.production}/episodes/{episode_id}/setup-cost"


def production_url(world: World) -> str:
    return f"/v1/productions/{world.production}/setup-cost"


def get(world: World, url: str, who: UUID | None = None) -> dict:
    r = world.client.get(url, headers=world.headers(who or world.producer))
    assert r.status_code == 200, r.text
    return r.json()


# ── access ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["producer", "director", "admin"])
def test_the_people_who_see_costs_see_setup(world: World, who: str):
    s = seed_scene(world)
    assert get(world, episode_url(world, s["episode"]["id"]), getattr(world, who))["currency"] == "USD"
    assert get(world, production_url(world), getattr(world, who))["currency"] == "USD"


@pytest.mark.parametrize("who", ["writer", "crew", "reviewer"])
def test_everyone_else_gets_403(world: World, who: str):
    s = seed_scene(world)
    for url in (episode_url(world, s["episode"]["id"]), production_url(world)):
        r = world.client.get(url, headers=world.headers(getattr(world, who)))
        assert r.status_code == 403 and "micros" not in r.text


def test_an_episode_of_another_production_is_404(world: World):
    seed_scene(world)
    assert world.client.get(episode_url(world, uuid4()), headers=world.headers(world.producer)).status_code == 404


# ── what is in them ───────────────────────────────────────────────────────────────────────────


def test_an_episode_setup_lists_the_upload_and_each_replan_at_final_prices(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    usage(world, phase="raphael.plan", scene=sid, at="2026-11-02T00:00:00+00:00")  # the upload-time plan
    replan = job(world, "plan_scene_raphael", scene_id=sid)
    usage(world, phase="raphael.plan", scene=sid, job=replan, at="2026-11-09T00:00:00+00:00")
    usage(world, phase="zora.reply", scene=sid)  # chat: scene cost, not setup
    got = get(world, episode_url(world, s["episode"]["id"]))
    assert set(got) == {"currency", "total_micros", "complete", "entries"}
    assert got["total_micros"] == 2 * ONE and got["complete"] is True
    assert [(e["label"], e["total_micros"]) for e in got["entries"]] == [
        ("Upload and first plan", ONE), ("Re-plan, scene 1", ONE)]
    assert set(got["entries"][0]) == {"label", "at", "total_micros", "complete"}


def test_production_setup_holds_canon_and_sheets(world: World):
    seed_scene(world)
    face = job(world, "frame_render", entity_id=str(uuid4()))
    usage(world, phase="frame_render.image", job=face)
    usage(world, phase="canon_extract.cards")
    got = get(world, production_url(world))
    assert {e["label"]: e["total_micros"] for e in got["entries"]} == {
        "Character sheets": with_margin(1_250_000, "image"), "Canon": ONE}


def test_setup_and_scene_cost_never_count_the_same_spend(world: World):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    scene_url = f"/v1/productions/{world.production}/scenes/{sid}/cost"
    scene_before = get(world, scene_url)["total_micros"]
    usage(world, phase="raphael.plan", scene=sid)
    usage(world, phase="shot_producer.design", scene=sid)
    assert get(world, scene_url)["total_micros"] == scene_before + ONE  # only the design
    assert get(world, episode_url(world, s["episode"]["id"]))["total_micros"] == ONE  # only Raphael


def test_the_answer_is_kept_and_cleared_when_a_job_ends(world: World):
    from api.cache import job_ended

    s = seed_scene(world)
    usage(world, phase="raphael.plan", scene=s["scene"]["id"])
    first = get(world, episode_url(world, s["episode"]["id"]))["total_micros"]
    usage(world, phase="raphael.plan", scene=s["scene"]["id"])
    assert get(world, episode_url(world, s["episode"]["id"]))["total_micros"] == first
    job_ended()
    assert get(world, episode_url(world, s["episode"]["id"]))["total_micros"] == 2 * first
