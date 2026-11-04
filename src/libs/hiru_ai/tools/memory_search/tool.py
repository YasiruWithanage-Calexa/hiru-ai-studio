"""memory_search: the production's remembered decisions (corpus `memory`): by meaning with a key, else by words."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.rag.embeddings import embed_query

CONCISE_CHARS = 300


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "a smaller `k` or a more specific `query`"

    query: str = Field(min_length=2, max_length=500, description="What you want to know the decisions about")
    k: int = Field(4, ge=1, le=8, description="How many decisions to return (at most 8)")


class Result(BaseModel):
    found: int
    memories: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    search = ctx.need("search", "Search")
    sink = ctx.sink()
    embedding = embed_query(args.query, "memory_search", sink)  # None without a key: the search is by words
    rows = search.memory(args.query, embedding, tooling.production_of(ctx), args.k)
    detailed = args.response_format == "detailed"
    memories = [{"cite": str(r["id"]), "text": str(r["content"]) if detailed else str(r["content"])[:CONCISE_CHARS],
                 **({"heading": r.get("heading", ""), "score": r.get("score")} if detailed else {})} for r in rows]
    return Result(found=len(memories), memories=memories)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
