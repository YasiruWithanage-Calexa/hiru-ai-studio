"""What goes into the director_board panel and what comes out of it. The members know nothing of this: the panel maps
a task into each agent's own `Input` and each agent's `Output` back into a `Result`."""
from __future__ import annotations

from typing import Any, TypedDict


class Brief(TypedDict, total=False):
    scene_text: str  # the shot list the specialists see
    lead_charter: str  # the board lead's persona; empty = a family teledrama audience


class Task(TypedDict, total=False):
    agent: str  # the craft: a member's `name` (cinematography, timing, sound, continuity)
    shots: list[int]  # the shots it may change; empty = the whole scene
    instruction: str


class Review(TypedDict):
    name: str  # the advisor's name, as heard in the reply
    charter: str  # the advisor's style
    summary: str  # what the lead changed


class Advice(TypedDict):
    who: str
    text: str


Ops = list[dict[str, Any]]
