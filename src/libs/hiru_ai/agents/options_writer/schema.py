"""Typed seams of the options_writer agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from contracts.directorops import Op


class Input(BaseModel):
    lead_charter: str = ""  # the lead's persona; empty = a family teledrama audience
    memory: list[str] = []
    history: str = ""
    shot_list: str  # the shot list as the kernel describes it
    message: str


class Option(BaseModel):
    label: str
    detail: str
    ops: list[Op]
    prompt: str
    intent: Literal["", "dialogue.si", "dialogue.ta", "dialogue.hi", "dialogue.en", "shot.framing"]


class Output(BaseModel):
    question: str
    options: list[Option]
