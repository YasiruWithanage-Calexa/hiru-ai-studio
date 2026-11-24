"""Typed seams of the views_writer agent (plan/2026-11-24)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Place(BaseModel):
    name: str
    look: str = ""  # the card's look


class Input(BaseModel):
    place: Place  # the location the sheet is for
    spots: list[Place] = []  # its spots
    within: list[Place] = []  # other places that stand in it in the scenes set there (a food cart, a parked bus)
    geographies: list[str] = []  # how the Scene boards of the scenes set there laid the place out
    scenes: list[str] = []  # those scenes' headings and times of day


class View(BaseModel):
    name: str = Field(description="Two or three words: Front wide, Looking left, Looking right, Reverse, a detail.")
    what: str = Field(description="One or two sentences: where the camera stands, which way it looks, what is in the "
                                  "picture and on which side of the frame.")


class Output(BaseModel):
    layout: str = Field(description="The place as one connected layout: where each thing stands relative to the "
                                    "others, in one paragraph.")
    light: str = Field(description="The light and weather the scenes here share, in one sentence.")
    views: list[View] = Field(description="Exactly six views, in the order given in the prompt.")
