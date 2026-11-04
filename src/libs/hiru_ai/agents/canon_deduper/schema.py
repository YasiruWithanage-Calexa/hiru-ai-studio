"""Typed seams of the canon_deduper agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Kind = Literal["character", "location", "prop"]


class Candidate(BaseModel):
    kind: Kind
    name: str
    code: str
    aliases: list[str]
    summary: str


class Input(BaseModel):
    candidates: list[Candidate]


class Group(BaseModel):
    kind: Kind
    keep: str
    same_as_keep: list[str]


class Output(BaseModel):
    groups: list[Group]
