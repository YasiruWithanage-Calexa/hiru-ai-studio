"""scene_read: one scene of this run's production, only the parts asked for. Read-only."""
from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts import sceneplan
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused

Part = Literal["script", "lines", "shots", "canon", "reading", "staging", "coverage"]


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "a shorter `include`, or `shots` like \"S02-S04\""

    scene: str | None = Field(None, description='The scene, like "E1S2" (episode 1, scene 2). '
                                                  "Default: this run's scene")
    include: list[Part] = Field(["script", "shots"], max_length=7, description="Which parts to return")
    shots: str | None = Field(None, description='One shot or a range ("S03", "S02-S04"); narrows the `shots` part')


class Result(BaseModel):
    scene: str
    heading: str
    title: str
    status: str
    envelope_s: int
    script: list[dict[str, Any]] | None = None
    lines: list[dict[str, Any]] | None = None
    shots: list[dict[str, Any]] | None = None
    canon: list[dict[str, Any]] | None = None
    reading: dict[str, Any] | None = None
    staging: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None


def shot_range(text: str | None) -> tuple[int, int] | None:
    """"S03" → (3, 3); "S02-S04" or "2-4" → (2, 4); None → no narrowing."""
    if not text:
        return None
    match = re.fullmatch(r"\s*[Ss]?(\d{1,3})\s*(?:[-–]\s*[Ss]?(\d{1,3}))?\s*", text)
    if match is None:
        raise ToolRefused(f"{text!r} is not a shot or a range of shots", how_to_fix="Write S03 or S02-S04.",
                          example='{"shots": "S02-S04"}')
    low = int(match.group(1))
    return low, int(match.group(2) or low)


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    wanted = set(args.include)
    detailed = args.response_format == "detailed"
    lines = store.lines(str(scene["id"]))
    out = Result(scene=tooling.scene_label(scene), heading=str(scene.get("heading") or ""),
                 title=str(scene.get("title") or ""), status=str(scene.get("status") or ""),
                 envelope_s=int(scene.get("envelope_s") or 0))
    shots = store.shots(str(scene["id"]))
    code_of = {str(s["id"]): tooling.shot_code(int(s["number"])) for s in shots}
    if "script" in wanted:
        out.script = [{"block": i.index, "kind": i.kind, **({"speaker": i.speaker} if i.is_line else {}),
                       "text": i.text, **({"delivery": i.delivery} if i.is_line and i.delivery else {})}
                      for i in sceneplan.scene_items(scene, lines)]
    if "lines" in wanted:
        out.lines = [{"speaker": ln.get("speaker", ""), "text": ln.get("text", ""), "delivery": ln.get("delivery", ""),
                      "shot": code_of.get(str(ln.get("shot_id")), ""), "starts_s": ln.get("start_s"),
                      **({"overrun_s": ln["overrun_s"]} if ln.get("overrun_s") else {})} for ln in lines]
    if "shots" in wanted:
        span = shot_range(args.shots)
        chosen = [s for s in shots if span is None or span[0] <= int(s["number"]) <= span[1]]
        out.shots = [{"shot": tooling.shot_code(int(s["number"])),
                      "blocks": f"{s['block_start']}-{int(s['block_end']) - 1}",
                      "framing": s.get("framing"), "length_s": s.get("duration_s"), "start_s": s.get("start_s"),
                      "sound": s.get("sound_mode"), "words": s.get("words"), "word_target": s.get("word_target"),
                      "status": s.get("status"),
                      **({"title": s.get("title"), "join": s.get("camera_link"),
                          "locked": bool(s.get("duration_locked")), "beats": len(s.get("beats") or []),
                          "purpose": (s.get("intent") or {}).get("purpose", "")} if detailed else {})}
                     for s in chosen]
    if "canon" in wanted:
        speakers = {str(ln.get("character_id")) for ln in lines if ln.get("character_id")}
        place = str(scene["location_id"]) if scene.get("location_id") else ""
        cards = store.canon(tooling.production_of(ctx))
        out.canon = [{"code": c["code"], "name": c["name"], "kind": c["kind"]} for c in cards
                     if str(c["id"]) in speakers or str(c["id"]) == place]
    if "reading" in wanted:
        reading = scene.get("reading") or {}
        out.reading = reading if detailed else {k: reading[k] for k in ("about", "value", "tone", "ending")
                                                 if k in reading}
    if "staging" in wanted:
        staging = scene.get("staging") or {}
        out.staging = staging if detailed else {"zones": staging.get("zones", []),
                                                 "marks": len(staging.get("marks") or [])}
    if "coverage" in wanted:
        out.coverage = scene.get("coverage") or {}
    return out


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
