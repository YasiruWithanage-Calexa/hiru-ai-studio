"""Typed seams of the adam_fixer agent (plan/2026-11-05 T3).

The Input is ONE problem and the part of the plan around it, not the whole plan; the Output is the reviser's wire shape
(`RevisionWire`: operations and dispositions), so `apply`, `check_revision` and the notes ledger are reused.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import Moment, SceneScript, ShotCard
from contracts.adam.problems import Problem
from contracts.adam.screening import RevisionWire


class Input(BaseModel):
    scene: SceneScript
    concept: str  # the treatment's concept: what the one take was for, which a fix keeps
    problem: Problem
    moments: list[Moment]  # the moments of the cards around the problem (a creative fix may need them all)
    cards: list[ShotCard]  # the cards around the problem, with their numbers in the whole plan
    report: str = ""  # what code found about this problem, as lines
    earlier: str = ""  # why the last rung's fix was refused, when this is the second rung; empty on the first


class Output(RevisionWire):
    """What the fixer answers: see `RevisionWire`. Its one disposition answers the problem by its id."""
