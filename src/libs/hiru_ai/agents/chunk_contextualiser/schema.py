"""Typed seams of the chunk_contextualiser agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Passage(BaseModel):
    ord: int
    heading: str
    content: str


class Input(BaseModel):
    filename: str
    role: Literal["bible", "script", "canon_index", "outline", "notes", "other"]
    overview: str  # the document's text; the agent reads its first 4000 characters
    passages: list[Passage]  # one batch of at most 20, in order


class Header(BaseModel):
    ord: int
    header: str


class Output(BaseModel):
    headers: list[Header]
