"""The director_chat system's state. Plain data only; the turn's objects (kernel, turn state) live in the run."""
from __future__ import annotations

from typing import TypedDict


class State(TypedDict, total=False):
    route: str  # which branch of the turn runs: confirm | translate | reshape | edit | follow | options | none
