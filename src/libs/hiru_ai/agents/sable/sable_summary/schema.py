"""Typed seams of the sable_summary agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Input(BaseModel):
    summary: str = ""  # the thread's summary so far ("" = none yet)
    messages: str  # the older messages to fold in, as "speaker: text" lines, oldest first


class Output(BaseModel):
    summary: str = Field(description="The whole thread so far, in at most 12 short lines")
