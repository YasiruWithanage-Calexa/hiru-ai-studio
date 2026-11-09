"""Typed seams of the sable_agent agent (plan/2026-11-08 §4.3). It knows nothing about the panel that shows it."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Input(BaseModel):
    message: str  # what the person just wrote
    history: str = ""  # the recent chat, as "speaker: text" lines (the last 12 messages whole)
    summary: str = ""  # what the older part of the thread said, summarised once and stored on the thread (§4.5)
    scene: str = ""  # the scene in view, as a person says it ("E1S2"); "" = none (Sable is production-wide)
    role: str = ""  # the person's role in the production ("director", "reviewer", ...): what they may accept
    mentioned: str = ""  # what the person pointed at with @, one line each, resolved by the API ("" = nothing)
    can_stage: bool = True  # False: the person cannot accept a card (a viewer, D8), so none is proposed
    memory_scope: dict[str, Any] = Field(default_factory=dict)  # {place, people, episode} of the scene in view


class Output(BaseModel):
    text: str = Field(description="The reply to the person, in plain English")
    handoff_scene: str = Field(description='The scene to open for an edit, like "E1S2"; "" when no edit was asked')
    handoff_request: str = Field(description="The person's edit request, as they would send it in that scene's "
                                             "chat; \"\" when no edit was asked")
