"""Typed seams of the canon_extractor agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Document(BaseModel):
    filename: str
    role: str
    text: str


class Counted(BaseModel):
    name: str
    count: int  # lines spoken (a speaker) or scenes headed (a place)


class Input(BaseModel):
    documents: list[Document]  # the extracted text of the ready documents
    speakers: list[Counted] = []  # speakers found in the scripts, by the rules
    places: list[Counted] = []  # places found in the scene headings, by the rules


class Card(BaseModel):
    summary: str
    age: str
    gender: str
    appearance: str
    wardrobe: str
    voice: str
    accent: str
    look: str
    details: str
    notes: str


class Entity(BaseModel):
    kind: Literal["character", "location", "prop"]
    name: str
    code: str
    aliases: list[str]
    core: bool
    card: Card


class Output(BaseModel):
    entities: list[Entity]
