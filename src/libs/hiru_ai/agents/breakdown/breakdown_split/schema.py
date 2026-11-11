"""Typed seams of the breakdown_split agent (plan/2026-11-11 §4): the message is built by `contracts.breakdown.run` (the
same
bytes for every caller); the answer is the wire shape `contracts.breakdown.schema.SplitW`, pointers only."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.breakdown.schema import SplitW as Output


class Input(BaseModel):
    message: str  # built by contracts.breakdown.run / inputs; uploaded text inside it is labelled data


__all__ = ["Input", "Output"]
