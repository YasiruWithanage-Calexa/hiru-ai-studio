"""Typed seams of the shot_critic agent."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    scene_number: int
    heading: str
    context: str = ""  # what surrounds the scene (the producer's context block)
    plan: str = ""  # the scene's coverage plan as text
    drafts: list[str]  # each shot's design as the producer writes it for review
    free: list[str] = []  # what the free staging checks already found


class Output(BaseModel):
    acceptable: bool
    notes: list[str]
