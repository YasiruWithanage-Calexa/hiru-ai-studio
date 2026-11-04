"""The designs under review, as the shots the critic's tools read (plan/2026-11-04 §8, row 4).

The shot critic reviews drafts that are not saved yet: the producer saves a scene's designs only after the review.
A tool that read the stored shots (`staging_check`, `continuity_check`, `shot_read`) would check last time's design.
So during the review the scenes port is this overlay: every read goes to the real port, except that a shot under
review comes back with the draft's `ir` and `on_screen` in place of the stored ones. The tools only read, and a write
method here refuses.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import Row, SceneStore


class DraftScenes:
    """A `SceneStore` that reads the real one and serves the drafts for the shots under review."""

    def __init__(self, scenes: SceneStore, drafts: dict[str, tuple[Row, list[str]]]) -> None:
        self._scenes, self._drafts = scenes, drafts  # shot id -> (the draft's ir, the ids it puts on screen)

    def shots(self, scene_id: UUID | str) -> list[Row]:
        out = []
        for row in self._scenes.shots(scene_id):
            draft = self._drafts.get(str(row.get("id")))
            if draft is not None:
                ir, on_screen = draft
                row = {**row, "ir": dict(ir), "design": {**(row.get("design") or {}), "on_screen": list(on_screen)}}
            out.append(row)
        return out

    def __getattr__(self, name: str) -> Any:
        if name in ("save_plan", "replace_shots", "save_design", "add_prompt"):
            raise PermissionError(f"{name}: the review reads drafts; it saves nothing")
        return getattr(self._scenes, name)


def reviewing(ctx: RunContext, scene_id: str, drafts: dict[str, tuple[Row, list[str]]]) -> RunContext:
    """`ctx` for the critic: the scene in scope, and the drafts as its shots."""
    scenes: SceneStore = ctx.need("scenes")
    return replace(ctx, scene_id=UUID(str(scene_id)), ports=replace(ctx.ports, scenes=DraftScenes(scenes, drafts)))
