"""The script_split system's state. Plain data only (JSON-able): the scenes still to plan, what was written so far."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    todo: list[dict[str, Any]]  # {"label", "scene", "lines"} of each scene to plan, in order
    skipped: int  # approved scenes and scenes with no script
    carried: dict[str, Any]  # totals from earlier deliveries of this hop
    written: int
    shot_count: int
    issues: int
    continuity: list[str]
    episodes: dict[str, dict[str, int]]  # episode number -> what its scenes add up to
    left: list[str]  # ids of the scenes the time budget left for the next delivery
    result: dict[str, Any]
