"""Typed seams of the prose_writer agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CanonName(BaseModel):
    kind: str
    name: str


class Input(BaseModel):
    number: int | None  # None: a lone scene the document does not number
    title: str
    duration_s: int | None = None  # the episode's stated length, if it states one
    body: str  # the episode's prose
    canon: list[CanonName] = []


class Block(BaseModel):
    kind: Literal["action", "dialogue"]
    speaker: str
    delivery: str
    text: str


class Scene(BaseModel):
    int_ext: Literal["INT", "EXT", "INT/EXT", ""]
    location: str
    sub_location: str
    time_of_day: Literal["DAY", "NIGHT", "MORNING", "AFTERNOON", "EVENING", "DAWN", "DUSK", ""]
    seconds: int
    blocks: list[Block]


class Output(BaseModel):
    scenes: list[Scene]
