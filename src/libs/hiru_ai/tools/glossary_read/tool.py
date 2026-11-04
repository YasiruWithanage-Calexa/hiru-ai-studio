"""glossary_read: fixed spellings of people and places, for a translator that must stay consistent. Read-only.

No table behind it (plan/2026-11-04 D6): the canon's names and aliases are the fixed spellings, and the lines of the
scene in scope that a person already accepted a translation for show how those names were written in that language."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts.canon import name_key
from contracts.director_capabilities import script_of
from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext

KINDS = ("character", "location")


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`names`"

    language: str = Field(min_length=2, max_length=5,
                          description='The language the lines are written in: "si", "en", "ta"')
    names: list[str] | None = Field(None, max_length=30, description="Only these people or places (names or codes)")


class Result(BaseModel):
    language: str
    entries: list[dict[str, Any]]
    translated_lines_seen: int


def run(args: Args, ctx: RunContext) -> Result:
    store = ctx.need("scenes", "SceneStore")
    canon = [c for c in ctx.need("canon", "CanonStore").entities(tooling.production_of(ctx)) if c["kind"] in KINDS]
    if args.names:
        chosen = []
        for name in args.names:
            entity = views.find_entity(canon, name)
            if entity is None:
                raise tooling.not_found("person or place", name, views.entity_names(canon),
                                        example='{"language": "en", "names": ["C02"]}')
            chosen.append(entity)
        canon = list({str(e["id"]): e for e in chosen}.values())
    translated: list[dict[str, Any]] = []
    if ctx.scene_id is not None:
        _, scene = tooling.scene_in_scope(ctx, None)
        translated = [ln for ln in store.lines(str(scene["id"]))
                      if ln.get("source_text") and script_of(str(ln.get("text") or "")) == args.language]
    detailed = args.response_format == "detailed"
    entries = []
    for entity in canon:
        spellings = [str(entity["name"]), *(str(a) for a in entity.get("aliases") or [])]
        written = [s for s in spellings if any(name_key(s) in name_key(str(ln["text"])) for ln in translated)]
        entries.append({"code": entity["code"], "name": entity["name"],
                        "written_as": written,
                        **({"aliases": [str(a) for a in entity.get("aliases") or []], "kind": entity["kind"]}
                           if detailed else {})})
    return Result(language=args.language, entries=entries, translated_lines_seen=len(translated))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
