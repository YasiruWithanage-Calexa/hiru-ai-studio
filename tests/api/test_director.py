"""The director's routes: personas, the board, threads, the streamed turn (function stood in for),
and production memory."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from api.services import director as director_service
from contracts.director import ChoicePayload, ChoiceResult, TurnPayload
from tests.api.conftest import World
from tests.api.test_scenes import seed_scene, url


def frames(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


# ── personas and the board ─────────────────────────────────────────────────────────────────


def test_personas_are_a_library_with_no_prices(world: World):
    r = world.client.get("/v1/director-personas", headers=world.headers(world.reviewer))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5 and {"id", "name", "initials", "color", "traits"} <= set(rows[0])
    assert not any(k in rows[0] for k in ("price", "monthly_price", "tier", "charter"))
    assert world.client.get("/v1/director-personas").status_code == 401


def test_the_default_board_until_someone_picks_one(world: World):
    v = world.client.get(url(world, "/director-board"), headers=world.headers(world.reviewer)).json()
    assert v["is_default"] and v["members"][0]["seat"] == "lead"
    assert v["members"][0]["persona"]["name"] == "Classic Teledrama"


def test_a_director_sets_the_board(world: World):
    p = world.repos.personas  # type: ignore[attr-defined]
    lead, adv = p.by_slug("grounded-realist")["id"], p.by_slug("lyrical-eye")["id"]
    body = {"seats": [{"persona_id": adv, "seat": "advisor"}, {"persona_id": lead, "seat": "lead"}]}
    r = world.client.put(url(world, "/director-board"), json=body, headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    v = r.json()
    assert not v["is_default"] and [(m["persona"]["id"], m["seat"]) for m in v["members"]] == [
        (lead, "lead"), (adv, "advisor")]
    assert world.repos.audit.entries[-1]["diff"]["seats"][0] == {"persona": "lyrical-eye", "seat": "advisor"}  # type: ignore[attr-defined]


@pytest.mark.parametrize("seats", [
    [{"seat": "advisor"}],  # no lead
    [{"seat": "lead"}, {"seat": "lead"}],  # two leads
])
def test_board_shape_is_checked(world: World, seats: list[dict]):
    ids = [r["id"] for r in world.repos.personas.rows.values()]  # type: ignore[attr-defined]
    body = {"seats": [{**s, "persona_id": ids[i]} for i, s in enumerate(seats)]}
    assert world.client.put(url(world, "/director-board"), json=body,
                            headers=world.headers(world.director)).status_code == 422


def test_board_needs_known_personas_and_the_direct_permission(world: World):
    body = {"seats": [{"persona_id": str(uuid4()), "seat": "lead"}]}
    assert world.client.put(url(world, "/director-board"), json=body,
                            headers=world.headers(world.director)).status_code == 422
    real = {"seats": [{"persona_id": next(iter(world.repos.personas.rows)), "seat": "lead"}]}  # type: ignore[attr-defined]
    for user in (world.writer, world.crew, world.reviewer):
        assert world.client.put(url(world, "/director-board"), json=real,
                                headers=world.headers(user)).status_code == 403


# ── the turn ───────────────────────────────────────────────────────────────────────────────


class Recorder:
    def __init__(self, frames_out: list[bytes] | None = None) -> None:
        self.payloads: list[TurnPayload] = []
        self.out = frames_out or [director_service.sse("delta", {"text": "Hello"}),
                                  director_service.sse("done", {"message_id": "m1"})]

    async def __call__(self, payload: TurnPayload) -> AsyncIterator[bytes]:
        self.payloads.append(payload)
        for f in self.out:
            yield f


@pytest.fixture
def recorder(world: World) -> Recorder:
    rec = Recorder()
    world.client.app.dependency_overrides[director_service.get_turn_streamer] = lambda: rec  # type: ignore[attr-defined]
    return rec


def test_chat_stores_the_message_and_streams_the_turn(world: World, recorder: Recorder):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    r = world.client.post(url(world, f"/scenes/{sid}/chat"), json={"message": "  make shot 2 eight seconds "},
                          headers=world.headers(world.director))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = frames(r.text)
    assert [e for e, _ in got] == ["accepted", "delta", "done"]
    accepted = got[0][1]
    assert accepted["message"]["text"] == "make shot 2 eight seconds" and accepted["message"]["kind"] == "user"
    p = recorder.payloads[0]
    assert p.can_edit and str(p.scene_id) == sid and str(p.thread_id) == accepted["thread_id"]
    assert str(p.user_message_id) == accepted["message"]["id"] and p.actor_name == "Dee Director"
    threads = world.client.get(url(world, f"/scenes/{sid}/threads"), headers=world.headers(world.reviewer)).json()
    assert len(threads) == 1 and threads[0]["title"] == "Director"
    msgs = world.client.get(url(world, f"/threads/{threads[0]['id']}/messages"),
                            headers=world.headers(world.reviewer)).json()
    assert [m["speaker"] for m in msgs] == ["Dee Director"]
    # the next message goes to the same main thread
    world.client.post(url(world, f"/scenes/{sid}/chat"), json={"message": "and shot 3?"},
                      headers=world.headers(world.director))
    assert recorder.payloads[1].thread_id == p.thread_id


def test_everyone_may_chat_but_only_directing_roles_may_edit(world: World, recorder: Recorder):
    s = seed_scene(world)
    for user, can_edit in ((world.reviewer, False), (world.writer, False), (world.crew, False),
                           (world.producer, True), (world.admin, True)):
        r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/chat"), json={"message": "hi"},
                              headers=world.headers(user))
        assert r.status_code == 200
        assert recorder.payloads[-1].can_edit is can_edit
    assert world.client.post(url(world, f"/scenes/{s['scene']['id']}/chat"), json={"message": "hi"},
                             headers=world.headers(world.outsider)).status_code == 404


def test_chat_threads_belong_to_their_scene(world: World, recorder: Recorder):
    s = seed_scene(world)
    sid = s["scene"]["id"]
    h = world.headers(world.writer)
    t = world.client.post(url(world, f"/scenes/{sid}/threads"), json={"title": "Wardrobe"}, headers=h).json()
    world.client.post(url(world, f"/scenes/{sid}/chat"), json={"message": "hi", "thread_id": t["id"]}, headers=h)
    assert str(recorder.payloads[-1].thread_id) == t["id"]
    other = next(x for x in world.repos.scenes.rows.values() if x["id"] != sid)  # type: ignore[attr-defined]
    r = world.client.post(url(world, f"/scenes/{other['id']}/chat"), json={"message": "hi", "thread_id": t["id"]},
                          headers=h)
    assert r.status_code == 404
    assert world.client.post(url(world, f"/scenes/{sid}/chat"), json={"message": ""}, headers=h).status_code == 422


def test_an_unreachable_director_is_one_error_frame(world: World, monkeypatch: pytest.MonkeyPatch):
    s = seed_scene(world)

    class Down(httpx.AsyncClient):
        def stream(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(director_service.httpx, "AsyncClient", Down)
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/chat"), json={"message": "hi"},
                          headers=world.headers(world.director))
    got = frames(r.text)
    assert [e for e, _ in got] == ["accepted", "error"]
    assert got[1][1]["message"] == director_service.UNAVAILABLE


# ── choosing a side in a disagreement ──────────────────────────────────────────────────────


class Applier:
    def __init__(self, result: ChoiceResult | None = None, down: bool = False) -> None:
        self.payloads: list[ChoicePayload] = []
        self.result = result or ChoiceResult(applied=[{"op": "set"}], summary="Applied: S01 sound mode → music_only.")
        self.down = down

    async def __call__(self, payload: ChoicePayload) -> ChoiceResult:
        self.payloads.append(payload)
        if self.down:
            raise director_service.DirectorUnavailable(director_service.UNAVAILABLE)
        return self.result


def use(world: World, applier: Applier) -> Applier:
    world.client.app.dependency_overrides[director_service.get_choice_applier] = lambda: applier  # type: ignore[attr-defined]
    return applier


SHOT_ID = str(uuid4())


def seed_disagreement(world: World) -> tuple[dict, dict]:
    """→ (scene, director message): text, then Sound (applied) vs Cinematography, then an advisor."""
    s = seed_scene(world)
    thread = world.repos.threads.add(production_id=str(world.production), scene_id=s["scene"]["id"],  # type: ignore[attr-defined]
                                     title="Director", created_by=str(world.director))
    cine_op = {"op": "set", "field": "sound_mode", "value": "music_only", "shot_id": SHOT_ID}
    message = world.repos.messages.add(  # type: ignore[attr-defined]
        production_id=str(world.production), thread_id=thread["id"], kind="director", speaker="Classic Teledrama",
        tone="lead", text="", ops=[], citations=[], author_user_id=None, persona_id=None, blocks=[
            {"kind": "text", "text": "Done."},
            {"kind": "disagreement", "title": "Two views on S01 sound mode", "positions": [
                {"who": "Sound", "text": "Silent.", "applied": True,
                 "ops": [{**cine_op, "value": "silent"}]},
                {"who": "Cinematography", "text": "Music.", "ops": [cine_op]}]},
            {"kind": "disagreement", "title": "Lyrical Eye sees it differently", "positions": [
                {"who": "Classic Teledrama", "text": "S01 silent", "applied": True},
                {"who": "Lyrical Eye", "text": "Hold the wide."}]}])
    return s["scene"], message


def choice_url(world: World, message: dict) -> str:
    return url(world, f"/messages/{message['id']}/choice")


def test_choosing_the_other_side_applies_its_stored_edit(world: World):
    scene, message = seed_disagreement(world)
    applier = use(world, Applier())
    r = world.client.post(choice_url(world, message), json={"block": 1, "who": "Cinematography"},
                          headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    block = body["message"]["blocks"][1]
    assert block["chosen"] == "Cinematography" and block["outcome"] == "Applied: S01 sound mode → music_only."
    assert [p["applied"] for p in block["positions"]] == [False, True]
    p = applier.payloads[0]
    assert str(p.scene_id) == scene["id"] and p.actor_user_id == world.director
    assert p.ops == [{"op": "set", "field": "sound_mode", "value": "music_only", "shot_id": SHOT_ID}]  # from the store
    stored = world.repos.messages.rows[message["id"]]  # type: ignore[attr-defined]
    assert stored["blocks"][1]["chosen"] == "Cinematography"
    assert world.repos.audit.entries[-1]["action"] == "director.choice"  # type: ignore[attr-defined]
    # decided once
    again = world.client.post(choice_url(world, message), json={"block": 1, "who": "Sound"},
                              headers=world.headers(world.director))
    assert again.status_code == 409


def test_keeping_the_version_the_plan_has_changes_nothing(world: World):
    _, message = seed_disagreement(world)
    applier = use(world, Applier())
    r = world.client.post(choice_url(world, message), json={"block": 2, "who": "Classic Teledrama"},
                          headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is False and r.json()["message"]["blocks"][2]["chosen"] == "Classic Teledrama"
    assert not applier.payloads


def test_a_choice_needs_a_real_side_a_director_and_a_reachable_function(world: World):
    _, message = seed_disagreement(world)
    use(world, Applier())
    h = world.headers(world.director)
    assert world.client.post(choice_url(world, message), json={"block": 2, "who": "Lyrical Eye"},
                             headers=h).status_code == 422  # a view, not an edit
    assert world.client.post(choice_url(world, message), json={"block": 0, "who": "Sound"},
                             headers=h).status_code == 404  # not a disagreement
    assert world.client.post(choice_url(world, message), json={"block": 9, "who": "Sound"},
                             headers=h).status_code == 404
    for user in (world.writer, world.reviewer):
        assert world.client.post(choice_url(world, message), json={"block": 1, "who": "Cinematography"},
                                 headers=world.headers(user)).status_code == 403
    assert world.client.post(choice_url(world, message), json={"block": 1, "who": "Cinematography"},
                             headers=world.headers(world.outsider)).status_code == 404
    use(world, Applier(ChoiceResult(summary="That shot has changed.")))
    r = world.client.post(choice_url(world, message), json={"block": 1, "who": "Cinematography"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "That shot has changed."
    use(world, Applier(down=True))
    r = world.client.post(choice_url(world, message), json={"block": 1, "who": "Cinematography"}, headers=h)
    assert r.status_code == 503
    assert world.repos.messages.rows[message["id"]]["blocks"][1].get("chosen") is None  # type: ignore[attr-defined]


def seed_options(world: World) -> dict:
    """A director message with options: one with an edit, one that is a message to the board."""
    s = seed_scene(world)
    thread = world.repos.threads.add(production_id=str(world.production), scene_id=s["scene"]["id"],  # type: ignore[attr-defined]
                                     title="Director", created_by=str(world.director))
    return world.repos.messages.add(  # type: ignore[attr-defined]
        production_id=str(world.production), thread_id=thread["id"], kind="director", speaker="Classic Teledrama",
        tone="lead", text="", ops=[], citations=[], author_user_id=None, persona_id=None, blocks=[
            {"kind": "text", "text": "Two ways."},
            {"kind": "options", "question": "How should S02 play?", "options": [
                {"label": "Push in", "change": "S02 framing → CU",
                 "ops": [{"op": "set", "field": "framing", "value": "CU", "shot_id": SHOT_ID}]},
                {"label": "Warmer", "prompt": "Make S02 warmer in tone."}]}])


def option_url(world: World, message: dict) -> str:
    return url(world, f"/messages/{message['id']}/option")


def test_an_option_with_an_edit_is_applied_and_recorded(world: World):
    message = seed_options(world)
    applier = use(world, Applier())
    for user in (world.writer, world.reviewer):  # they may ask the board, not change the plan
        assert world.client.post(option_url(world, message), json={"block": 1, "option": 0},
                                 headers=world.headers(user)).status_code == 403
    r = world.client.post(option_url(world, message), json={"block": 1, "option": 0},
                          headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True and body["prompt"] == ""
    assert body["message"]["blocks"][1]["chosen"] == 0
    assert applier.payloads[0].ops == [{"op": "set", "field": "framing", "value": "CU", "shot_id": SHOT_ID}]
    assert world.client.post(option_url(world, message), json={"block": 1, "option": 1},
                             headers=world.headers(world.director)).status_code == 409  # decided once


def test_an_option_without_an_edit_hands_back_its_prompt(world: World):
    message = seed_options(world)
    applier = use(world, Applier())
    r = world.client.post(option_url(world, message), json={"block": 1, "option": 1},
                          headers=world.headers(world.writer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is False and body["prompt"] == "Make S02 warmer in tone."
    assert body["message"]["blocks"][1]["outcome"] == "Asked the board." and not applier.payloads


def test_an_option_must_exist(world: World):
    message = seed_options(world)
    use(world, Applier())
    h = world.headers(world.director)
    assert world.client.post(option_url(world, message), json={"block": 1, "option": 5}, headers=h).status_code == 404
    assert world.client.post(option_url(world, message), json={"block": 0, "option": 0}, headers=h).status_code == 404
    use(world, Applier(ChoiceResult(summary="That shot has changed.")))
    r = world.client.post(option_url(world, message), json={"block": 1, "option": 0}, headers=h)
    assert r.status_code == 409 and world.repos.messages.rows[message["id"]]["blocks"][1].get("chosen") is None  # type: ignore[attr-defined]


# ── memory ─────────────────────────────────────────────────────────────────────────────────


def test_memory_is_listed_added_and_forgotten(world: World):
    s = seed_scene(world)
    h = world.headers(world.director)
    r = world.client.post(url(world, "/memory"), json={"text": "Kamala never cries on screen.",
                                                       "scene_id": s["scene"]["id"]}, headers=h)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["kind"] == "note"
    chunks = world.repos.memory.chunks  # type: ignore[attr-defined]
    assert chunks[f"memory:{item['id']}"]["embedding"] is None  # no key in tests: keyword search only
    listed = world.client.get(url(world, "/memory"), headers=world.headers(world.reviewer)).json()
    assert [m["id"] for m in listed] == [item["id"]]
    assert world.client.post(url(world, "/memory"), json={"text": "x"},
                             headers=world.headers(world.writer)).status_code == 403
    assert world.client.delete(url(world, f"/memory/{item['id']}"), headers=h).status_code == 204
    assert not chunks and world.client.get(url(world, "/memory"), headers=h).json() == []


def test_an_answered_build_question_becomes_memory(world: World):
    q = world.repos.questions.add(  # type: ignore[attr-defined]
        production_id=str(world.production), job_id=None, agent="structure", scope="Ep 01 Scene 2", key="loc:pier",
        title="Place", body="Is 'the pier' the breakwater (L02)?", options=[{"value": "L02", "label": "Yes, L02"}],
        allow_text=False, status="open", created_at="2026-10-23T00:00:00+00:00")
    r = world.client.post(url(world, f"/questions/{q['id']}/answer"), json={"value": "L02"},
                          headers=world.headers(world.writer))
    assert r.status_code == 200, r.text
    items = list(world.repos.memory.rows.values())  # type: ignore[attr-defined]
    assert items[0]["kind"] == "answer" and items[0]["source_ref"]["question_id"] == q["id"]
    assert items[0]["text"] == "Ep 01 Scene 2: Is 'the pier' the breakwater (L02)? Answer: Yes, L02"
