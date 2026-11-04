"""Typed seams of the craft_articulator agent."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    scenes: list[str]  # one short text per scene


class Output(BaseModel):
    problems: list[str]
