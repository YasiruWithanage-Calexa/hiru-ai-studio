"""Sable's routes (plan/2026-11-08 Phase 6), the function stood in for: who may ask (every role that can view), whose
threads (per person, D3), the stored message first, the payload the function is trusted with, the cards a person
accepts, and that no other chat's list or message route ever shows a Sable thread."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from api.services import director as director_service
from api.services import sable as sable_service
from tests.api.conftest import World, _settings, world  # noqa: F401  (the API's own fixtures)
from tests.api.test_director import frames
from tests.api.test_scenes import seed_scene, url

Row = dict[str, Any]


@pytest.fixture(autouse=True)
def _sable_on(monkeypatch: pytest.MonkeyPatch, _settings: None) -> None:  # noqa: F811
    from api.config import get_settings

    monkeypatch.setenv("SABLE__ENABLED", "true")
    get_settings.cache_clear()


class Function:
    """Stands in for the sable_chat function: records what it is sent."""

    def __init__(self) -> None:
        self.turns: list[Row] = []

    async def stream(self, payload: Row) -> AsyncIterator[bytes]:
        self.turns.append(payload)
        yield director_service.sse("status", {"text": "Reading E1S1"})
        yield director_service.sse("done", {"message_id": "m1", "used": []})


@pytest.fixture
def fn(world: World) -> Function:  # noqa: F811
    f = Function()
    world.client.app.dependency_overrides[sable_service.get_streamer] = lambda: f.stream  # type: ignore[attr-defined]
    return f


class Actor:
    """Stands in for the sable_chat function's card action: records it and answers `ok` (or the sentence given)."""

    def __init__(self, refused: str = "") -> None:
        self.actions: list[Row] = []
        self.refused = refused

    async def act(self, payload: Row) -> Row:
        self.actions.append(payload)
        if self.refused:
            return {"ok": False, "text": self.refused, "revision": 0}
        return {"ok": True, "text": f"Applied: {payload.get('summary')} · revision 4.", "revision": 4}


def actor(world: World, refused: str = "") -> Actor:  # noqa: F811
    a = Actor(refused)
    world.client.app.dependency_overrides[sable_service.get_actor] = lambda: a.act  # type: ignore[attr-defined]
    return a


def row_card(sid: Any, **over: Any) -> Row:
    return {"kind": "sable_change", "scene_id": str(sid), "scene": "E1S1", "summary": "Open close.", "engine": "rows",
            "made_on": "abc123", "ops": [{"op": {"op": "set", "shot": 1, "field": "size", "value": "CU"},
                                          "by": "author"}], "status": "open", **over}


def ask(world: World, who: Any, message: str = "How far along is episode 1?", **body: Any) -> Any:  # noqa: F811
    return world.client.post(url(world, "/sable/turn"), json={"message": message, **body}, headers=world.headers(who))


def test_every_role_that_can_view_may_ask_and_only_direct_may_accept(world: World, fn: Function):  # noqa: F811
    for who in (world.reviewer, world.crew, world.writer, world.director):
        assert ask(world, who).status_code == 200
    assert [t["can_stage"] for t in fn.turns] == [False, False, False, True]
    assert [t["role"] for t in fn.turns] == ["reviewer", "production", "writer", "director"]
    assert ask(world, world.outsider).status_code == 404  # a production the caller cannot see


def test_a_turn_stores_the_message_first_then_streams(world: World, fn: Function):  # noqa: F811
    r = ask(world, world.director, "Which scenes is Kamala in?")
    got = frames(r.text)
    assert [e for e, _ in got] == ["accepted", "status", "done"]
    accepted = got[0][1]
    assert accepted["message"]["text"] == "Which scenes is Kamala in?" and "meta" not in accepted["message"]
    thread = world.client.get(url(world, f"/sable/threads/{accepted['thread_id']}"),
                              headers=world.headers(world.director)).json()
    assert thread["thread"]["title"] == "Which scenes is Kamala in?" and len(thread["messages"]) == 1
    assert fn.turns[0]["user_message_id"] == accepted["message"]["id"]


