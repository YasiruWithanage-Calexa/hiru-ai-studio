"""Typed seams of the conductor agent."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

from contracts.directorops import Op


class Input(BaseModel):
    plan_text: str  # the shot list as the kernel describes it
    message: str  # what the person just wrote
    history: str = ""  # the recent chat, as "speaker: text" lines
    memory: list[str] = []  # the production's remembered rules
    said: str = ""  # what the person wrote, here and earlier: the only words a dialogue change may use
    again: bool = False  # the first answer would have changed nothing: ask once more


class Task(BaseModel):
    agent: Literal["cinematography", "timing", "sound", "continuity"]
    shots: list[int]
    instruction: str


class Cannot(BaseModel):
    request: str
    reason: str
    route: str


class Translate(BaseModel):
    language: str
    code: str
    style: str
    shots: list[int]


class Output(BaseModel):
    lane: Literal["chat", "edit", "craft", "reshape", "options", "cannot", "translate"]
    ops: list[Op]
    tasks: list[Task]
    memory: list[str]
    cannot: Cannot | None
    translate: Translate | None

    @model_validator(mode="before")
    @classmethod
    def _absent_is_none(cls, value: Any) -> Any:
        """The engine read an answer with no `cannot` or `translate` as having none (the wire schema still asks for
        both: this only keeps a reply that left them out from being thrown away)."""
        if isinstance(value, dict):
            return {"cannot": None, "translate": None, **value}
        return value
