"""The david_shot_planner system's state. Plain data only (JSON-able): the scenes still to plan, what was written."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    todo: list[dict[str, Any]]  # {"label", "scene", "lines"} of each scene to plan, in order
    skipped: int  # approved scenes and scenes with no script
    carried: dict[str, Any]  # totals from earlier deliveries of this hop
    written: int
    shot_count: int
    reused: int  # scenes whose input is unchanged since David planned them: left as they were
    failed: list[dict[str, Any]]  # {"scene_id", "label", "reason"} of scenes David could not plan (left as they were)
    continuity: list[str]  # overruns, seams and look changes, as lines a person reads
    episodes: dict[str, int]  # episode number -> seconds of shots planned
    planned: list[str]  # ids of the scenes written in this delivery
    left: list[str]  # ids of the scenes the time budget left for the next delivery
    result: dict[str, Any]
