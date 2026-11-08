"""The sable_chat system's state. Plain data only; the turn's objects live in the run (`turn.Turn`)."""
from __future__ import annotations

from typing import TypedDict


class State(TypedDict, total=False):
    done: bool
