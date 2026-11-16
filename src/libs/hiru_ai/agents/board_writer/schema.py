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


class Panel(BaseModel):
    shot: int = Field(description="The shot's number.")
    zone: str = Field(description="The staging zone or spot the camera is in.")
    camera: str = Field(description="Where the camera stands, which way it looks, size.")
    background: str = Field(description="What is behind the people, and on which side.")
    picture: str = Field(description="2-4 sentences: the opening picture of the shot.")
    people: list[Person] = Field(description="Every person the panel shows, with their state.")


class Output(BaseModel):
    world: str
    geography: str
    panels: list[Panel]
    conflicts: list[str]
