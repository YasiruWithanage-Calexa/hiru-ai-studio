"""Typed seams of the zora_reply agent (plan/2026-11-13 §3.6 Reply)."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    persona: str = ""  # who Zora is (a fixed sentence; the turn passes it)
    transcript: list[str] = []  # "speaker: text", oldest first (6, or 12 when the author worked)
    scene: str  # clip heads, with the clips the turn touched and the shots the message names in full
    message: str  # what the person just wrote, or "(they pressed Accept)"
    facts: list[str]  # what happened this turn, as plain sentences under their headers: the LAST thing read


class Output(BaseModel):
    text: str
