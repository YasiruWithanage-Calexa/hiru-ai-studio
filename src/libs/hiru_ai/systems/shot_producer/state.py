"""The shot_producer system's state. Plain data only (JSON-able); the scene inputs live inside the run."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    result: dict[str, Any]