def test_the_scene_in_view_must_be_in_this_production(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    assert ask(world, world.director, scene_id=str(sid)).status_code == 200
    assert fn.turns[-1]["scene_id"] == str(sid)
    assert ask(world, world.director, scene_id=str(uuid4())).status_code == 404


def test_threads_are_one_persons_own(world: World, fn: Function):  # noqa: F811
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mine = world.client.get(url(world, "/sable/threads"), headers=world.headers(world.director)).json()
    theirs = world.client.get(url(world, "/sable/threads"), headers=world.headers(world.producer)).json()
    assert [t["id"] for t in mine] == [tid] and theirs == []
    assert world.client.get(url(world, f"/sable/threads/{tid}"),
                            headers=world.headers(world.producer)).status_code == 404
    assert ask(world, world.producer, thread_id=tid).status_code == 404
    assert world.client.delete(url(world, f"/sable/threads/{tid}"),
                               headers=world.headers(world.producer)).status_code == 404
    assert world.client.delete(url(world, f"/sable/threads/{tid}"),
                               headers=world.headers(world.director)).status_code == 204
    assert world.client.get(url(world, "/sable/threads"), headers=world.headers(world.director)).json() == []


def test_no_other_chat_shows_a_sable_thread(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    tid = frames(ask(world, world.director, scene_id=str(sid)).text)[0][1]["thread_id"]
    classic = world.client.get(url(world, f"/scenes/{sid}/threads"), headers=world.headers(world.director)).json()
    assert tid not in [t["id"] for t in classic]
    assert world.client.get(url(world, f"/threads/{tid}/messages"),
                            headers=world.headers(world.director)).status_code == 404
    assert world.client.delete(url(world, f"/threads/{tid}/messages"),
                               headers=world.headers(world.director)).status_code == 404
    assert world.repos.messages.rows  # type: ignore[attr-defined]  # the message is still there


def test_switched_off_nothing_runs(world: World, fn: Function, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from api.config import get_settings

    monkeypatch.setenv("SABLE__ENABLED", "false")
    get_settings.cache_clear()
    assert world.client.get(url(world, "/sable"), headers=world.headers(world.reviewer)).json() == {
        "enabled": False, "can_accept": False}
    assert ask(world, world.director).status_code == 409 and fn.turns == []


def _reply(world: World, tid: str, blocks: list[Row]) -> str:  # noqa: F811
    mid = str(uuid4())
    world.repos.messages.add(id=mid, production_id=str(world.production), thread_id=tid,  # type: ignore[attr-defined]
                             kind="director", speaker="Sable", text="", blocks=blocks, ops=[], citations=[],
                             meta={"tier_start": "sable", "tier_end": "sable_deep", "tools": ["sable_overview"]})
    return mid


def test_meta_never_reaches_the_browser_and_a_handoff_says_where_it_opens(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    _reply(world, tid, [{"kind": "text", "text": "Open it."},
                        {"kind": "handoff", "scene_id": str(sid), "scene": "E1S1", "request": "make S01 a CU"}])
    body = world.client.get(url(world, f"/sable/threads/{tid}"), headers=world.headers(world.director)).text
    assert "sable_deep" not in body and "tier" not in body and "meta" not in body
    messages = world.client.get(url(world, f"/sable/threads/{tid}"), headers=world.headers(world.director)).json()
    handoff = next(b for m in messages["messages"] for b in m["blocks"] if b["kind"] == "handoff")
    assert handoff["target"] == "zora"  # Zora on: every scene is hers, whoever planned it


def test_a_staged_change_is_carried_out_by_code_once(world: World, fn: Function):  # noqa: F811
    """plan/2026-11-13 phase 8: the row kernel's operations go to the function's `apply` with the rows' fingerprint."""
    sid = seed_scene(world)["scene"]["id"]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    card = row_card(sid)
    mid = _reply(world, tid, [{"kind": "text", "text": "A card."}, card])
    z = actor(world)
    path = url(world, f"/sable/messages/{mid}/cards/1/accept")
    assert world.client.post(path, headers=world.headers(world.writer)).status_code == 403  # no DIRECT
    r = world.client.post(path, headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["text"] == "Applied: Open close. · revision 4."
    (sent,) = z.actions
    assert sent["kind"] == "apply" and sent["scene_id"] == str(sid) and sent["ops"] == card["ops"]
    assert sent["made_on"] == "abc123" and sent["actor_user_id"] == str(world.director)
    assert r.json()["message"]["blocks"][1]["status"] == "accepted"
    assert world.client.post(path, headers=world.headers(world.director)).status_code == 409  # once
    assert world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"),
                             headers=world.headers(world.director)).status_code == 404  # a text block is no card


def test_a_change_the_scene_refuses_now_is_marked_failed_with_the_reason(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [row_card(sid)])
    actor(world, refused="The shots changed since this card was made, so nothing was applied. Ask me again.")
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.json()["ok"] is False and r.json()["message"]["blocks"][0]["status"] == "failed"
    assert r.json()["text"].startswith("The shots changed since this card was made")


def test_a_card_from_before_the_row_kernel_is_failed_and_nothing_is_sent(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    old = {"kind": "sable_change", "scene_id": str(sid), "scene": "E1S1", "summary": "x",
           "ops": [{"op": "set", "shot_id": str(uuid4()), "field": "framing", "value": "CU"}], "status": "open"}
    mid = _reply(world, tid, [old])
    z = actor(world)
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.json()["ok"] is False and "Ask Sable again" in r.json()["text"] and z.actions == []


def test_a_rule_accepted_is_remembered_and_a_dismissed_card_is_set_aside(world: World, fn: Function):  # noqa: F811
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [{"kind": "sable_memory", "rule": "Kamala never shouts.", "scope": "production",
                               "status": "open"},
                              {"kind": "sable_memory", "rule": "Something else.", "scope": "production",
                               "status": "open"}])
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["text"] == "Remembered."
    items = [m for m in world.repos.memory.rows.values()]  # type: ignore[attr-defined]
    assert [(m["text"], m["kind"]) for m in items] == [("Kamala never shouts.", "decision")]
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/1/dismiss"), headers=world.headers(world.director))
    assert r.json()["message"]["blocks"][1]["status"] == "dismissed" and len(world.repos.memory.rows) == 1  # type: ignore[attr-defined]


def test_a_new_thread_is_titled_from_its_first_line():
    assert sable_service.title_of("Which scenes?\nmore") == "Which scenes?"
    long = "word " * 30
    assert sable_service.title_of(long).endswith("…") and len(sable_service.title_of(long)) <= 61
    assert sable_service.title_of("   ") == "New chat"


# ── plan/2026-11-09b: a state card and a shot note, carried out by code ──────────────────────────────────────────


def _mapped_scene(world: World) -> tuple[str, list[Row]]:  # noqa: F811
    """A seeded scene with a staging map: Kamala at the door from block 0, Nimal in the yard."""
    sid = str(seed_scene(world)["scene"]["id"])
    from contracts import sceneplan
    from contracts import stagemap as sm

    scene = world.repos.scenes.rows[sid]  # type: ignore[attr-defined]
    lines = [r for r in world.repos.lines.rows.values() if str(r["scene_id"]) == sid]  # type: ignore[attr-defined]
    items = sceneplan.scene_items(scene, lines)
    raw = {"zones": ["door", "yard"], "marks": [{"block": 0, "who": "Kamala", "zone": "door"},
                                                  {"block": 0, "who": "Nimal", "zone": "yard"}]}
    scene["staging"] = sm.validate(raw, items, ["Kamala", "Nimal"], version=1, by="model").model_dump(mode="json")
    return sid, [s for s in world.repos.shots.rows.values() if str(s["scene_id"]) == sid]  # type: ignore[attr-defined]


def _state_card(sid: str, **over: Any) -> Row:
    return {"kind": "sable_state", "scene_id": sid, "scene": "E1S1", "summary": "Nimal is dead.", "status": "open",
            "script_version": 1, "changes": ["Nimal: lying, dead, from block 0"],
            "marks": [{"who": "Nimal", "from_block": 0, "condition": "dead"}], **over}


def test_a_state_card_is_merged_into_the_map_as_a_persons_and_the_shots_go_out_of_date(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [_state_card(sid)])
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["ok"] is True, r.json()["text"]
    assert "Applied: Nimal" in r.json()["text"]
    staging = world.repos.scenes.rows[sid]["staging"]  # type: ignore[attr-defined]
    assert staging["by"] == "person"
    nimal = next(m for m in staging["marks"] if m["who"] == "Nimal")
    assert nimal["condition"] == "dead" and nimal["posture"] == "lying" and nimal["zone"] == "yard"
    assert any(int(s["version"]) > 1 for s in world.repos.shots.rows.values() if str(s["scene_id"]) == sid)  # type: ignore[attr-defined]
    assert any(a["action"] == "sable.accept_state" for a in world.repos.audit.entries)  # type: ignore[attr-defined]
    assert world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"),
                             headers=world.headers(world.director)).status_code == 409


def test_a_state_card_for_a_script_that_changed_is_failed_not_applied(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [_state_card(sid, script_version=7)])
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.json()["ok"] is False and "script changed" in r.json()["text"]
    assert world.repos.scenes.rows[sid]["staging"]["by"] == "model"  # type: ignore[attr-defined]


def test_a_state_card_for_an_approved_scene_is_refused(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    world.repos.scenes.rows[sid]["status"] = "approved"  # type: ignore[attr-defined]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [_state_card(sid)])
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.status_code == 409


def test_a_change_card_for_an_approved_scene_is_refused(world: World, fn: Function):  # noqa: F811
    sid = seed_scene(world)["scene"]["id"]
    world.repos.scenes.rows[str(sid)]["status"] = "approved"  # type: ignore[attr-defined]
    tid = frames(ask(world, world.director).text)[0][1]["thread_id"]
    mid = _reply(world, tid, [row_card(sid)])
    z = actor(world)
    r = world.client.post(url(world, f"/sable/messages/{mid}/cards/0/accept"), headers=world.headers(world.director))
    assert r.status_code == 409 and z.actions == []


# ── plan/2026-11-09b phase 4: what @ pointed at ───────────────────────────────────────────────────────────────────────


def test_refs_are_read_again_from_the_production_and_reach_the_function_as_mentions(world: World, fn: Function):  # noqa: F811
    sid, shots = _mapped_scene(world)
    shot = sorted(shots, key=lambda s: int(s["number"]))[0]
    nimal = next(c for c in world.repos.canon.rows.values() if c["name"] == "Nimal")  # type: ignore[attr-defined]
    refs = [{"kind": "shot", "id": str(shot["id"]), "label": "whatever the browser said"},
            {"kind": "person", "id": str(nimal["id"]), "label": "Nimal"},
            {"kind": "block", "id": "0", "label": "b0"}]
    assert ask(world, world.director, "make @S01 a van", scene_id=sid, refs=refs).status_code == 200
    got = fn.turns[-1]["mentions"]
    assert [m["kind"] for m in got] == ["shot", "person", "block"] and got[0]["label"] == "S01"
    assert not any(m["outside"] for m in got) and "Nimal = person" in got[1]["text"]


def test_a_ref_that_is_not_in_this_production_is_404_and_nothing_runs(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    bad = [{"kind": "shot", "id": str(uuid4()), "label": "S09"}]
    assert ask(world, world.director, "x", scene_id=sid, refs=bad).status_code == 404 and fn.turns == []
    assert ask(world, world.director, "x", scene_id=sid, refs=[{"kind": "block", "id": "999"}]).status_code == 404
    too_many = [{"kind": "block", "id": "0"}] * 13
    assert ask(world, world.director, "x", scene_id=sid, refs=too_many).status_code == 422


def test_a_shot_of_another_scene_is_kept_for_reading_and_marked_outside(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    episode = world.repos.scenes.rows[sid]["episode_id"]  # type: ignore[attr-defined]
    other = world.repos.scenes.add(production_id=str(world.production), episode_id=episode,  # type: ignore[attr-defined]
                                   number=2, heading="INT. HOUSE - DAY", title="", note="", time_of_day="DAY",
                                   envelope_s=30, status="split", script=[], script_version=1)
    shot = world.repos.shots.add(production_id=str(world.production), scene_id=other["id"], number=1, title="x")  # type: ignore[attr-defined]
    ref = [{"kind": "shot", "id": str(shot["id"]), "label": "S01"}]
    assert ask(world, world.director, "read @S01", scene_id=sid, refs=ref).status_code == 200
    (m,) = fn.turns[-1]["mentions"]
    assert m["outside"] is True and m["scene"] == "E1S2" and "read only" in m["text"]


def test_the_picker_lists_the_approved_scene_first_then_the_canon_then_other_scenes(world: World, fn: Function):  # noqa: F811
    sid, _ = _mapped_scene(world)
    r = world.client.get(url(world, f"/sable/mentions?scene_id={sid}"), headers=world.headers(world.reviewer))
    kinds = [row["kind"] for row in r.json()]
    assert r.status_code == 200 and kinds[0] == "shot" and kinds.index("block") < kinds.index("person")
    only = world.client.get(url(world, f"/sable/mentions?scene_id={sid}&q=nim"), headers=world.headers(world.reviewer))
    assert ("person", "Nimal") in [(row["kind"], row["label"]) for row in only.json()]  # and his lines, by detail
    assert all("nim" in (row["label"] + row["detail"]).lower() for row in only.json())
    assert world.client.get(url(world, f"/sable/mentions?scene_id={uuid4()}"),
                            headers=world.headers(world.reviewer)).status_code == 404
