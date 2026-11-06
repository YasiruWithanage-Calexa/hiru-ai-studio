"""Typed seams of the story_reader agent. It knows nothing about the ingest job that uses it.

Everything that points into the text is a verbatim quote that code can find (`steps/story_check`), never an offset.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Input(BaseModel):
    filename: str
    text: str  # the document's extracted text; the agent reads the first MAX_DOC_CHARS of it


class SpokenLine(BaseModel):
    speaker: str  # as the text names them ("FATHER"; "Thaththe" stays as written)
    delivery: str  # "on the phone", "quietly", "": short English
    text: str  # the words, copied exactly, without quote marks


class Episode(BaseModel):
    number: int | None  # None when the text does not say (a lone scene)
    title: str
    starts_with: str  # the first ~8 words of the episode's story, copied exactly
    ends_with: str  # the last ~8 words, copied exactly
    duration_s: int | None
    kind: Literal["script", "synopsis"]  # people speaking and acting, or a summary of what happens
    spoken: list[SpokenLine]


class Person(BaseModel):
    name: str
    aliases: list[str]  # "Thaththe" for the father
    voice_only: bool  # heard (on a phone, off screen), never shown
    evidence: str  # a short quote that shows them


class Output(BaseModel):
    contains: list[Literal["bible", "script", "outline", "canon_index", "notes"]]  # every kind the document holds
    episodes: list[Episode]
    people: list[Person]
    ignore: list[str]  # quotes of text that is not story: page headers and footers, a props table spliced in
