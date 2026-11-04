"""search_kb: passages from the knowledge bases and documents IN SCOPE for this run.

The scope is not the model's to choose (CLAUDE.md "AI and RAG"): the production comes from the run, the corpora and
the document filter from `RunContext.corpora` / `.document_ids`, which the composition root fills from trusted data.
A model supplies the question and, at most, ONE of the corpora already in scope. Results come back in the database's
total order; nothing here re-sorts them. Absent-safe: with no key the search is keyword-only.
"""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts.documents import Corpus
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.rag.embeddings import embed_query
from hiru_ai.rag.retrievers import HybridRetriever

KNOWN = {c.value for c in Corpus}
CONCISE_CHARS = 400


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "a smaller `k`, a `corpus`, or a more specific `query`"

    query: str = Field(min_length=2, max_length=500, description="What to look for")
    corpus: str | None = Field(None, max_length=40, description="Only this corpus, one of those in scope for this run")
    k: int = Field(5, ge=1, le=8, description="How many passages to return (at most 8)")


class Result(BaseModel):
    found: int
    passages: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    search = ctx.need("search", "Search")
    corpora = list(ctx.corpora)
    if not corpora:
        raise ToolRefused("no knowledge base is in scope for this run")
    unknown = [c for c in corpora if c not in KNOWN]
    if unknown:
        raise ToolRefused(f"unknown corpus {', '.join(unknown)}")
    if args.corpus is not None:
        if args.corpus not in corpora:  # a model may narrow the scope, never widen it
            raise ToolRefused(f"{args.corpus!r} is not in scope for this run",
                              how_to_fix=f"Use one of: {', '.join(corpora)}, or leave `corpus` out.",
                              example=f'{{"query": "...", "corpus": "{corpora[0]}"}}')
        corpora = [args.corpus]
    sink = ctx.sink()
    retriever = HybridRetriever(
        search=search, production_id=tooling.production_of(ctx), corpora=corpora,
        document_ids=None if ctx.document_ids is None else list(ctx.document_ids), k=args.k,
        embedder=lambda q: embed_query(q, "search_kb", sink))
    detailed = args.response_format == "detailed"
    passages = []
    for r in retriever.retrieve(args.query).rows:
        label = str(r.get("source") or "") + (f" — {r['heading']}" if r.get("heading") else "")
        text = str(r.get("content") or "")
        passages.append({"cite": str(r.get("id")), "source": label,
                         "text": text if detailed else text[:CONCISE_CHARS],
                         **({"corpus": r.get("corpus"), "context": r.get("context_header"), "score": r.get("score")}
                            if detailed else {})})
    return Result(found=len(passages), passages=passages)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
