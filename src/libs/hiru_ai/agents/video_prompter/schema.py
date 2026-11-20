"""Typed seams of the video_prompter agent (plan/2026-11-20b §3). The agent writes DIRECTION only; the `video_prompt`
step builds what it is given (the brief), checks its answer (the gates) and writes the prompt (the assembly), so every
fact stays code's: the lines' words, the opening frame, the join, the hands, the format.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Step(BaseModel):
    """One beat of the clip, in order."""

    kind: Literal["action", "line"]
    text: str = Field(description="An action step: what happens, one or two sentences. A line step: empty.")
    line_id: str = Field(description="A line step: the line's id as the brief gives it. An action step: empty.")
    to: str = Field(description="A line step: who it is said to ('herself' when muttered). An action step: empty.")
    how: str = Field(description="A line step: the delivery, a phrase. An action step: empty.")
    listener: str = Field(description="A line step: what the listener does. Empty when nobody else is there.")


class Direction(BaseModel):
    """The agent's answer."""

    situation: str
    people: str
    flow: list[Step]
    camera: str
    sound: str


class Input(BaseModel):
    """What the step built for one clip."""

    scene: str  # the <scene> part: identical for every clip of the scene, sent as its own message first (it caches)
    clip: str  # the <clip> part
    cards: list[str] = Field(default_factory=list)  # the craft cards code picked for this clip, by name (prompts/cards)
    repair: list[str] = Field(default_factory=list)  # the first answer's faults, on the repair call only
    previous: str = ""  # the first answer as JSON, on the repair call only
