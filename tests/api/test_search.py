from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from api.config import OpenAISettings
from api.services.ai import AI
from tests.api.conftest import World


class FakeAsyncOpenAI:
    def __init__(self, ranking: list[dict[str, int]] | None = None, fail: bool = False) -> None:
        self.ranking = ranking
        self.fail = fail
        self.embeddings = SimpleNamespace(create=self._embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))

    async def _embed(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("down")
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 4)],
                               usage=SimpleNamespace(prompt_tokens=5))

    async def _chat(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("down")
        usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        content = json.dumps({"ranking": self.ranking or []})
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _doc(world: World, role: str, status: str = "ready", production=None) -> str:
    did = str(uuid4())
    world.repos.documents.rows[did] = {  # type: ignore[attr-defined]
        "id": did, "production_id": str(production or world.production), "filename": f"{role}.md",
        "status": status, "detected_role": role, "confirmed_role": None, "storage_path": "p"}
    return did


def _chunk(doc_id: str | None, n: int, corpus: str = "production_docs") -> dict[str, Any]:
    return {"id": str(uuid4()), "corpus": corpus, "production_id": None, "document_id": doc_id,
            "source": "" if doc_id else "craft/directing.md", "ord": n, "heading": f"H{n}",
            "context_header": f"header {n}", "content": f"content {n}", "meta": {"page_start": n},
            "score": 1.0 / (n + 1), "vector_rank": None, "text_rank": n + 1}


def _search(world: World, user, **body):
    return world.client.post(f"/v1/productions/{world.production}/search",
                             json={"query": "who wants to sell the boat", **body}, headers=world.headers(user))


def test_keyword_mode_without_ai(world: World):
    script = _doc(world, "script")
    _doc(world, "notes", status="processing")  # not ready → never searched
    world.repos.search.chunk_rows = [_chunk(script, i) for i in range(3)]  # type: ignore[attr-defined]
    r = _search(world, world.reviewer)
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "text" and body["reranked"] is False
    call = world.repos.search.calls[0]  # type: ignore[attr-defined]
    assert call["query_embedding"] is None
    assert [str(d) for d in call["document_ids"]] == [script]
    assert call["match_count"] == 8  # no reranker → fetch exactly k
    hit = body["hits"][0]
    assert hit["citation"]["filename"] == "script.md" and hit["citation"]["page_start"] == 0
    assert hit["matched_by"] == ["text"]


def test_role_filter_narrows_documents(world: World):
    _doc(world, "script")
    bible = _doc(world, "bible")
    _search(world, world.writer, roles=["bible"])
    assert [str(d) for d in world.repos.search.calls[0]["document_ids"]] == [bible]  # type: ignore[attr-defined]


def test_other_productions_documents_are_never_in_scope(world: World):
    _doc(world, "script", production=world.other_production)
    _search(world, world.producer)
    call = world.repos.search.calls[0]  # type: ignore[attr-defined]
    assert call["document_ids"] == [] and call["production_id"] == world.production


def test_non_member_cannot_search(world: World):
    r = world.client.post(f"/v1/productions/{world.other_production}/search", json={"query": "x"},
                          headers=world.headers(world.producer))
    assert r.status_code == 404


@pytest.fixture
def with_ai(world: World):
    def install(client: FakeAsyncOpenAI) -> None:
        world.client.app.state.ai = AI(OpenAISettings(api_key="sk-test"), client=client)  # type: ignore[attr-defined]
    return install


def test_hybrid_mode_and_rerank_reorders_and_drops_unrelated(world: World, with_ai):
    script = _doc(world, "script")
    world.repos.search.chunk_rows = [_chunk(script, i) for i in range(4)]  # type: ignore[attr-defined]
    with_ai(FakeAsyncOpenAI(ranking=[{"n": 0, "relevance": 1}, {"n": 1, "relevance": 0},
                                     {"n": 2, "relevance": 3}, {"n": 3, "relevance": 2}]))
    body = _search(world, world.reviewer, k=8).json()
    assert body["mode"] == "hybrid" and body["reranked"] is True
    assert [h["heading"] for h in body["hits"]] == ["H2", "H3", "H0"]  # H1 judged unrelated
    assert world.repos.search.calls[0]["match_count"] == 30  # type: ignore[attr-defined]
    phases = [u["phase"] for u in world.repos.usage.rows]  # type: ignore[attr-defined]
    assert phases == ["search.embed", "search.rerank"]


def test_ai_failure_degrades_to_keyword_order(world: World, with_ai):
    script = _doc(world, "script")
    world.repos.search.chunk_rows = [_chunk(script, i) for i in range(3)]  # type: ignore[attr-defined]
    with_ai(FakeAsyncOpenAI(fail=True))
    body = _search(world, world.reviewer).json()
    assert body["mode"] == "text" and body["reranked"] is False and len(body["hits"]) == 3


def test_craft_hits_cite_their_source(world: World):
    world.repos.search.chunk_rows = [_chunk(None, 0, corpus="craft")]  # type: ignore[attr-defined]
    body = _search(world, world.reviewer, corpora=["craft"]).json()
    assert body["hits"][0]["citation"]["source"] == "craft/directing.md"
    assert world.repos.search.calls[0]["document_ids"] is None  # type: ignore[attr-defined]


def test_technique_search(world: World):
    world.repos.search.technique_rows = [{  # type: ignore[attr-defined]
        "category": "Camera Angle", "name": "High Angle", "abbreviation": "HA",
        "definition": "Camera points down", "use_case": "Make the subject look vulnerable",
        "example_film": "x", "score": 0.03}]
    r = world.client.post("/v1/craft/techniques/search", json={"query": "she feels powerless"},
                          headers=world.headers(world.writer))
    assert r.status_code == 200 and r.json()[0]["name"] == "High Angle"
