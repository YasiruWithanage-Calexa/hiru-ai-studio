"""Typed seams of the shot_intent agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Input(BaseModel):
    production: str  # the frozen production block: title and cast (identical for every scene of a job: prompt cache)
    scene: str  # the scene prompt: the reading, the staging map, and each shot's script, cast and timeline


class ShotIntent(BaseModel):
    number: int
    purpose: str
    what_we_see: str
    emotional_beat: str
    on_screen: list[str]
    heard_only: list[str]
    voice_source: Literal["", "phone", "radio", "television", "speaker", "off_screen"]
    split_after: int
    split_reason: str


class Coverage(BaseModel):
    axis: str
    motif: str
    progression: str


class Output(BaseModel):
    shots: list[ShotIntent]
    coverage: Coverage
