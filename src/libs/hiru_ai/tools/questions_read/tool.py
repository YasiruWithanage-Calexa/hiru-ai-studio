"""questions_read: the structure build's open questions. Read-only; answering one is a person's job."""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext


class Args(tooling.Paged):
    NARROW_WITH: ClassVar[str] = "a smaller `page_size`"

    status: Literal["open"] = Field("open", description="Only open questions are listed")


class Result(BaseModel):
    total: int
    next_page: int | None
    questions: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    rows = ctx.need("structure", "StructureStore").open_questions(tooling.production_of(ctx))
    shown, meta = tooling.page(rows, args.page, args.page_size)
    detailed = args.response_format == "detailed"
    return Result(total=int(meta["total"] or 0), next_page=meta["next_page"],
                  questions=[{"scope": q.get("scope", ""), "title": q.get("title", ""),
                              **({"question": q.get("body", "")} if detailed else {})} for q in shown])


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
