"""Typed seams of the breakdown_canon agent (plan/2026-11-12c): the message is built by `contracts.canon_refine` (the
same bytes for every caller); the answer is `contracts.canon_refine.Answer`, which code checks
(`contracts.canon_refine.check`) before anything is stored."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.canon_refine import Answer as Output


class Input(BaseModel):
    message: str  # built by contracts.canon_refine.message; the documents' text inside it is labelled data


__all__ = ["Input", "Output"]
