"""Typed seams of the beat_finder agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from contracts.shotplan import Item


class Input(BaseModel):
    items: list[Item]  # the scene's blocks, in order


class Reading(BaseModel):
    block: int
    screen: Literal["move", "act", "with_line", "info", "inner"]
    events: int


class Output(BaseModel):
    blocks: list[Reading]
