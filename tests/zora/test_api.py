"""Phase 7 (plan/2026-11-06e §4.10): Zora's routes, the function stood in for. Which scenes are Zora's (D3), who may
change the plan, the stored message first, the actions, the pinned-treatment job, and the API's undo replay held to
the function's."""
from __future__ import annotations

import random
from collections.abc import AsyncIterator
from typing import Any

import pytest

from api.services import director as director_service
from api.services import zora as zora_service
from hiru_ai.steps.zora.zora_save import logic as save_logic
from tests.api.conftest import World, _settings, world  # noqa: F401  (the API's own fixtures)
from tests.api.test_director import frames
from tests.api.test_scenes import seed_scene, url

Row = dict[str, Any]


@pytest.fixture(autouse=True)
def _zora_on(monkeypatch: pytest.MonkeyPatch, _settings: None) -> None:  # noqa: F811
    from api.config import get_settings

    monkeypatch.setenv("ZORA__ENABLED", "true")
    get_settings.cache_clear()


class Function:
    """Stands in for the zora_chat function: records what it is sent."""

    def __init__(self) -> None:
        self.turns: list[Row] = []
        self.actions: list[Row] = []

    async def stream(self, payload: Row) -> AsyncIterator[bytes]:
        self.turns.append(payload)
        yield director_service.sse("ops", {"changes": [], "nothing_changed": True})
        yield director_service.sse("done", {"message_id": "m1", "lane": "chat"})

    async def act(self, payload: Row) -> Row:
        self.actions.append(payload)
        return {"ok": True, "text": "Undone.", "revision": 3, "can_undo": True, "can_redo": True}


@pytest.fixture
def fn(world: World) -> Function:  # noqa: F811
    f = Function()
    world.client.app.dependency_overrides[zora_service.get_streamer] = lambda: f.stream  # type: ignore[attr-defined]
    world.client.app.dependency_overrides[zora_service.get_actor] = lambda: f.act  # type: ignore[attr-defined]
    return f


def planned(world: World) -> str:  # noqa: F811
    s = seed_scene(world)
    sid = s["scene"]["id"]
    world.repos.scenes.rows[sid]["jonathan"] = {"planner": "jonathan", "plan": {  # type: ignore[attr-defined]
        "treatment": {"logline": "x", "arc": []}, "shots": []}, "person": {"locked": ["S03.lens"]}}
    return str(sid)


def test_a_scene_jonathan_planned_is_zoras_and_any_other_keeps_the_classic_chat(world: World, fn: Function):  # noqa: F811
    plain = seed_scene(world)["scene"]["id"]
    got = world.client.get(url(world, f"/scenes/{plain}/zora"), headers=world.headers(world.reviewer)).json()
    assert got["available"] is False and "Plan it with Jonathan first" in got["reason"]
    r = world.client.post(url(world, f"/scenes/{plain}/zora/turn"), json={"message": "hi"},
                          headers=world.headers(world.director))
    assert r.status_code == 409 and fn.turns == []
    sid = planned(world)
    got = world.client.get(url(world, f"/scenes/{sid}/zora"), headers=world.headers(world.reviewer)).json()
    assert got["available"] is True and got["locked"] == ["S03.lens"] and got["undo_available"] is False


def test_zora_switched_off_sends_every_scene_to_the_classic_chat(world: World, fn: Function,  # noqa: F811
                                                                 monkeypatch: pytest.MonkeyPatch):
    from api.config import get_settings

    sid = planned(world)
    monkeypatch.setenv("ZORA__ENABLED", "false")
    get_settings.cache_clear()
    got = world.client.get(url(world, f"/scenes/{sid}/zora"), headers=world.headers(world.reviewer)).json()
    assert got["enabled"] is False and got["available"] is False
    assert world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": "hi"},
                             headers=world.headers(world.director)).status_code == 409


def test_a_turn_stores_the_message_then_streams_and_the_function_is_told_who_may_edit(world: World,  # noqa: F811
                                                                                      fn: Function):
    sid = planned(world)
    for user, can_edit in ((world.director, True), (world.reviewer, False), (world.writer, False)):
        r = world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": " S03 on an 85 "},
                              headers=world.headers(user))
        assert r.status_code == 200 and [e for e, _ in frames(r.text)] == ["accepted", "ops", "done"]
        assert fn.turns[-1]["can_edit"] is can_edit and fn.turns[-1]["message"] == "S03 on an 85"
    assert len({t["thread_id"] for t in fn.turns}) == 1  # the scene's one main thread
    assert world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": "hi"},
                             headers=world.headers(world.outsider)).status_code == 404


def test_undo_redo_and_locks_need_the_direct_permission_and_go_to_the_function(world: World,  # noqa: F811
                                                                               fn: Function):
    sid = planned(world)
    assert world.client.post(url(world, f"/scenes/{sid}/zora/undo"),
                             headers=world.headers(world.reviewer)).status_code == 403
    r = world.client.post(url(world, f"/scenes/{sid}/zora/undo"), headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["revision"] == 3 and fn.actions[-1]["kind"] == "undo"
    r = world.client.post(url(world, f"/scenes/{sid}/zora/lock"), json={"path": "S02.size"},
                          headers=world.headers(world.director))
    assert r.status_code == 200 and fn.actions[-1] == {**fn.actions[-1], "kind": "lock", "path": "S02.size",
                                                       "can_edit": True}


def test_plan_shots_from_this_treatment_dispatches_jonathan_with_the_treatment_pinned(
        world: World, fn: Function, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from api.workers import task_manager

    fired: list[Row] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: fired.append({"url": u, **payload.model_dump(mode="json")}))
    sid = planned(world)
    r = world.client.post(url(world, f"/scenes/{sid}/zora/plan-shots"), headers=world.headers(world.director))
    assert r.status_code == 202 and fired[0]["kind"] == "plan_scene_jonathan" and ":8211" in fired[0]["url"]
    state = fired[0]["state"]
    assert state["replan"] is True and state["scene_ids"] == [sid] and state["pinned"][sid]["logline"] == "x"
    assert world.client.post(url(world, f"/scenes/{sid}/zora/plan-shots"),
                             headers=world.headers(world.writer)).status_code == 403


def test_the_apis_undo_replay_is_the_functions():
    rng = random.Random(7)  # noqa: S311 (a test sequence, not a secret)
    for _ in range(300):
        rows = [{"revision": 1, "kind": "base"}]
        for n in range(2, rng.randint(2, 14)):
            rows.append({"revision": n, "kind": rng.choice(["turn", "use", "undo", "undo", "redo"])})
        st = save_logic.Stack.of([{**r, "scene_id": "s", "stored": {}} for r in rows])
        assert zora_service.undo_redo(rows) == (st.can_undo(), st.can_redo())
