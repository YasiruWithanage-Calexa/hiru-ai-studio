"""episode_read: an episode and the scenes around a scene, so a prompt need not carry the whole structure. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.ports import Row


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    episode: int | None = Field(None, ge=1, description="The episode number. Default: the episode of this run's scene")
    around_scene: str | None = Field(None, description='A scene, like "E1S2": also return the scenes either side')


class Result(BaseModel):
    episode: int
    title: str
    synopsis: str
    status: str
    scenes: list[dict[str, Any]]
    previous: dict[str, Any] | None = None
    next: dict[str, Any] | None = None


def label(episode: int, header: Row) -> str:
    return f"E{episode}S{header['number']}"


def locate(ref: str | None, headers: list[Row], number_of: dict[str, int], ctx: RunContext) -> Row:
    """The scene header a person means: "E1S2", "2" (in the episode of the scene in scope) or, with none, the scene in
    scope."""
    text = (ref or "").strip()
    if not text:
        if ctx.scene_id is None:
            raise ToolRefused("this run has no scene in scope",
                              how_to_fix="Pass `episode`, or `around_scene` like E1S2.",
                              example='{"around_scene": "E1S2"}')
        found = next((h for h in headers if str(h["id"]) == str(ctx.scene_id)), None)
        if found is None:
            raise ToolRefused("the scene this run is about is not in the structure")
        return found
    parsed = tooling.parse_scene_ref(text)
    if parsed is None:
        raise ToolRefused(f"{text!r} is not a scene", how_to_fix="Name a scene like E1S2 (episode 1, scene 2).",
                          example='{"around_scene": "E1S2"}')
    episode, number = parsed
    if episode is None and ctx.scene_id is not None:
        here = next((h for h in headers if str(h["id"]) == str(ctx.scene_id)), None)
        episode = number_of.get(str(here["episode_id"])) if here else None
    found_one = next((h for h in headers if int(h["number"]) == number
                      and (episode is None or number_of.get(str(h["episode_id"])) == episode)), None)
    if found_one is None:
        raise tooling.not_found("scene", text, [label(number_of.get(str(h["episode_id"]), 0), h) for h in headers],
                                example='{"around_scene": "E1S2"}')
    return found_one


def run(args: Args, ctx: RunContext) -> Result:
    production = tooling.production_of(ctx)
    structure = ctx.need("structure", "StructureStore")
    episodes = {str(e["id"]): e for e in structure.episodes(production)}
    number_of = {k: int(e["number"]) for k, e in episodes.items()}
    headers = sorted(structure.scene_headers(production),
                     key=lambda h: (number_of.get(str(h["episode_id"]), 0), int(h["number"])))
    around = locate(args.around_scene, headers, number_of, ctx) if args.around_scene is not None else None
    wanted = args.episode
    if wanted is None:
        anchor = around if around is not None else locate(None, headers, number_of, ctx)
        wanted = number_of.get(str(anchor["episode_id"]))
    episode = next((e for e in episodes.values() if int(e["number"]) == wanted), None)
    if episode is None:
        raise tooling.not_found("episode", str(wanted), [str(n) for n in sorted(number_of.values())],
                                example='{"episode": 1}',
                                where=f"Episodes: {', '.join(str(n) for n in sorted(number_of.values()))}.")
    detailed = args.response_format == "detailed"

    def line(header: Row) -> dict[str, Any]:
        row = {"scene": label(number_of.get(str(header["episode_id"]), 0), header),
               "heading": header.get("heading", ""),
               "title": header.get("title", "")}
        return row if detailed or header.get("title") else {k: row[k] for k in ("scene", "heading")}

    own = [h for h in headers if str(h["episode_id"]) == str(episode["id"])]
    out = Result(episode=int(episode["number"]), title=str(episode.get("title") or ""),
                 synopsis=str(episode.get("synopsis") or ""), status=str(episode.get("status") or ""),
                 scenes=[line(h) for h in own])
    if around is not None:
        at = next(n for n, h in enumerate(headers) if str(h["id"]) == str(around["id"]))
        out.previous = line(headers[at - 1]) if at > 0 else None
        out.next = line(headers[at + 1]) if at + 1 < len(headers) else None
    return out


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
