"""canon_find: the canon as a short list, so a prompt does not have to carry it. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts.canon import name_key
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext


class Args(tooling.Paged):
    NARROW_WITH: ClassVar[str] = "`kind`, `query` or a smaller `page_size`"

    kind: Literal["character", "location", "prop"] | None = Field(None, description="Only this kind")
    query: str | None = Field(None, max_length=80, description="A word in the name, a nickname or the code")


class Result(BaseModel):
    total: int
    page: int
    next_page: int | None
    entities: list[dict[str, Any]]


def run(args: Args, ctx: RunContext) -> Result:
    entities = ctx.need("canon", "CanonStore").entities(tooling.production_of(ctx))
    key = name_key(args.query or "")
    kept = [e for e in entities if (args.kind is None or e["kind"] == args.kind)
            and (not key or any(key in name_key(str(n)) for n in (e["code"], e["name"], *(e.get("aliases") or []))))]
    shown, meta = tooling.page(kept, args.page, args.page_size)
    detailed = args.response_format == "detailed"
    rows = [{"code": e["code"], "kind": e["kind"], "name": e["name"],
             **({"aliases": e.get("aliases") or [], "locked": bool(e.get("locked")),
                 "version": (e.get("current") or {}).get("version")} if detailed else {})} for e in shown]
    return Result(total=int(meta["total"] or 0), page=int(meta["page"] or 1), next_page=meta["next_page"],
                  entities=rows)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
