"""The echo system's state."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    message: str
    result: dict[str, Any]
