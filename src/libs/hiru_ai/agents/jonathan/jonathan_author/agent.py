"""jonathan_author hooks (plan/2026-11-06b §4.1).

The prompt is the cinematic lab's team prompt and its one worked example (`prompts/system.md`, the lab's text to the
letter: a test compares them while the lab exists). The user message is the context pack `jonathan_pack` built.

The answer is cleaned entry by entry and nothing else (`contracts.jonathan.scene.clean`): whether a line is missing, a
take too short or a person invented stays with the checks, which give the reviser the exact sentence. There is no
fallback: with no model the job fails clearly and names the classic planner.

The shape of a shot's camera design is not Python: it is the clip schema YAML the `serialize` step ships, the one the
DoP
fills, turned into a strict JSON schema at run time. So `output_schema()` returns JonathanWire's schema with that design
in place of the free `ir` object.
"""
from __future__ import annotations

from typing import Any

from contracts.jonathan.scene import clean
from contracts.jonathan.wire import JonathanWire
from hiru_ai.agents.jonathan.jonathan_author.schema import Input, Output
from hiru_ai.agents.jonathan.wire_schema import wire_schema

SCHEMA_NAME = "jonathan_plan"


def output_schema() -> dict[str, Any]:
    return wire_schema(JonathanWire, SCHEMA_NAME)


def user_message(inp: Input) -> str:
    return inp.pack


def finish(inp: Input, out: Output) -> Output:
    return Output.model_validate(clean(inp.scene, out).model_dump())
