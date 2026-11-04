"""Typed seams of the scene_planner agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from contracts.shotplan import Item


class Input(BaseModel):
    items: list[Item]
    speaker_names: dict[str, str] = {}
    heading: str
    envelope_s: int
    allowed: list[int] = [4, 6, 8]  # the shot lengths the plan may use
    context: str = ""  # what surrounds the scene, as text (episode synopsis, neighbours, the director's note)
    reading: str = ""  # the scene's reading as text
    notes: list[str] = []  # problems a reviewer found in the previous plan


class Shot(BaseModel):
    start: int
    end: int
    framing: Literal["WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT"]
    title: str
    sound_mode: Literal["dialogue", "voiceover", "sung", "ambient", "music_only", "silent"]
    duration: Literal[4, 6, 8]
    camera_link: Literal["cut", "continuous", "match"]


class Output(BaseModel):
    shots: list[Shot]
