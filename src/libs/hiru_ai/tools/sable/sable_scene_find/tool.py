"""sable_scene_find: scenes found by who, where, when and words (plan/2026-11-08 §4.3). Read-only.

"Which scenes have Nimal at the temple at night?" is a search over scenes, not over document passages. A person is found
in a scene when one of its lines is theirs (the line's character, or its speaker as written) or when the scene's action
names them (their name or an alias); a place when the heading names it or the scene's location is that canon place.
Lines are read only for the scenes the other filters leave, so a narrow question reads little.
"""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts.canon import name_key
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.ports import Row

EXAMPLE = '{"character": "Nimal", "place": "temple", "time_of_day": "night"}'


class Args(tooling.Paged):
    NARROW_WITH: ClassVar[str] = "another filter (`episode`, `place`, `time_of_day`) or a smaller `page_size`"

    character: str | None = Field(None, description="A person: canon code, name or alias")
    place: str | None = Field(None, description="A place: a word of the heading, or a canon place's name or code")
    time_of_day: str | None = Field(None, description='As the heading says it: "day", "night", "dawn" ...')
    episode: int | None = Field(None, ge=1, description="Only this episode")
    text: str | None = Field(None, description="A word or phrase of the heading or the title")


class Result(BaseModel):
    scenes: list[dict[str, Any]]
    matched: dict[str, str]
    total: int
    page: int
    page_size: int
    next_page: int | None


def _names(entity: Row) -> set[str]:
    return {k for k in (name_key(str(entity.get("name") or "")), name_key(str(entity.get("code") or "")),
                        *(name_key(str(a)) for a in entity.get("aliases") or [])) if k}


def _entity(canon: list[Row], kind: str, wanted: str) -> Row | None:
    key = name_key(wanted)
    return next((e for e in canon if e.get("kind") == kind and key in _names(e)), None)


def _contains(text: str, keys: set[str]) -> bool:
    words = f" {name_key(text)} "
    return any(f" {k} " in words for k in keys)


def _given(value: str | None) -> bool:
    return bool(value and value.strip())


def run(args: Args, ctx: RunContext) -> Result:
    production = tooling.production_of(ctx)
    if not any(_given(v) for v in (args.character, args.place, args.time_of_day, args.text)) and args.episode is None:
        raise ToolRefused("give at least one filter", how_to_fix="Pass character, place, time_of_day, episode or text.",
                          example=EXAMPLE)
    store = ctx.need("scenes", "SceneStore")
    canon = ctx.ports.canon
    entities = canon.entities(production) if canon is not None else []
    matched: dict[str, str] = {}
    person: Row | None = None
    if _given(args.character):
        person = _entity(entities, "character", str(args.character))
        if person is None:
            raise tooling.not_found("character", str(args.character),
                                    [str(e.get("name")) for e in entities if e.get("kind") == "character"],
                                    example=EXAMPLE, where="canon_find lists the characters.")
        matched["character"] = f"{person.get('code') or ''} {person.get('name') or ''}".strip()
    place: Row | None = None
    if _given(args.place):
        place = _entity(entities, "location", str(args.place))
        if place is not None:
            matched["place"] = f"{place.get('code') or ''} {place.get('name') or ''}".strip()

    rows = sorted(store.scenes(production, None),
                  key=lambda r: (int((r.get("episode") or {}).get("number") or 0), int(r.get("number") or 0)))
    episodes = sorted({int((r.get("episode") or {}).get("number") or 0) for r in rows})
    if args.episode is not None and args.episode not in episodes:
        raise tooling.not_found("episode", str(args.episode), [str(n) for n in episodes], example='{"episode": 1}',
                                where=f"Episodes: {', '.join(map(str, episodes))}.")

    def keep(r: Row) -> bool:
        heading = str(r.get("heading") or "")
        if args.episode is not None and (r.get("episode") or {}).get("number") != args.episode:
            return False
        if _given(args.time_of_day):
            when = name_key(str(args.time_of_day))
            if when not in name_key(str(r.get("time_of_day") or "")) and not _contains(heading, {when}):
                return False
        if _given(args.place):
            at_place = place is not None and str(r.get("location_id") or "") == str(place.get("id"))
            words = _names(place) if place is not None else {name_key(str(args.place))}
            if not at_place and not _contains(heading, words) and name_key(str(args.place)) not in name_key(heading):
                return False
        if _given(args.text):
            key = name_key(str(args.text))
            if key not in name_key(heading) and key not in name_key(str(r.get("title") or "")):
                return False
        return True

    chosen = [r for r in rows if keep(r)]
    how: dict[str, str] = {}
    if person is not None:
        keys = _names(person)
        found = []
        for r in chosen:
            speaks = any(str(line.get("character_id") or "") == str(person.get("id"))
                         or name_key(str(line.get("speaker") or "")) in keys for line in store.lines(r["id"]))
            named = any(_contains(str(b.get("text") or ""), keys) for b in r.get("script") or []
                        if isinstance(b, dict) and b.get("kind") != "dialogue")
            if speaks or named:
                found.append(r)
                how[str(r["id"])] = "speaks" if speaks else "named in the action"
        chosen = found
    picked, meta = tooling.page(chosen, args.page, args.page_size)
    detailed = args.response_format == "detailed"
    scenes = []
    for r in picked:
        line: dict[str, Any] = {"scene": tooling.scene_label(r), "heading": str(r.get("heading") or ""),
                                "time_of_day": str(r.get("time_of_day") or "")}
        if r.get("title") or detailed:
            line["title"] = str(r.get("title") or "")
        if str(r["id"]) in how:
            line["character"] = how[str(r["id"])]
        if detailed:
            line["status"] = str(r.get("status") or "")
        scenes.append(line)
    return Result(scenes=scenes, matched=matched, total=int(meta["total"] or 0), page=int(meta["page"] or 1),
                  page_size=int(meta["page_size"] or 1), next_page=meta["next_page"])


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
