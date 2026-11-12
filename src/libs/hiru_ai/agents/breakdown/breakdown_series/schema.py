"""Typed seams of the breakdown_series agent (plan/2026-11-12b): the message is built by `contracts.breakdown.series`
(the same bytes for every caller); the answer is the wire shape `contracts.breakdown.schema.SeriesW`, which code checks
(`contracts.breakdown.series.check`) before anything is stored."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.breakdown.schema import SeriesW as Output


class Input(BaseModel):
    message: str  # built by contracts.breakdown.series.message; uploaded text inside it is labelled data


__all__ = ["Input", "Output"]
