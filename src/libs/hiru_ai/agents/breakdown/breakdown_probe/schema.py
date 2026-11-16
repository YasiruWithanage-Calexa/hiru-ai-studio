"""Typed seams of the breakdown_probe agent (plan/2026-11-15): the message is built by `contracts.breakdown.reading`
(the same bytes for every caller); the answer is `contracts.breakdown.reading.ProbeW`."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.breakdown.reading import ProbeW as Output


class Input(BaseModel):
    message: str  # contracts.breakdown.reading.numbered(): the document inside labelled tags, its lines numbered


__all__ = ["Input", "Output"]
