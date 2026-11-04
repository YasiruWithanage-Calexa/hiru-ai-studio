"""Typed seams of the adam_reviser agent (plan/2026-11-04b §5.2, §5.4).

The Input is the plan so far and the notes to act on (`contracts.adam.screening.ScreenInput` plus `notes`); the
Output is the wire shape `RevisionWire`: a list of operations. `Output.apply(moments, cards)` gives the plan after them.
"""
from __future__ import annotations

from contracts.adam.screening import RevisionWire, ScreenInput


class Input(ScreenInput):
    notes: list[str]  # the critics' notes, one line each, most severe first (`contracts.adam.screening.note_line`)


class Output(RevisionWire):
    """What the reviser answers: see `RevisionWire`."""
