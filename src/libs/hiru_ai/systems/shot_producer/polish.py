"""The prompt writer in shot_producer (plan/2026-11-11c): the `prompt_writer` agent rewords the descriptive sections of
a prompt code has already written, and the `prompt_polish` step keeps the code's words wherever a fact was lost.

    video        a new prompt version (mode "prompt"): its Setting, Subjects, Story, Camera and Lighting sections; the
                 first frame line, style, join, voices, action and dialogue, sound, constraints and format never change.
    first frame  mode "frame_prompt": the frame brief's Shot, Composition, People, Place, Light, Colour and Mood
                 sections, stored on the shot (`design.frame_polish`) and used by the shot screen and the renderer
                 while the code's words for each section are the ones it was written from.

Both go through the same two parts, found by id, so any other system can plug the writer in the same way.
`PROMPT_WRITER__ENABLED` off (the default) or no key: nothing is called and the code's prompt stands.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.producer import PromptSection, prompt_text
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


def polish_video(ctx: RunContext, prompt: Row, names: Sequence[str]) -> Row:
    """A video prompt row with its descriptive sections reworded, its prose rebuilt and the writer's checks added. A
    section holding a spoken line (Sinhala kept apart) is never sent."""
    sections: list[Row] = list(prompt.get("sections") or [])
    plain = [{"key": s["id"], "title": s.get("title") or s["id"],
              "text": "".join(str(seg.get("text") or "") for seg in s.get("segments") or [])}
             for s in sections if all(seg.get("sinhala") is None for seg in s.get("segments") or [])]
    merged = polish(ctx, "video", plain, names)
    if not merged:
        return prompt
    texts: dict[str, str] = merged["texts"]
    new = [{**s, "segments": [{"text": texts[s["id"]]}]} if s["id"] in texts else s for s in sections]
    return {**prompt, "sections": new, "prose": prompt_text([PromptSection.model_validate(s) for s in new]),
            "checks": [*(prompt.get("checks") or []), *merged["checks"]]}


def polish_frame(ctx: RunContext, world: Row, shot: Row) -> Row | None:
    """The first frame's polish for one shot (what `design.frame_polish` stores), written from the code's own words;
    None when nothing could be sent. `world` is the frame_compose step's world for the shot's scene."""
    brief = parts.module("step", "frame_compose", "step").run({"op": "brief", **world, "shot": shot, "polished": False})
    return polish(ctx, "first_frame", brief["sections"], brief["names"])
