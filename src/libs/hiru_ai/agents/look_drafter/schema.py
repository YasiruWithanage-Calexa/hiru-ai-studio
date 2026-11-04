"""Typed seams of the look_drafter agent."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Character(BaseModel):
    name: str
    card: dict[str, str] = {}  # the canon card's text fields


class Input(BaseModel):
    episodes: int
    characters: list[Character]


class Look(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    character: str
    name: str
    from_: int = Field(alias="from")  # `from` is a Python keyword; on the wire it is "from"
    to: int
    outfit: str
    hair: str
    makeup: str
    accessories: str


class Output(BaseModel):
    looks: list[Look]
