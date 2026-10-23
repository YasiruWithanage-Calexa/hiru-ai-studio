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

from api.repositories import Repos, Row
from api.services.ai import AI, UsageContext
from contracts.documents import (
    Citation,
    Corpus,
    DocumentRole,
    DocumentStatus,
    SearchHit,
    SearchRequest,
    SearchResponse,
)

CANDIDATES = 30  # what the reranker reads; without a reranker we fetch exactly k


async def search(repos: Repos, ai: AI, *, production_id: UUID, actor_user_id: UUID,
                 req: SearchRequest) -> SearchResponse:
    usage = UsageContext(repos, actor_user_id, production_id)
    corpora = [c.value for c in req.corpora]

    documents: dict[str, Row] = {}
    document_ids: list[UUID] | None = None
    if Corpus.PRODUCTION_DOCS in req.corpora:
        wanted = set(req.roles) if req.roles else None
        for doc in await repos.documents.list(production_id):
            role = doc.get("confirmed_role") or doc.get("detected_role")
            if doc["status"] != DocumentStatus.READY:
                continue
            if wanted and (role is None or DocumentRole(role) not in wanted):
                continue
            documents[str(doc["id"])] = doc
        document_ids = [UUID(d) for d in documents]

    embedding = await ai.embed_query(req.query, usage)
    rerank = req.rerank and ai.enabled
    rows = await repos.search.match_chunks(
        query_text=req.query, query_embedding=embedding, production_id=production_id,
        corpora=corpora, document_ids=document_ids,
        match_count=CANDIDATES if rerank else req.k)

    reranked = False
    if rerank and len(rows) > 1:
        order = await ai.rerank(req.query, [f"{r['context_header']}\n{r['content']}" for r in rows], usage)
        if order is not None:
            rows, reranked = [rows[i] for i in order], True

    hits = [_hit(r, documents, reranked) for r in rows[: req.k]]
    return SearchResponse(hits=hits, mode="hybrid" if embedding is not None else "text", reranked=reranked)


def _hit(row: Row, documents: dict[str, Row], reranked: bool) -> SearchHit:
    meta = row.get("meta") or {}
    doc = documents.get(str(row.get("document_id"))) if row.get("document_id") else None
    matched = [name for name, key in (("vector", "vector_rank"), ("text", "text_rank")) if row.get(key)]
    if reranked:
        matched.append("rerank")
    return SearchHit(
        chunk_id=row["id"], corpus=row["corpus"], heading=row["heading"],
        context_header=row["context_header"], content=row["content"], score=float(row["score"]),
        matched_by=matched,
        citation=Citation(
            document_id=row.get("document_id"), filename=doc["filename"] if doc else "",
            source=row.get("source") or "", heading=row["heading"],
            page_start=meta.get("page_start"), page_end=meta.get("page_end")),
        meta=meta,
    )
