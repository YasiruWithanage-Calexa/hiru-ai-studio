"""prompt_check: a stored video prompt linted in code (the `prompt_lint` step). Read-only."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "`response_format: concise`"

    shot: str = Field(description='The shot: "S03" or 3')
    scene: str | None = Field(None, description='The scene, like "E1S2". Default: this run\'s scene')
    version: int | None = Field(None, ge=1, description="The prompt version to check. Only the latest can be checked")


class Result(BaseModel):
    shot: str
    version: int
    ok: bool
    findings: list[dict[str, Any]]
    words: int | None = None


def run(args: Args, ctx: RunContext) -> Result:
    store, scene = tooling.scene_in_scope(ctx, args.scene)
    scene_id = str(scene["id"])
    shots = store.shots(scene_id)
    number = tooling.shot_number(args.shot)
    shot = views.shot_by_number(shots, number)
    if shot is None:
        raise tooling.not_found("shot", tooling.shot_code(number), [tooling.shot_code(int(s["number"])) for s in shots],
                                example='{"shot": "S01"}')
    prompt = store.latest_prompts([str(shot["id"])]).get(str(shot["id"]))
    code = tooling.shot_code(number)
    if prompt is None:
        raise ToolRefused(f"{code} has no prompt yet", how_to_fix="Check it after the shot producer has written one; "
                          "shot_read says whether a shot has a prompt.", example=f'{{"shot": "{code}"}}')
    if args.version is not None and int(args.version) != int(prompt["version"]):
        raise ToolRefused(f"{code} is on prompt v{prompt['version']}; v{args.version} is not kept for checking",
                          how_to_fix="Leave `version` out to check the latest.", example=f'{{"shot": "{code}"}}')
    out = parts.module("step", "prompt_lint", "step").run(
        {"prompt": prompt, "shot": shot, "lines": store.lines(scene_id)})
    return Result(shot=code, version=int(prompt["version"]), ok=out["ok"], findings=out["findings"],
                  words=len(str(prompt.get("prose") or "").split()) if args.response_format == "detailed" else None)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
