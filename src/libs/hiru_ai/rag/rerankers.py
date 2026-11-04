"""Rerankers: read the top candidates and drop the unrelated ones (PLAN.md §7). Absent-safe: with no key, or when the
call fails, there is no rerank and the fusion order stands.

A reranker is any callable `(query, passages) -> order | None`; `order` lists passage indexes, most relevant first.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from hiru_ai.core import llm
from hiru_ai.core.telemetry import logger
from hiru_ai.core.usage import UsageCallback, UsageSink
from hiru_ai.rag.ranking import RERANK_SYSTEM, order_by_relevance, rerank_user

_log = logger("rag.rerankers")
Reranker = Callable[[str, Sequence[str]], list[int] | None]


class Score(BaseModel):
    n: int
    relevance: int


class Ranking(BaseModel):
    ranking: list[Score]


class LLMReranker:
    """Scores every passage 0..3 with a mid-tier model (`medium`, as the API does today)."""

    def __init__(self, sink: UsageSink | None = None, *, tier: str = "medium", phase: str = "search.rerank") -> None:
        self.sink, self.tier, self.phase = sink, tier, phase

    def __call__(self, query: str, passages: Sequence[str]) -> list[int] | None:
        if not passages or not llm.models_enabled():
            return None
        try:
            answer = llm.get_structured(self.tier, Ranking).invoke(
                [SystemMessage(RERANK_SYSTEM), HumanMessage(rerank_user(query, passages))],
                config={"callbacks": [UsageCallback(self.sink, self.phase)]})
        except Exception:
            _log.warning("rerank failed; keeping rank-fusion order", exc_info=True)
            return None
        return order_by_relevance([s.model_dump() for s in answer.ranking], len(passages))
