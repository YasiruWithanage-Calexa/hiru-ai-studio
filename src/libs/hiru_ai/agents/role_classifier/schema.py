"""Typed seams of the role_classifier agent. It knows nothing about the ingest job that uses it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Input(BaseModel):
    filename: str
    text: str  # the document's extracted text; the agent reads a head-and-middle sample of it


class Output(BaseModel):
    role: Literal["bible", "script", "canon_index", "outline", "notes", "other"]
    confidence: float
    reason: str
