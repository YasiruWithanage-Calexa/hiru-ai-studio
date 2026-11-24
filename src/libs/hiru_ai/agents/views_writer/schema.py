"""Typed seams of the views_writer agent (plan/2026-11-24; plan/2026-11-24c: lab/place_views r2's `Written`)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Place(BaseModel):
    name: str
    look: str = ""  # the card's look


class Picture(BaseModel):
    mime: str = "image/jpeg"
    b64: str


class GivenAnswers(BaseModel):
    """A person's three answers, set on the canon page before writing (plan/2026-11-24c D1): they win."""

    sides: Literal["outside", "inside", "both"]
    moves: bool
    size: Literal["small", "room", "long"]


class Input(BaseModel):
    place: Place  # the place (or vehicle) the sheet is for
    vehicle: bool = False  # a vehicle card (canon class `vehicle`)
    spots: list[Place] = []  # its spots
    within: list[Place] = []  # other fixed places that stand in it in the scenes set there (a kiosk, its own set)
    comes_and_goes: list[Place] = []  # vehicles in those scenes: they have sheets of their own; their spaces stay empty
    geographies: list[str] = []  # how the Scene boards of the scenes set there laid the place out
    scenes: list[str] = []  # those scenes as text (lab `scene_text`: "Scene n — heading: the script")
    picture: Picture | None = None  # the place's plate, shrunk (the lab gave it to the writer)
    answers: GivenAnswers | None = None  # a person's answers, when given
    findings: list[str] = []  # the code checks' findings on a first answer: the one re-ask (§2.3)


class Answers(BaseModel):
    sides: Literal["outside", "inside", "both"]
    moves: bool = Field(description="true only for a vehicle: a car, a three-wheeler, a bus, a boat")
    size: Literal["small", "room", "long"]
    why: str = Field(description="one sentence: why these answers")


class View(BaseModel):
    slot: str = Field(description="the template slot name, exactly")
    camera: str = Field(description="where the camera stands and which way it looks, in one sentence")
    sees: str = Field(description="what the camera sees and on which side of the picture (left, centre, right, "
                                  "near, far), in one or two sentences")


class Output(BaseModel):
    answers: Answers
    layout: str = Field(description="the place as ONE connected layout: where each fixed thing stands relative to "
                                    "the others (left, right, behind, across), in two to four sentences")
    empty: list[str] = Field(description="each space of the place kept EMPTY because something that comes and goes "
                                         "stands there in the scenes (a vehicle, a cart, a stall packed away at "
                                         "night): where it is and what it looks like empty; [] when there is none")
    light: str = Field(default="", description="The light and weather the scenes here share, in one sentence. It is "
                                               "not painted into the sheet.")
    views: list[View]
