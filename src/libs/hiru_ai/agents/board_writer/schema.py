"""Typed seams of the board_writer agent (the lab's `SCHEMA` plus each panel's people and their state)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Picture(BaseModel):
    mime: str = "image/png"
    b64: str


class Input(BaseModel):
    message: str  # `contracts.board.writer_message`: the scene, every painted shot's plan, the mannequin note
    pictures: list[Picture] = []  # the reference pictures named in the message, in order (sent at detail low)


class Person(BaseModel):
    name: str
    state: str = Field(description="Their state at the opening of the shot (eyes closed, still, crying ...); "
                                   "empty when nothing is notable. Never drawn on the board.")
    left_hand: str = Field(default="", description=(
        "What the left hand holds or does as the shot opens (\"the clay phone\", \"empty, at her side\"); a bag "
        "on the left forearm or shoulder is said here too."))
    right_hand: str = Field(default="", description="What the right hand holds or does, as `left_hand`.")


class Prop(BaseModel):
    """plan/2026-11-23c: a prop the panel shows, painted as a white clay stand-in."""

    name: str = Field(description="The prop's name, exactly as the scene's `props` name it.")
    held_by: str = Field(default="", description="Who holds or carries it; empty when it rests on something.")
    hand: str = Field(default="", description="left, right or both; empty when it is worn or resting.")
    rests_on: str = Field(default="", description="The surface it rests on when nobody holds it.")
    frame_side: str = Field(default="", description="left, right or centre of the picture.")


class Panel(BaseModel):
    shot: int = Field(description="The shot's number.")
    zone: str = Field(description="The staging zone or spot the camera is in.")
    camera: str = Field(description="Where the camera stands, which way it looks, size.")
    background: str = Field(description="What is behind the people, and on which side.")
    picture: str = Field(description="2-4 sentences: the opening picture of the shot.")
    people: list[Person] = Field(description="Every person the panel shows, with their state and both hands.")
    props: list[Prop] = Field(default_factory=list, description="Every prop the panel shows: who holds it in which "
                                                                "hand, or what it rests on.")
    view: int = Field(default=0, description="The number of the place's view its background comes from (the "
                                             "place's `views`); 0 when the place has no views or none fits.")


class GroundMark(BaseModel):
    """plan/2026-11-24d: one still person's spot on one stretch (`contracts.marks.GroundMark`, checked in code)."""

    stretch: int = Field(description="The stretch's number, from the scene's `stretches`.")
    who: str = Field(description="The person's name, one of the stretch's `still`.")
    spot: str = Field(description=("What they stand (or sit) on, beside which landmark of the place, on which side "
                                   "of it and how far from it, the landmarks named as the place's pictures show "
                                   "them."))
    apart: str = Field(default="", description="The gap to the person before them in `still`, and on which side; "
                                               "empty for the first.")


class Output(BaseModel):
    world: str
    geography: str
    panels: list[Panel]
    conflicts: list[str]
    marks: list[GroundMark] = Field(default_factory=list, description=(
        "One ground spot per stretch and per still person (plan/2026-11-24d); empty when the scene has no "
        "`stretches`."))
