"""shot_writer hooks. Ported from `shot_producer/engine/shots.py` (`design_by_model`).

The shape of one shot's design is not Python: it is the clip schema YAML the `serialize` step ships (the rig, lens and
movement rules a video model must obey), turned into a strict JSON schema at run time. So `output_schema()` returns that
schema and `Output` only holds the answer as the engine did: a list of raw entries, matched by shot number in code.

The production block and the scene tail are rendered by the producer's system from the stored rows (the `serialize`
step's shot model). A partial answer is kept and the missing shots are asked for once more by the system; whatever is
still missing falls back to the rules, so there is no fallback here.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.agents.shot_writer.schema import Input
from hiru_ai.steps.serialize.schema import get_schema

SCHEMA_NAME = "scene_design"


def output_schema() -> dict[str, Any]:
    return {"title": SCHEMA_NAME, **get_schema().scene_schema()}


def user_message(inp: Input) -> str:
    return inp.production + "\n\n" + inp.scene
