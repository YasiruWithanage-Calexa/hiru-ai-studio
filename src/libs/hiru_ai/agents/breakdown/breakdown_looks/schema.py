"""Typed seams of the breakdown_looks agent (plan/2026-11-12c): the message is built by `contracts.scene_looks`; the
answer is `contracts.scene_looks.LooksAnswer`, which code checks (`contracts.scene_looks.check`) before anything is
stored."""

from __future__ import annotations

from pydantic import BaseModel

from contracts.scene_looks import LooksAnswer as Output


class Input(BaseModel):
    message: str  # built by contracts.scene_looks.message


__all__ = ["Input", "Output"]
