"""A `match_chunks` row as the cited hit the API returns (and the passage a reranker reads)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.documents import Citation, SearchHit

Row = dict[str, Any]


def passages(rows: Sequence[Row]) -> list[str]:
    """What a reranker reads for each row: the context header, then the text."""
    return [f"{r['context_header']}\n{r['content']}" for r in rows]


def to_hit(row: Row, documents: dict[str, Row], reranked: bool) -> SearchHit:
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
