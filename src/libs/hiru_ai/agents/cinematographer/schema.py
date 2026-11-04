"""Typed seams of the cinematographer agent (a specialist on the director's board)."""
from __future__ import annotations

from pydantic import BaseModel

from contracts.directorops import Op


class Input(BaseModel):
    lead_charter: str = ""  # the board lead's persona; empty = a family teledrama audience
    scene_text: str  # the shot list the specialist sees
    shots: list[int] = []  # the shots its task names (empty = the whole scene)
    instruction: str = ""


class Output(BaseModel):
    ops: list[Op]
    note: str
