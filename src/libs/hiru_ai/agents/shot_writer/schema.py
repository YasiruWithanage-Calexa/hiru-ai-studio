"""Typed seams of the shot_writer agent."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Input(BaseModel):
    production: str  # the frozen production block (title, cast, style, technique palette): identical for a whole job
    scene: str  # the scene tail: the scene, the coverage plan, the opening continuity and each shot to design


class Output(BaseModel):
    """One raw design per shot, matched back BY NUMBER in code. Each entry follows the clip schema (see agent.py)."""

    shots: list[dict[str, Any]]
