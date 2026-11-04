"""Typed seams of the emotion_critic agent."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator


class Input(BaseModel):
    listing: str
    shot_list: str
    reading: str = ""
    staging: str = ""
    found: list[str] = []


class Note(BaseModel):
    note: str
    severity: Literal[1, 2, 3]

    @model_validator(mode="before")
    @classmethod
    def _tolerant(cls, value: Any) -> Any:
        """What the engine accepted from a reviewer: a plain string is a note of severity 2, and so is any other
        severity. (The wire schema is unchanged: the model is still held to a note and a 1, 2 or 3.)"""
        if isinstance(value, str):
            return {"note": value, "severity": 2}
        if isinstance(value, dict) and value.get("severity") not in (1, 2, 3):
            return {**value, "severity": 2}
        return value


class Output(BaseModel):
    acceptable: bool
    notes: list[Note]
