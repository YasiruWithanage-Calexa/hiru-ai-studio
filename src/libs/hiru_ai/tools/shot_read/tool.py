"""shot_read: one shot, what it was made against, and whether the design and the prompt are out of date. Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    shot: str = Field(description='The shot: "S03" or 3')
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')


class Result(BaseModel):
    shot: str
    scene: str
    title: str
    framing: str
    length_s: int
    start_s: float | None
    sound: str
    join: str
    words: int
    word_target: int | None
    status: str
    people: list[str]
    intent: dict[str, Any]
    design: dict[str, Any]
    prompt: dict[str, Any] | None
    out_of_date: bool
    pins: dict[str, Any] | None = None
    beats: list[dict[str, Any]] | None = None


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    scene_id = str(scene["id"])
    shots = store.shots(scene_id)
    number = tooling.shot_number(args.shot)
    shot = views.shot_by_number(shots, number)
    if shot is None:
        raise tooling.not_found("shot", tooling.shot_code(number), [tooling.shot_code(int(s["number"])) for s in shots],
                                example='{"shot": "S01"}')
    canon = store.canon(tooling.production_of(ctx))
    code_of = {str(c["id"]): str(c["code"]) for c in canon}
    made = views.MadeAgainst(scene, shot, store.lines(scene_id), canon)
    detailed = args.response_format == "detailed"

    design = shot.get("design") or {}
    design_why = made.reasons(design.get("pins")) if design.get("pins") else []
    ir = shot.get("ir") or {}
    design_view: dict[str, Any] = {"made": bool(design.get("pins") and ir), "out_of_date": bool(design_why),
                                   "why": design_why}
    if detailed and ir:
        design_view |= {"setting": ir.get("setting", ""), "lighting": ir.get("lighting", ""),
                        "subjects": [{"who": s.get("id", ""), "position": s.get("position", ""),
                                      "action": s.get("action", "")} for s in ir.get("subjects") or []]}

    latest = store.latest_prompts([str(shot["id"])]).get(str(shot["id"]))
    prompt_view = None
    if latest is not None:
        prompt_why = made.reasons(latest.get("pins"))
        failed = [str(c.get("label", "")) for c in latest.get("checks") or [] if c.get("tone") == "fail"]
        prompt_view = {"version": latest.get("version"), "out_of_date": bool(prompt_why), "why": prompt_why,
                       "failed_checks": failed}

    intent = shot.get("intent") or {}
    intent_view = {k: intent.get(k, "") for k in ("purpose", "what_we_see", "emotional_beat")} if intent else {}
    if intent:
        intent_view["on_screen"] = [code_of.get(str(i), str(i)) for i in intent.get("on_screen") or []]
        intent_view["heard_only"] = [code_of.get(str(i), str(i)) for i in intent.get("heard_only") or []]
        if detailed:
            intent_view |= {"voice_source": intent.get("voice_source", ""), "by": intent.get("by", "")}

    return Result(
        shot=tooling.shot_code(number), scene=tooling.scene_label(scene), title=str(shot.get("title") or ""),
        framing=str(shot.get("framing") or ""), length_s=int(shot.get("duration_s") or 0), start_s=shot.get("start_s"),
        sound=str(shot.get("sound_mode") or ""), join=str(shot.get("camera_link") or "cut"),
        words=int(shot.get("words") or 0), word_target=shot.get("word_target"), status=str(shot.get("status") or ""),
        people=[code_of.get(i, i) for i in made.cast_ids], intent=intent_view, design=design_view, prompt=prompt_view,
        out_of_date=bool(design_why) or bool(prompt_view and prompt_view["out_of_date"]),
        pins={"shot_version": made.now.shot_version, "script_hash": made.now.script_hash,
              "canon": {code_of.get(k, k): v for k, v in made.now.canon.items()}} if detailed else None,
        beats=[{"time": f"{b.get('start_s')}-{b.get('end_s')}s", "action": b.get("action", ""),
                "camera": b.get("camera", "")} for b in shot.get("beats") or []] if detailed else None)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
