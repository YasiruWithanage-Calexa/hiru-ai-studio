"""Typed seams of the zora_conductor agent (plan/2026-11-06e §4.4). The wire shape is `contracts.zora.wire`."""
from __future__ import annotations

from pydantic import BaseModel

from contracts.zora.wire import ConductorAnswer


class Input(BaseModel):
    plan: str  # the scene's plan, addressable (`contracts.zora.render.addressable`)
    message: str  # the person's latest message
    transcript: list[str] = []  # "speaker: text", oldest first; the last few are sent
    # what was wrong with the answer before, when this is the one retry (appended LAST: the cached prefix is unmoved)
    problems: list[str] = []


class Output(ConductorAnswer):
    """The lane, the person's own changes as operations, the author's tasks (`ConductorAnswer`)."""
