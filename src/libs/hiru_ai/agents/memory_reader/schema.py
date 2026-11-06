"""Typed seams of the memory_reader agent. It knows nothing about the ingest job that uses it.

An entry is one thing a document says about HOW to make the drama. The `quote` is the document's own words, which
`steps/memory_check` finds in the text; an entry whose quote is not there is dropped.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Input(BaseModel):
    filename: str
    text: str  # the document's extracted text; the agent reads the first MAX_DOC_CHARS of it


class Entry(BaseModel):
    # open, lower case: series, tone, visual, camera, lighting, sound, music, edit, performance, language, rule, ...
    topic: str
    # "production", "place:<name>", "character:<name>", "episode:<n>", or "when:<the situation, in words>"
    applies_to: str
    says: str  # the direction in one plain sentence, for someone making the drama to follow
    quote: str  # the document's own words for it, copied exactly
    strength: Literal["must", "prefer", "fact"]  # a rule ("only", "never") · a style · a fact (genre, tagline, setting)


class Output(BaseModel):
    entries: list[Entry]
