"""Hybrid retrieval: embed the query (when a model is there), fuse vector and keyword ranks in the database, then
optionally rerank. Every step degrades on its own (CLAUDE.md "Absent-safe"): no embedding is keyword-only
(`mode: "text"`), no reranker or a failed one leaves the fusion order.

The same rules the API's `/search` follows; `rag.ranking` holds the ones both share.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document

from hiru_ai.rag.hits import passages
from hiru_ai.rag.ranking import Mode, apply_order, candidates_for, mode_of
from hiru_ai.rag.rerankers import Reranker
from hiru_ai.rag.retrievers.match_chunks import MatchChunksRetriever, to_document

Row = dict[str, Any]


@dataclass(frozen=True)
class Retrieval:
    rows: list[Row]
    mode: Mode
    reranked: bool


class HybridRetriever(MatchChunksRetriever):
    reranker: Reranker | None = None

    def retrieve(self, query: str) -> Retrieval:
        embedding = self.embed(query)
        rerank = self.reranker is not None
        rows = self.fetch(query, embedding, candidates_for(self.k, rerank))
        reranked = False
        if self.reranker is not None and len(rows) > 1:
            order: Sequence[int] | None = self.reranker(query, passages(rows))
            if order is not None:
                rows, reranked = apply_order(rows, order), True
        return Retrieval(rows[: self.k], mode_of(embedding), reranked)

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        found = self.retrieve(query)
        return [to_document(r, mode=found.mode, reranked=found.reranked) for r in found.rows]
