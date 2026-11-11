"""Typed seams of the prompt_writer agent. It knows nothing about the system that uses it: any system that has a
prompt in sections can send them (`contracts.prompt_polish.request`) and apply the answer
(`contracts.prompt_polish.merge`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Section(BaseModel):
    key: str
    title: str
    text: str  # the code's words: complete and correct, often flat
    keep: list[str] = Field(default_factory=list)  # words the rewrite must still contain, as they are


class Input(BaseModel):
    kind: Literal["first_frame", "video"]  # a still for the image model, or a clip for the video model
    sections: list[Section]


class Written(BaseModel):
    key: str = Field(description="The key of the section this rewrites, exactly as sent.")
    text: str = Field(description="The section rewritten. Every KEEP word appears in it, as given.")


class Output(BaseModel):
    sections: list[Written] = Field(description="One entry per section sent, in the same order.")
