"""prompt_writer hooks (plan/2026-11-11c): rewords a prompt's descriptive sections as film language.

Code writes the prompt first, from what the shot planner saved, and that prompt is complete. This agent is sent only the
sections whose wording may change (`contracts.prompt_polish.POLISHABLE`), each with the words it must keep. Code checks
its answer section by section and keeps the code's words wherever a fact was lost (`contracts.prompt_polish.merge`), so
the worst answer gives the code's prompt. No key, or a failed call: the fallback is the code's own words.

Reusable: any system with a prompt in sections calls it by id (`agents.build("prompt_writer")`), through the
`prompt_polish` step that builds the request and applies the answer.
"""
from __future__ import annotations

import json

from hiru_ai.agents.prompt_writer.schema import Input, Output, Written

_FOR = {"first_frame": "ONE STILL FRAME for an image model (the opening frame of a shot)",
        "video": "ONE VIDEO CLIP for a video model (the shot as it plays)"}


def user_message(inp: Input) -> str:
    rows = [json.dumps({"key": s.key, "title": s.title, "text": s.text, "keep": s.keep}, ensure_ascii=False)
            for s in inp.sections]
    return f"<prompt for=\"{_FOR[inp.kind]}\">\n" + "\n".join(rows) + "\n</prompt>"


def fallback(inp: Input) -> Output:
    """No model: every section as code wrote it (the merge then changes nothing)."""
    return Output(sections=[Written(key=s.key, text=s.text) for s in inp.sections])
