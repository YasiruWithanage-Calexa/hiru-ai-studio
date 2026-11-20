"""video_prompt: the code around the `video_prompter` agent (plan/2026-11-20b §4). JSON in, JSON out, no model.

    {"op": "brief", "scene": {packet, genre, style_note}, "clip": {...}}  -> {"scene": str, "clip": str, "cards": [...]}
    {"op": "brief", "scene": {...}}                                      -> {"scene": str}       (once per scene)
    {"op": "check", "direction": {...}, "clip": {...}}                    -> {"faults": [str]}
    {"op": "assemble", "direction": {...}, "clip": {...}, "repaired": b}  -> {"sections", "prose", "checks"}

`clip` is what `facts.clip_facts` builds from the shot producer's rows. A system calls the agent between `brief` and
`check`, gives a failed answer ONE repair with the faults, and writes no prompt when the faults remain (D3).
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.video_prompt import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "brief":
        out: dict[str, Any] = {"scene": logic.scene_brief(payload["scene"])} if payload.get("scene") else {}
        if payload.get("clip"):
            out |= {"clip": logic.clip_brief(payload["clip"]), "cards": logic.cards_for(payload["clip"])}
        return out
    if op == "check":
        return {"faults": logic.gates(payload["direction"], payload["clip"])}
    if op == "assemble":
        return logic.assemble(payload["direction"], payload["clip"], repaired=bool(payload.get("repaired")))
    raise ValueError(f"unknown op {op!r}")
