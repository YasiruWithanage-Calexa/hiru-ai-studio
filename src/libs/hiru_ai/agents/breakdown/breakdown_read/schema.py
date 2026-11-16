"""Typed seams of the breakdown_read agent (plan/2026-11-15): the message is built by `contracts.breakdown.reading` (the
same bytes for every caller); the answer is `contracts.breakdown.reading.ReadingW`, every fact with its quote."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.breakdown.reading import ReadingW as Output


class Input(BaseModel):
    message: str  # contracts.breakdown.reading.numbered() (or its repair message): the document as labelled data


__all__ = ["Input", "Output"]
