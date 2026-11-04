"""Keyword-only retrieval: `match_chunks` with no embedding runs the full-text half alone.

This is what search does with no key, and what CI's retrieval eval measures ("text" in `tests/eval/thresholds.json`).
"""
from __future__ import annotations

from hiru_ai.rag.retrievers.match_chunks import MatchChunksRetriever


class KeywordRetriever(MatchChunksRetriever):
    def embed(self, query: str) -> list[float] | None:
        return None
