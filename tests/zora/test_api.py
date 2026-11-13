"""Zora's routes (plan/2026-11-06e §4.10; plan/2026-11-13 §3.10), the function stood in for: every scene is Zora's
when she is on, who may change the shots, the stored message first, Accept / Reject on a card (a stale card, an approved
scene), the actions, "Re-plan the scene" through the production's own planner, and the API's undo replay held to the
function's."""
from __future__ import annotations

import random
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest

from api.services import director as director_service
from api.services import zora as zora_service
from hiru_ai.systems.zora.zora_chat.store import Stack
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
    """Stands in for the zora_chat function: records what it is sent; a stale card is refused as the function does."""

    def __init__(self) -> None:
        self.turns: list[Row] = []
        self.actions: list[Row] = []
        self.stale = False

    async def stream(self, payload: Row) -> AsyncIterator[bytes]:
        self.turns.append(payload)
        yield director_service.sse("ops", {"changes": [], "nothing_changed": True})
        yield director_service.sse("done", {"message_id": "m1", "lane": "chat"})

    async def act(self, payload: Row) -> Row:
        self.actions.append(payload)
        if self.stale and payload["kind"] == "accept":
            return {"ok": False, "text": "The shots changed since this card was made; ask me again.", "revision": 0}
        return {"ok": True, "text": "Done.", "revision": 3, "can_undo": True, "can_redo": True,
                "message": {"id": "m2", "text": "", "blocks": [{"kind": "text", "text": "It's in."}]}}


@pytest.fixture
def fn(world: World) -> Function:  # noqa: F811
    f = Function()
    world.client.app.dependency_overrides[zora_service.get_streamer] = lambda: f.stream  # type: ignore[attr-defined]
    world.client.app.dependency_overrides[zora_service.get_actor] = lambda: f.act  # type: ignore[attr-defined]
    return f


def planned(world: World, *, settings: dict | None = None) -> str:  # noqa: F811
    """A scene with shot rows; its third shot's size is the person's (`person_edits.zora_locks`)."""
    s = seed_scene(world, settings=settings)
    sid = str(s["scene"]["id"])
    shots = sorted((r for r in world.repos.shots.rows.values() if r["scene_id"] == sid),  # type: ignore[attr-defined]
                   key=lambda r: r["number"])
    shots[2]["person_edits"] = {"zora_locks": ["size"]}
    shots[0]["duration_locked"] = True
    return sid


def card_message(world: World, sid: str) -> str:  # noqa: F811
    """A director message in the scene's thread that carries a card (block 1), as the function stores it."""
    thread = world.repos.threads.add(production_id=str(world.production), scene_id=sid,  # type: ignore[attr-defined]
                                     title="Director", created_by=str(world.director))
    messages: Any = world.repos.messages
    msg = messages.add(production_id=str(world.production), thread_id=str(thread["id"]),
                                   kind="director", text="", speaker="Zora",
                                   blocks=[{"kind": "text", "text": "Dropping S02 would…"},
                                           {"kind": "confirm", "ops": [], "made_on": "x", "reasons": ["a must clip"],
                                            "lines": [], "state": ""}])
    return str(msg["id"])


def test_every_scene_is_zoras_and_the_persons_locks_are_read_from_the_rows(world: World, fn: Function):  # noqa: F811
    plain = seed_scene(world)["scene"]["id"]
    got = world.client.get(url(world, f"/scenes/{plain}/zora"), headers=world.headers(world.reviewer)).json()
    assert got["available"] is True and got["reason"] == "" and got["locked"] == []
    sid = planned(world)
    got = world.client.get(url(world, f"/scenes/{sid}/zora"), headers=world.headers(world.reviewer)).json()
    assert got["available"] is True and got["locked"] == ["S01.take_s", "S03.size"] and got["undo_available"] is False


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
        r = world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": " Make S03 a wide "},
                              headers=world.headers(user))
        assert r.status_code == 200 and [e for e, _ in frames(r.text)] == ["accepted", "ops", "done"]
        assert fn.turns[-1]["can_edit"] is can_edit and fn.turns[-1]["message"] == "Make S03 a wide"
    assert len({t["thread_id"] for t in fn.turns}) == 1  # the scene's one main thread
    assert world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": "hi"},
                             headers=world.headers(world.outsider)).status_code == 404


