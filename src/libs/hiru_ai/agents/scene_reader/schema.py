"""Typed seams of the scene_reader agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from contracts.shotplan import Item


class Character(BaseModel):
    name: str
    summary: str = ""


class Context(BaseModel):
    """What surrounds the scene. Everything is optional: a reading is made from whatever is known."""

    heading: str = ""
    note: str = ""  # the director's note on the scene
    episode_title: str = ""
    synopsis: str = ""
    before: str = ""  # the scene before: its heading and title
    after: str = ""
    characters: list[Character] = []


class Input(BaseModel):
    items: list[Item]
    speaker_names: dict[str, str] = {}
    context: Context = Context()


class Value(BaseModel):
    start: str
    end: str


class Want(BaseModel):
    character: str
    verb: str


class Unit(BaseModel):
    from_block: int
    to_block: int
    wants: list[Want]
    turn_block: int | None


class Subtext(BaseModel):
    block: int
    who: str
    behaviour: str
    narration_only: bool
    reason: str


class Breath(BaseModel):
    after_block: int
    kind: Literal["reaction", "transition", "atmosphere", "button"]
    who: str
    seconds: float
    priority: Literal[1, 2, 3]
    why: str


class Output(BaseModel):
    about: str
    value: Value
    tone: str
    units: list[Unit]
    subtext: list[Subtext]
    breath: list[Breath]
    ending: str
