"""jonathan_pack: the data in → the author's context pack out (plan/2026-11-05e §5). Deterministic, no model.

    {"scene": SceneS, "production": {style_note, rules, people[{name, code, look, voice}]},
     "context": {heading, note, episode_title, synopsis, before, after, place},
     "link": "continuous" | "carry" | "", "start": EndState | None, "canon_looks": {name: look},
     "look_changes": [LookChange], "last_shot_ir": {…} | None, "reading": str, "removed": [str]}
        → {"text", "parts": {production, scene, start, last_shot, script}, "words"}

The parts are in the order that caches best: what is the same for the whole job comes first, the script last.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from hiru_ai.steps.jonathan.jonathan_pack import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return logic.pack(payload)
    except (ValidationError, KeyError) as exc:
        return {"malformed": str(exc)[:600], "text": "", "parts": {}, "words": 0}


