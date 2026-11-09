"""Typed seams of the stager agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from contracts.shotplan import Item


class Input(BaseModel):
    items: list[Item]
    speaker_names: dict[str, str] = {}  # speaker id -> the name the listing shows
    reading_text: str = ""  # the scene's reading as text (SceneReading.text())
    place: str = ""  # the location's card


Posture = Literal["", "standing", "sitting", "kneeling", "crouching", "lying", "walking", "running"]


class Mark(BaseModel):
    block: int
    who: str
    zone: str
    facing: Literal["", "left", "right", "camera", "away"]
    frame_side: Literal["", "left", "right", "centre"]
    holding: str
    # plan/2026-11-09: the state ledger. Every field is required (strict mode); "" is allowed.
    posture: Posture
    left_hand: str
    right_hand: str
    condition: str
    wearing: str


class PropMark(BaseModel):
    """A prop in no hand, from this block on."""

    block: int
    prop: str
    where: str
    state: str


class Output(BaseModel):
    zones: list[str]
    marks: list[Mark]
    props: list[PropMark]
