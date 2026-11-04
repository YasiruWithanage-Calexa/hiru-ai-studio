"""Typed seams of the frame_inspector agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Input(BaseModel):
    image_b64: str  # the painted frame, base64
    mime: str = "image/png"
    seen: list[str]  # "Anudi: Sri Lankan woman, long dark hair ..." (who should be visible)
    unseen: list[str] = []  # who must NOT be visible (a voice on a phone)
    frame: str = ""  # the DoP's first frame: composition and subjects


class Output(BaseModel):
    main_people: int = Field(description="How many main people are visible.")
    unexpected_person: bool = Field(
        description="A main person is visible who matches someone who must NOT be seen.")
    matches: bool = Field(description="The frame shows what the expected first frame describes.")
    problems: list[str] = Field(description="At most two short differences from the expected frame.")
