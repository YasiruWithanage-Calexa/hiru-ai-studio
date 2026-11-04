"""Typed seams of the advisor agent."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    charter: str  # the advisor's style, from their persona
    summary: str  # what the lead changed
    scene_text: str  # the shot list after the changes


class Output(BaseModel):
    agrees: bool
    view: str
