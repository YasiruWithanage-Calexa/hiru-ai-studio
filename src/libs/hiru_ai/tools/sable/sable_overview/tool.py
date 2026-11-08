"""sable_overview: the production at a glance (plan/2026-11-08 §4.3). Read-only.

"How far along is episode 3?" has no tool otherwise: `episode_read` is one episode's synopsis and headings. This reads
the scene rows the run already has a port for (`scenes`, with each row's stored plans) and the open questions
(`structure`), and counts each listed scene's shots, a page at a time, so a production of many scenes costs one page of
reads. Takes and renders are not read here (no port carries them): it says shots, never takes.
"""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import Row

PLANNERS = ("jonathan", "david", "adam")  # a stored plan on the scene row names who planned it (newest planner first)
Waiting = Literal["plan", "approval"]


class Args(tooling.Paged):
    NARROW_WITH: ClassVar[str] = "`episode`, `waiting: true` or a smaller `page_size`"

    episode: int | None = Field(None, ge=1, description="Only this episode's scenes. Default: every episode")
    waiting: bool = Field(False, description="Only the scenes not planned yet or not approved yet")


class Result(BaseModel):
    production: str
    episodes: list[dict[str, Any]]
    open_questions: int
    scenes: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    next_page: int | None


def planner_of(scene: Row) -> str:
    """Who planned the scene: the planner whose plan is stored on it, else "classic" when it has shots from the
    classic shot list, else ""."""
    for name in PLANNERS:
        stored = scene.get(name)
        if isinstance(stored, dict) and isinstance(stored.get("plan"), dict):
            return name
    return ""


def waiting_for(scene: Row, shots: int) -> Waiting | None:
    if not shots and not planner_of(scene):
        return "plan"
    if scene.get("status") != "approved":
        return "approval"
    return None


def run(args: Args, ctx: RunContext) -> Result:
    production = tooling.production_of(ctx)
    store = ctx.need("scenes", "SceneStore")
    rows = sorted(store.scenes(production, None),
                  key=lambda r: (int((r.get("episode") or {}).get("number") or 0), int(r.get("number") or 0)))
    structure = ctx.ports.structure
    episodes: dict[int, Row] = {}
    if structure is not None:
        for e in structure.episodes(production):
            episodes[int(e["number"])] = dict(e)
    for r in rows:
        number = int((r.get("episode") or {}).get("number") or 0)
        episodes.setdefault(number, {"number": number, "title": (r.get("episode") or {}).get("title") or ""})
    questions = len(structure.open_questions(production)) if structure is not None else 0

    def number_of(r: Row) -> int:
        return int((r.get("episode") or {}).get("number") or 0)

    lines = []
    for number in sorted(episodes):
        own = [r for r in rows if number_of(r) == number]
        lines.append({"episode": number, "title": str(episodes[number].get("title") or ""),
                      "status": str(episodes[number].get("status") or ""), "scenes": len(own),
                      "planned": sum(1 for r in own if planner_of(r)),
                      "approved": sum(1 for r in own if r.get("status") == "approved")})
    chosen = [r for r in rows if args.episode is None or number_of(r) == args.episode]
    if args.episode is not None and not chosen:
        raise tooling.not_found("episode", str(args.episode), [str(n) for n in sorted(episodes)],
                                example='{"episode": 1}', where=f"Episodes: {', '.join(map(str, sorted(episodes)))}.")
    if args.waiting:  # an approved scene waits for nothing; any other waits for its plan or for approval
        chosen = [r for r in chosen if r.get("status") != "approved"]
    detailed = args.response_format == "detailed"
    shown: list[dict[str, Any]] = []
    picked, meta = tooling.page(chosen, args.page, args.page_size)
    for r in picked:
        shots = len(store.shots(r["id"]))
        why = waiting_for(r, shots)
        line: dict[str, Any] = {"scene": tooling.scene_label(r), "heading": str(r.get("heading") or ""),
                                "status": str(r.get("status") or ""),
                                "planner": planner_of(r) or ("classic" if shots else ""), "shots": shots}
        if why:
            line["waiting_for"] = why
        if detailed:
            line |= {"title": str(r.get("title") or ""), "time_of_day": str(r.get("time_of_day") or ""),
                     "envelope_s": r.get("envelope_s")}
        shown.append(line)
    title = ""
    if (row := store.production(production)) is not None:
        title = str(row.get("title") or "")
    return Result(production=title, episodes=lines, open_questions=questions, scenes=shown,
                  total=int(meta["total"] or 0), page=int(meta["page"] or 1), page_size=int(meta["page_size"] or 1),
                  next_page=meta["next_page"])


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
