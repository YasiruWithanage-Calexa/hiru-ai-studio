"""Typed seams of the zora_conductor agent (plan/2026-11-13 §3.9). The wire shape is `contracts.zora.wire`."""
from __future__ import annotations

from pydantic import BaseModel

from contracts.zora.wire import ConductorAnswer


class Input(BaseModel):
    scene: str  # the scene as clip heads (`Coverage.render(only=set())`)
    message: str  # the person's latest message
    transcript: list[str] = []  # "speaker: text", oldest first; the last few are sent
    rejected: list[str] = []  # what the person pressed Reject on in this thread: never offered again
    # what was wrong with the answer before, when this is the one retry (appended LAST: the cached prefix is unmoved)
    problems: list[str] = []
    place: str = ""  # what the turn is about, for the production memory (`memory_scope`)
    people: list[str] = []


class Output(ConductorAnswer):
    """The lane, the person's own changes as operations, the author's tasks (`ConductorAnswer`)."""
