"""Typed seams of the zora_author agent (plan/2026-11-13 §3.6, §3.9). The wire shape is `contracts.zora.wire`.

The caller renders the scene and the tasks (it holds the coverage and its handles); the agent only lays them out, in the
cache order the lab used: the conversation, the scene, what is done, the tasks, then the per-call asks (variants,
faults).
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.zora.wire import AuthorAnswer


class TaskView(BaseModel):
    instruction: str
    writes: list[str]  # the kinds of change it may make (picture, camera, timing, sound, light, order)
    on: str  # "any shot" or "S03, S04"


class Input(BaseModel):
    scene: str  # the scene, the tasks' clips in full (a whole-scene task: every clip brief)
    transcript: list[str] = []
    done: list[str] = []  # "ALREADY DONE THIS TURN"
    tasks: list[TaskView]
    variants: int = 0  # > 0 only on the options lane
    faults: list[str] = []  # a repair pass: the exact problems the checks found after the edit
    # what the call is about, for the production memory (`memory_scope`)
    place: str = ""
    people: list[str] = []


class Output(AuthorAnswer):
    """Notes for the director, the operations, questions, and variants (`AuthorAnswer`)."""
