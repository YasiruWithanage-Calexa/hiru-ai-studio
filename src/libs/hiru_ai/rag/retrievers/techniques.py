"""Technique retrieval: `match_craft_techniques`, an intent ("the viewer must feel she is powerless") in and the
cinematography techniques that deliver it out.

Absent-safe, as the shot producer's lookup is: no embedding is keyword-only, and a search that fails answers with none.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from hiru_ai.core.telemetry import logger

_log = logger("rag.techniques")
Row = dict[str, Any]


class TechniqueRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    search: Any  # a `Search` port
    k: int = 4
    embedder: Callable[[str], list[float] | None] | None = None

    def rows(self, query: str) -> list[Row]:
        embedding = self.embedder(query) if self.embedder else None
        try:
            return list(self.search.techniques(query, embedding, self.k))
        except Exception:
            _log.warning("technique lookup failed; answering with none", exc_info=True)
            return []

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [Document(page_content=str(r.get("effect_text") or r.get("definition") or r.get("name") or ""),
                         metadata=r) for r in self.rows(query)]
