"""The prompt writer in shot_producer (plan/2026-11-11c): the `prompt_writer` agent rewords the descriptive sections of
the first frame's prompt code has already written, and the `prompt_polish` step keeps the code's words wherever a fact
was lost.

    first frame  mode "frame_prompt": the frame brief's Shot, Composition, People, Place, Light, Colour and Mood
                 sections, stored on the shot (`design.frame_polish`) and used by the shot screen and the renderer
                 while the code's words for each section are the ones it was written from.

The video path is gone (plan/2026-11-20b D12): a video prompt is written by the `video_prompter` agent. Through two
parts found by id, so any other system can plug the writer in the same way. `PROMPT_WRITER__ENABLED` off (the default)
or no key: nothing is called and the code's prompt stands.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings

Row = dict[str, Any]
AGENT = "prompt_writer"


def writer_on() -> bool:
    return bool(get_settings().prompt_writer.enabled) and llm.models_enabled()


def polish(ctx: RunContext, kind: str, sections: Sequence[Row], names: Sequence[str]) -> Row | None:
    """Sections `{key, title, text}` → the merge (`texts`, `kept_code`, `checks`, `record`); None = nothing to send."""
    step = parts.module("step", "prompt_polish", "step")
    req = step.run({"op": "request", "kind": kind, "sections": list(sections), "names": list(names)})["request"]
    if not req["sections"]:
        return None
    answer = agents.build(AGENT).run(req, ctx)
    merged: Row = step.run({"op": "merge", "request": req, "answer": answer.model_dump(mode="json")})
    return merged


def polish_frame(ctx: RunContext, world: Row, shot: Row) -> Row | None:
    """The first frame's polish for one shot (what `design.frame_polish` stores), written from the code's own words;
    None when nothing could be sent. `world` is the frame_compose step's world for the shot's scene."""
    brief = parts.module("step", "frame_compose", "step").run({"op": "brief", **world, "shot": shot, "polished": False})
    return polish(ctx, "first_frame", brief["sections"], brief["names"])
