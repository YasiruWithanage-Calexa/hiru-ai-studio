"""shot_write: save what a shot pipeline produced for a scene of this run's production.

Three modes, one tool, because the shot producer and the splitter write the same few tables:
  * `plan`   - the splitter's fresh plan: the scene's shots are replaced, its lines re-bound (the words never change);
  * `design` - the DoP's stored design for one shot (`ir` and `design`);
  * `prompt` - a new video-prompt version for one shot (the shot moves to `prompt`; a taken version is retried once).
"""
from __future__ import annotations

from typing import Any, Literal, Self

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused

WORDS = ("text", "speaker", "delivery")


class Args(BaseModel):
    mode: Literal["plan", "design", "prompt"]
    scene_id: str
    shots: list[dict[str, Any]] = Field(default_factory=list, description="plan: the new shot rows")
    lines: list[dict[str, Any]] = Field(default_factory=list, description="plan: line rows re-bound to the shots")
    scene_fields: dict[str, Any] = Field(default_factory=dict, description="plan: columns of the scene to change")
    shot_id: str = Field("", description="design, prompt: the shot")
    ir: dict[str, Any] = Field(default_factory=dict, description="design: the stored intermediate representation")
    design: dict[str, Any] = Field(default_factory=dict, description="design: the design record")
    prompt: dict[str, Any] = Field(default_factory=dict, description="prompt: the video_prompts row")

    @model_validator(mode="after")
    def _needs(self) -> Self:
        if self.mode in ("design", "prompt") and not self.shot_id:
            raise ValueError(f"mode {self.mode!r} needs a shot_id")
        if self.mode == "prompt" and not self.prompt:
            raise ValueError("mode 'prompt' needs the prompt row")
        return self


class Result(BaseModel):
    mode: str
    shots: int = 0
    lines: int = 0


def run(args: Args, ctx: RunContext) -> Result:
    store, _ = tooling.scene_of(ctx, args.scene_id)
    if args.mode == "plan":
        stored = {str(r["id"]): r for r in store.lines(args.scene_id)}
        for row in args.lines:  # re-binding only: a splitter never writes or rewords a line
            before = stored.get(str(row.get("id")))
            if before is None or any(k in row and row[k] != before.get(k) for k in WORDS):
                raise ToolRefused("a shot plan re-binds lines; it never adds or rewords one")
        if any(str(s.get("scene_id", args.scene_id)) != str(args.scene_id) for s in args.shots):
            raise ToolRefused("a shot belongs to another scene")
        if any(k in args.scene_fields for k in ("id", "production_id", "episode_id")):
            raise ToolRefused("a scene cannot change which production or episode it is in")
        store.replace_shots(args.scene_id, args.shots, args.lines, args.scene_fields)
        return Result(mode="plan", shots=len(args.shots), lines=len(args.lines))
    if args.shot_id not in {str(r["id"]) for r in store.shots(args.scene_id)}:
        raise ToolRefused(f"shot {args.shot_id} is not in this scene")
    if args.mode == "design":
        store.save_design(args.shot_id, args.ir, args.design)
    else:
        if str(args.prompt.get("shot_id", args.shot_id)) != args.shot_id:
            raise ToolRefused("the prompt row is for another shot")
        store.add_prompt({**args.prompt, "shot_id": args.shot_id, "production_id": str(ctx.production_id)})
    return Result(mode=args.mode, shots=1)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
