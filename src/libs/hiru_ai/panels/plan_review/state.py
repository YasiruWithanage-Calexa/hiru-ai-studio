"""What goes into plan_review and what comes out. The critics and the planner know nothing of this: the panel maps the
brief into each agent's own `Input`."""
from __future__ import annotations

from typing import Any, TypedDict


class Brief(TypedDict, total=False):
    items: list[Any]  # the scene's kernel items (contracts.shotplan.Item), with the reading's time
    reading: Any  # contracts.reading.SceneReading | None
    staging: Any  # contracts.stagemap.SceneStaging | None
    cast: list[str]  # the people's names
    listing: str  # the scene's blocks as text (the scene_listing step)
    reading_text: str
    staging_text: str
    found: list[str]  # what code already found (the staging checks), as lines
    plan_input: dict[str, Any]  # the scene_planner's input without notes
    envelope_s: int
    fixed_seconds: int | None