def test_accept_and_reject_carry_the_message_and_the_block_and_need_the_direct_permission(world: World,  # noqa: F811
                                                                                         fn: Function):
    sid = planned(world)
    mid = card_message(world, sid)
    body = {"message_id": mid, "block": 1}
    assert world.client.post(url(world, f"/scenes/{sid}/zora/accept"), json=body,
                             headers=world.headers(world.reviewer)).status_code == 403
    r = world.client.post(url(world, f"/scenes/{sid}/zora/accept"), json=body, headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["ok"] and r.json()["message"]["id"] == "m2"
    sent = fn.actions[-1]
    assert (sent["kind"], sent["message_id"], sent["block"], sent["can_edit"]) == ("accept", mid, 1, True)
    assert UUID(sent["thread_id"])
    r = world.client.post(url(world, f"/scenes/{sid}/zora/reject"), json=body, headers=world.headers(world.director))
    assert r.status_code == 200 and fn.actions[-1]["kind"] == "reject"


def test_a_stale_card_is_refused_and_nothing_is_audited(world: World, fn: Function):  # noqa: F811
    sid = planned(world)
    mid = card_message(world, sid)
    fn.stale = True
    r = world.client.post(url(world, f"/scenes/{sid}/zora/accept"), json={"message_id": mid, "block": 1},
                          headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["ok"] is False and "changed" in r.json()["text"]


def test_a_card_from_another_scene_or_an_approved_scene_is_refused(world: World, fn: Function):  # noqa: F811
    sid = planned(world)
    other = str(seed_scene(world, 0)["scene"]["id"])
    mid = card_message(world, other)
    r = world.client.post(url(world, f"/scenes/{sid}/zora/accept"), json={"message_id": mid, "block": 1},
                          headers=world.headers(world.director))
    assert r.status_code == 404
    mine = card_message(world, sid)
    world.repos.scenes.rows[sid]["status"] = "approved"  # type: ignore[attr-defined]
    r = world.client.post(url(world, f"/scenes/{sid}/zora/accept"), json={"message_id": mine, "block": 1},
                          headers=world.headers(world.director))
    assert r.status_code == 409 and not [a for a in fn.actions if a["kind"] == "accept"]


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


@pytest.mark.parametrize(("planner", "kind"), [("raphael", "plan_scene_raphael"), ("classic", "script_split")])
def test_replan_dispatches_the_productions_own_planner(world: World, fn: Function,  # noqa: F811
                                                       monkeypatch: pytest.MonkeyPatch, planner: str, kind: str):
    from api.workers import task_manager

    fired: list[Row] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: fired.append({"url": u, **payload.model_dump(mode="json")}))
    sid = planned(world, settings={"shot_planner": planner})
    r = world.client.post(url(world, f"/scenes/{sid}/zora/plan-shots"), headers=world.headers(world.director))
    assert r.status_code == 202 and fired[0]["kind"] == kind
    assert fired[0]["state"]["replan"] is True and fired[0]["state"]["scene_ids"] == [sid]
    assert world.client.post(url(world, f"/scenes/{sid}/zora/plan-shots"),
                             headers=world.headers(world.writer)).status_code == 403


def test_the_apis_undo_replay_is_the_functions():
    rng = random.Random(7)  # noqa: S311 (a test sequence, not a secret)
    for _ in range(300):
        rows = [{"revision": 1, "kind": "base"}]
        for n in range(2, rng.randint(2, 14)):
            rows.append({"revision": n, "kind": rng.choice(["turn", "use", "undo", "undo", "redo"])})
        st = Stack.of([{**r, "scene_id": "s", "stored": {"rows": [], "lines": []}} for r in rows])
        assert zora_service.undo_redo(rows) == (st.can_undo(), st.can_redo())


def test_a_turn_that_changed_the_plan_ends_with_the_scenes_two_views(world: World, fn: Function):  # noqa: F811
    """plan/2026-11-13d phase 4 (F10): the panel puts these in its cache instead of reading the scene twice. The
    function's frames pass through untouched, even when a chunk ends inside a frame or inside a letter."""
    sid = planned(world)
    body = (director_service.sse("delta", {"text": "Wide on S03, ගේට්ටුව."})
            + director_service.sse("plan", {"revision": 4})
            + director_service.sse("done", {"message_id": "m1", "lane": "edit", "revision": 4, "suggestions": []}))
    cut = body.index("ගේ".encode()) + 1  # inside a Sinhala letter

    async def changed(payload: Row) -> AsyncIterator[bytes]:
        for part in (body[:7], body[7:cut], body[cut:]):
            yield part

    world.client.app.dependency_overrides[zora_service.get_streamer] = lambda: changed  # type: ignore[attr-defined]
    h = world.headers(world.director)
    r = world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": "Make S03 a wide"}, headers=h)
    got = frames(r.text)
    assert [e for e, _ in got] == ["accepted", "delta", "plan", "done", "views"]
    assert got[1][1]["text"] == "Wide on S03, ගේට්ටුව."
    views = got[-1][1]
    assert views["scene"] == world.client.get(url(world, f"/scenes/{sid}"), headers=h).json()
    assert views["production"] == world.client.get(url(world, f"/scenes/{sid}/production"), headers=h).json()


def test_a_chat_only_turn_sends_no_views(world: World, fn: Function):  # noqa: F811
    sid = planned(world)
    r = world.client.post(url(world, f"/scenes/{sid}/zora/turn"), json={"message": "What is S03?"},
                          headers=world.headers(world.director))
    assert "views" not in [e for e, _ in frames(r.text)]
