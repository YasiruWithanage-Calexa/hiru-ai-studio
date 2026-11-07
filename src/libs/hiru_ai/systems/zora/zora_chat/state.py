"""The zora_chat system's state. Plain data only; the turn's objects (kernel, ledger material) live in the run."""
from __future__ import annotations

from typing import TypedDict


class State(TypedDict, total=False):
    route: str  # read: "" | "gone"; in_code: undo | redo | confirm | ""; conduct: the lane
