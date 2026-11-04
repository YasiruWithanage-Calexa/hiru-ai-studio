"""technique_lookup: cinematography techniques that deliver a described intent (`match_craft_techniques`).

Absent-safe, as the shot producer's lookup is (`rag.retrievers.techniques`): with no key the search is keyword-only,
and a search that fails answers with no techniques; it never raises into the agent that asked.
"""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.rag.embeddings import embed_query
from hiru_ai.rag.retrievers import TechniqueRetriever

USE_CHARS = 200


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "a smaller `k`"

    intent: str = Field(min_length=2, max_length=500, description="What the shot must make the viewer feel or see")
    k: int = Field(4, ge=1, le=6, description="How many techniques to return (at most 6)")


class Result(BaseModel):
    found: int
    techniques: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    search = ctx.need("search", "Search")
    sink = ctx.sink()
    retriever = TechniqueRetriever(search=search, k=args.k,
                                   embedder=lambda q: embed_query(q, "shot_producer.techniques", sink))
    detailed = args.response_format == "detailed"
    out = []
    for r in retriever.rows(args.intent):
        use = str(r.get("effect") or r.get("use_case") or r.get("effect_text") or r.get("definition") or "")
        out.append({"name": r.get("name", ""), "use": use if detailed else use[:USE_CHARS],
                    "phrase": r.get("prompt_phrase", ""),
                    **({"definition": r.get("definition", ""), "category": r.get("category", ""),
                        "example": r.get("example_scene") or r.get("example_film") or ""} if detailed else {})})
    return Result(found=len(out), techniques=out)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
