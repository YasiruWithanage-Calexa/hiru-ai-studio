"""The looks call's answer: how the agent reads story time, the looks (one outfit each), and who wears which look in
each scene with the scene's condition. Strict JSON schema built the same way as `schema.json_schema`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from schema import _strict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryTime(_M):
    scene: str
    story_day: int
    part_of_day: Literal["dawn", "morning", "day", "evening", "night"]
    continuous_with: str  # a scene id, or ""
    why: str


class Look(_M):
    id: str  # C01-1
    person: str  # C id
    name: str  # "Stall days", "Opening day"
    outfit: str
    hair: str
    makeup: str
    accessories: str
    why: str


class Wear(_M):
    person: str
    look: str
    condition: str
    why: str


class SceneWear(_M):
    scene: str
    on_screen: list[Wear]


class LooksAnswer(_M):
    story: list[StoryTime]
    looks: list[Look]
    scenes: list[SceneWear]


def json_schema() -> dict[str, Any]:
    raw = LooksAnswer.model_json_schema()
    return _strict(raw, raw.get("$defs", {}))
