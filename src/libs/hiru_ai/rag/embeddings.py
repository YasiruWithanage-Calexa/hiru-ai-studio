"""Embeddings for retrieval, through the one model door (`core.llm.get_embeddings`).

A query embedding is optional by contract (CLAUDE.md "Absent-safe"): no key, or a failed call, gives `None` and the
search runs on keywords. Embedding texts to index is not optional once a key is set: a failure there is raised,
because a half-embedded index would look healthy and search worse; a re-run reuses what was already embedded.
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings

from hiru_ai.core import llm
from hiru_ai.core.telemetry import logger
from hiru_ai.core.usage import UsageSink

_log = logger("rag.embeddings")
BATCH = 64


def embed_query(text: str, phase: str, sink: UsageSink | None = None, *,
                embeddings: Embeddings | None = None) -> list[float] | None:
    """The query's vector, or None when no model is available or the call fails."""
    if embeddings is None and not llm.models_enabled():
        return None
    try:
        return (embeddings or llm.get_embeddings(phase, sink)).embed_query(text)
    except Exception:
        _log.warning("query not embedded; searching by keyword", exc_info=True)
        return None


def embed_texts(texts: list[str], phase: str, sink: UsageSink | None = None, *,
                embeddings: Embeddings | None = None, batch: int = BATCH) -> list[list[float] | None]:
    """One vector per text, in order; all None when no model is available."""
    if embeddings is None and not llm.models_enabled():
        return [None] * len(texts)
    model = embeddings or llm.get_embeddings(phase, sink)
    out: list[list[float] | None] = []
    for i in range(0, len(texts), batch):
        out.extend(model.embed_documents(texts[i: i + batch]))
    return out
