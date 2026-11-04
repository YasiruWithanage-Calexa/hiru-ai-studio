"""Typed seams of the translator agent: the one agent that may write a spoken line."""
from __future__ import annotations

from pydantic import BaseModel


class Line(BaseModel):
    line_id: str
    speaker: str = ""
    delivery: str = ""
    text: str


class Input(BaseModel):
    language: str  # the target language's name ("Sinhala")
    code: str = ""  # its code when we can check the script ("si")
    style: str = ""  # "colloquial", "formal"...
    production: str = ""
    memory: list[str] = []  # the production's remembered rules
    lines: list[Line]  # at most 30 per call: the answer stays short enough to be exact


class Translated(BaseModel):
    line_id: str
    text: str


class Output(BaseModel):
    lines: list[Translated]
