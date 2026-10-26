"""The API behind the screens wired last: activity, ask, and the canon library's create, draft and
usage."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

from api.routers.ask import canon_matches, parts
from api.services.ai import AI, get_ai
from tests.api.conftest import World
from tests.api.test_production import design, states
from tests.api.test_scenes import seed_scene


def base(world: World) -> str:
    return f"/v1/productions/{world.production}"


# ── activity ───────────────────────────────────────────────────────────────────────────────


def test_activity_is_the_productions_own_audit_newest_first(world: World):
    r = world.repos
    asyncio.run(r.audit.record(action="frame.accept", entity="frame", entity_id="f1", actor_user_id=world.crew,
                               production_id=world.production, diff={"shot_id": "s1"}))
    asyncio.run(r.audit.record(action="shots.design", entity="job", entity_id="j1", actor_user_id=world.director,
                               production_id=world.production, actor_agent="shot_producer"))
    asyncio.run(r.audit.record(action="frame.accept", entity="frame", entity_id="x", actor_user_id=world.crew,
                               production_id=world.other_production))
    rows = world.client.get(f"{base(world)}/activity", headers=world.headers(world.reviewer)).json()
    assert [(e["action"], e["actor_name"], e["actor_agent"]) for e in rows] == [
        ("shots.design", "Dee Director", "shot_producer"), ("frame.accept", "Cam Crew", None)]
    assert world.client.get(f"{base(world)}/activity", headers=world.headers(world.outsider)).status_code == 404


# ── ask ────────────────────────────────────────────────────────────────────────────────────


def test_answer_parts_keep_only_real_citations():
    got = parts("Kamala is 52 [1]. She sells fish [2][9].", 2)
    assert [p.model_dump(exclude_none=True) for p in got] == [
        {"text": "Kamala is 52 "}, {"cite": 1}, {"text": ". She sells fish "}, {"cite": 2}, {"text": "[9]."}]


def test_canon_matches_by_name_and_card():
    canon = [{"code": "C01", "name": "Kamala", "aliases": ["Amma"], "current": {"card": {"age": "52"}}},
             {"code": "C02", "name": "Nimal", "aliases": [], "current": {"card": {"appearance": "thin"}}}]
    assert [c["code"] for c in canon_matches(canon, "How old is Amma?")] == ["C01"]
    assert canon_matches(canon, "the harbour at night") == []


def _with_card(world: World, s: dict) -> None:
    kamala = s["kamala"]["id"]
    asyncio.run(world.repos.canon.add_version(UUID(kamala), {
        "entity_id": kamala, "version": 1, "card": {"age": "52", "appearance": "grey hair"},
        "voice_pin": "low voice"}))


def test_ask_without_a_model_shows_the_sources(world: World):
    s = seed_scene(world)
    _with_card(world, s)
    world.repos.search.chunk_rows = [{  # type: ignore[attr-defined]
        "id": str(uuid4()), "corpus": "production_docs", "heading": "Kamala", "context_header": "Bible",
        "content": "Kamala is fifty-two and runs the fish stall.", "score": 1.0, "document_id": None, "meta": {}}]
    r = world.client.post(f"{base(world)}/ask", json={"query": "How old is Kamala?"},
                          headers=world.headers(world.reviewer))
    assert r.status_code == 200, r.text
    v = r.json()
    assert not v["answered_by_model"]
    kinds = [s_["kind"] for s_ in v["sources"]]
    assert kinds[0] == "canon" and kinds[-1] == "document", "her card first (a name match), the bible after"
    assert v["sources"][0]["title"] == "C01 · Kamala" and "age: 52" in v["sources"][0]["quote"]
    assert [p.get("cite") for p in v["answer"][1:]] == list(range(1, len(kinds) + 1))
    canon_only = world.client.post(f"{base(world)}/ask", json={"query": "Kamala", "scope": "canon"},
                                   headers=world.headers(world.reviewer)).json()
    assert {s_["kind"] for s_ in canon_only["sources"]} == {"canon"}


def test_ask_with_a_model_cites_its_sources(world: World):
    s = seed_scene(world)
    _with_card(world, s)

    async def create(**kw):  # type: ignore[no-untyped-def]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"answer": "Kamala is 52 [1]."}'))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                             embeddings=SimpleNamespace(create=None))
    ai = AI(SimpleNamespace(enabled=True, model_medium="m", effort_medium="", embedding_model="e",  # type: ignore[arg-type]
                            embedding_dimensions=4), client=client)

    async def no_embed(*a, **k):  # type: ignore[no-untyped-def]
        return None

    ai.embed_query = no_embed  # type: ignore[method-assign]
    world.client.app.dependency_overrides[get_ai] = lambda: ai  # type: ignore[attr-defined]
    v = world.client.post(f"{base(world)}/ask", json={"query": "How old is Kamala?", "scope": "canon"},
                          headers=world.headers(world.reviewer)).json()
    assert v["answered_by_model"] and v["answer"] == [{"text": "Kamala is 52 ", "cite": None},
                                                      {"text": None, "cite": 1}, {"text": ".", "cite": None}]


# ── canon ──────────────────────────────────────────────────────────────────────────────────


def test_a_person_creates_a_canon_entity(world: World):
    seed_scene(world)
    body = {"kind": "character", "name": "Sunil", "aliases": ["Aiya"],
            "card": {"gender": "male", "age": "34", "wardrobe": "a faded red sarong", "voice": "rough"},
            "lock": True}
    assert world.client.post(f"{base(world)}/canon", json=body, headers=world.headers(world.crew)).status_code == 403
    r = world.client.post(f"{base(world)}/canon", json=body, headers=world.headers(world.director))
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["code"] == "C03" and e["locked"] and e["current_version"] == 1
    assert e["current"]["wardrobe_anchor"] == "a faded red sarong" and "rough" in e["current"]["voice_pin"]
    assert world.client.post(f"{base(world)}/canon", json={**body, "name": "SUNIL"},
                             headers=world.headers(world.director)).status_code == 409
    detail = world.client.get(f"{base(world)}/canon/{e['id']}", headers=world.headers(world.reviewer)).json()
    assert detail["versions"][0]["author"] == "Dee Director" and detail["locked_by_name"] == "Dee Director"


def test_a_draft_quotes_the_documents(world: World):
    seed_scene(world)
    world.repos.search.chunk_rows = [{  # type: ignore[attr-defined]
        "id": str(uuid4()), "corpus": "production_docs", "heading": "Characters", "context_header": "Bible",
        "content": "The harbour is busy. Sunil is the elder brother. He mends nets at dawn.", "score": 1.0,
        "document_id": None, "meta": {"page_start": 4}}]
    d = world.client.post(f"{base(world)}/canon/draft", json={"kind": "character", "name": "Sunil"},
                          headers=world.headers(world.director)).json()
    assert d["look"] == "Sunil is the elder brother." and d["sources"] == ["Characters · p. 4"]


def test_usage_counts_shots_and_what_is_out_of_date(world: World):
    s = seed_scene(world)
    _with_card(world, s)
    design(world, s)
    kamala, house = s["kamala"]["id"], s["house"]["id"]
    usage = world.client.get(f"{base(world)}/canon/usage", headers=world.headers(world.reviewer)).json()
    assert usage[house]["shots"] == 4, "every shot of a scene is at its location"
    assert usage[kamala]["shots"] >= 1 and usage[kamala]["out_of_date"] == 0
    asyncio.run(world.repos.canon.add_version(UUID(kamala), {"entity_id": kamala, "version": 2, "card": {}}))
    one = world.client.get(f"{base(world)}/canon/{kamala}/usage", headers=world.headers(world.reviewer)).json()
    assert one["out_of_date"] == one["shots"] > 0
    assert one["used_in"][0]["label"] == "Ep 01 · Scene 1"
    assert states(world, s)  # the fixtures agree with the API's own view
