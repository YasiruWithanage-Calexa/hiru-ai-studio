"""A LangChain retriever over the `match_chunks` RPC (through the `Search` port).

`match_chunks` fuses vector and keyword ranks inside the database and returns a TOTAL order (ties broken on a stable
key), so the order of the documents here is the order of the rows: nothing in this module sorts. The scope (production,
corpora, documents) is fixed when the retriever is built, from data the caller trusts; the query is all a model gives.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

Row = dict[str, Any]
Embedder = Callable[[str], list[float] | None]

METADATA = ("id", "corpus", "document_id", "source", "ord", "heading", "context_header", "meta", "score",
            "vector_rank", "text_rank")


def to_document(row: Row, **extra: Any) -> Document:
    return Document(page_content=str(row["content"]), metadata={**{k: row[k] for k in METADATA if k in row}, **extra})


class MatchChunksRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    search: Any  # a `Search` port (hiru_ai.core.ports)
    production_id: UUID
    corpora: list[str]
    document_ids: list[str] | None = None  # None = every ready document of the production
    k: int = 6
    embedder: Embedder | None = None  # absent-safe: returns None when there is no model

    def embed(self, query: str) -> list[float] | None:
        return self.embedder(query) if self.embedder else None

    def fetch(self, query: str, embedding: list[float] | None, count: int) -> list[Row]:
        return list(self.search.chunks(
            query=query, embedding=embedding, production_id=self.production_id, corpora=list(self.corpora),
            document_ids=None if self.document_ids is None else list(self.document_ids), k=count))

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [to_document(r) for r in self.fetch(query, self.embed(query), self.k)]
