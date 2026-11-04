"""The frame_render system's state. Plain data only (JSON-able)."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    result: dict[str, Any]  # frames: the counts; a sheet: {"status": ...}
