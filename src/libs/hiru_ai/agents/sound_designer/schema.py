"""Typed seams of the sound_designer agent (a specialist on the director's board)."""
from __future__ import annotations

from pydantic import BaseModel

from contracts.directorops import Op


class Input(BaseModel):
    lead_charter: str = ""
    scene_text: str
    shots: list[int] = []
    instruction: str = ""


class Output(BaseModel):
    ops: list[Op]
    note: str
