"""Typed seams of the chat_answerer agent."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    persona: str = ""  # who is speaking: "You are <the lead>: <their style>"; empty = no persona
    history: str = ""  # the recent chat, as "speaker: text" lines
    shot_list: str  # the scene as the kernel describes it, AFTER this turn
    message: str  # what the person just wrote
    turn: list[str]  # the facts of the turn, one per line; the last thing the model reads before it writes


class Output(BaseModel):
    text: str
