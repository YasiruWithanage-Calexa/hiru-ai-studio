"""Typed seams of the architect agent."""
from __future__ import annotations

from pydantic import BaseModel


class Block(BaseModel):
    kind: str
    speaker: str = ""
    text: str = ""


class Scene(BaseModel):
    number: int
    heading: str  # the scene heading as written
    blocks: list[Block]


class Input(BaseModel):
    number: int  # the episode's
    title: str = ""
    scenes: list[Scene]


class SceneTitle(BaseModel):
    number: int
    title: str


class Output(BaseModel):
    synopsis: str
    scenes: list[SceneTitle]
