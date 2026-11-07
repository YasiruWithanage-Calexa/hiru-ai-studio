"""Typed seams of the zora_author agent (plan/2026-11-06e §4.5). The wire shape is `contracts.zora.wire`.

The caller renders the plan and the tasks (it holds the kernel and its handles); the agent only lays them out, in the
cache order the lab used: the conversation, the plan, what is done, the tasks, then the per-call asks (variants,
faults).
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.zora.wire import AuthorAnswer


class TaskView(BaseModel):
    instruction: str
    allowed: list[str]  # the effects it may write
    on: str  # "any shot" or "S03, S04"
    must: list[str]  # the effects it must change (checked against the diff)


class Input(BaseModel):
    plan: str  # the addressable plan, scoped to the tasks' shots (the rest one line each)
    transcript: list[str] = []
    done: list[str] = []  # "ALREADY DONE THIS TURN" (Nova finding 2)
    tasks: list[TaskView]
    variants: int = 0  # > 0 only on the options lane
    faults: list[str] = []  # a repair pass: the exact problems the planner's checks found after the edit
    # what the call is about, for the production memory (`memory_scope`)
    place: str = ""
    people: list[str] = []


class Output(AuthorAnswer):
    """Notes for the director, the operations, questions, and variants (`AuthorAnswer`)."""
