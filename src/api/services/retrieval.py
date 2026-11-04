"""Production search (PLAN.md §7): scope → hybrid match → optional rerank → cited hits.

* Scope is decided HERE from data the API trusts, never from model text: the production the
  caller may view, the corpora asked for, and only documents that are READY (a document being
  re-ingested has its chunks replaced mid-flight) with the requested roles.
* `match_chunks` fuses vector and keyword ranks. With no embedding it runs keyword-only and the
  response says `mode: "text"`.
* Reranking reads the top candidates with a mid-tier model and drops the unrelated ones. When it
  is unavailable the fusion order stands.
"""
from __future__ import annotations

from uuid import UUID

from api.repositories import Repos
from api.services.ai import AI, UsageContext
from contracts.documents import Corpus, SearchRequest, SearchResponse
from hiru_ai.rag.hits import passages, to_hit
from hiru_ai.rag.ranking import apply_order, candidates_for, mode_of
from hiru_ai.rag.scope import Row, ready_documents


async def search(repos: Repos, ai: AI, *, production_id: UUID, actor_user_id: UUID,
                 req: SearchRequest) -> SearchResponse:
    usage = UsageContext(repos, actor_user_id, production_id)
    corpora = [c.value for c in req.corpora]

    documents: dict[str, Row] = {}
    document_ids: list[UUID] | None = None
    if Corpus.PRODUCTION_DOCS in req.corpora:
        documents = ready_documents(await repos.documents.list(production_id), req.roles)
        document_ids = [UUID(d) for d in documents]

    embedding = await ai.embed_query(req.query, usage)
    rerank = req.rerank and ai.enabled
    rows = await repos.search.match_chunks(
        query_text=req.query, query_embedding=embedding, production_id=production_id,
        corpora=corpora, document_ids=document_ids,
        match_count=candidates_for(req.k, rerank))

    reranked = False
    if rerank and len(rows) > 1:
        order = await ai.rerank(req.query, passages(rows), usage)
        if order is not None:
            rows, reranked = apply_order(rows, order), True

    hits = [to_hit(r, documents, reranked) for r in rows[: req.k]]
    return SearchResponse(hits=hits, mode=mode_of(embedding), reranked=reranked)
