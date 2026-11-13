"""The scene as Zora reads it (plan/2026-11-13 §3.1): its shot rows, its dialogue lines and the production's
characters, read as coverage. Zora depends on no planner: it never reads a planner's stored JSON on the scene row, and
any scene with shot rows is editable, whoever planned it. The reader lives in `hiru_ai.core.coverage_rows` (phase 8:
Sable reads the same way); this module adds Zora's own sentences.
"""
from __future__ import annotations

from uuid import UUID

from hiru_ai.core import coverage_rows
from hiru_ai.core.context import RunContext
from hiru_ai.core.coverage_rows import GONE, World, characters_of, coverage_of, reread

NO_SHOTS = "This scene has no shots yet. Plan its shots first, then Zora can edit them."
__all__ = ["GONE", "NO_SHOTS", "World", "characters_of", "coverage_of", "read", "reread"]


def read(ctx: RunContext, production_id: UUID, scene_id: UUID) -> World | str:
    """The world of one turn or one click, or the sentence to say when there is none."""
    return coverage_rows.read(ctx, production_id, scene_id, no_shots=NO_SHOTS)
