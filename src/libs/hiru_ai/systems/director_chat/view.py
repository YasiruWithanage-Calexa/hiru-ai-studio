"""The director's world as the turn's code knows it: one object with the methods the engine's store had, built from the
run's ports. The scene's lines, shots, canon and saved plan are the scenes port; the board, the thread, the pending
action and the memory are the director port. Nothing here decides anything.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import DirectorStore, SceneStore

Row = dict[str, Any]


class DirectorView:
    def __init__(self, ctx: RunContext) -> None:
        self._scenes: SceneStore = ctx.need("scenes")
        self._director: DirectorStore = ctx.need("director")

    # ── the scenes port ──────────────────────────────────────────────────────────────────────────────────────────
    def production(self, production_id: UUID) -> Row | None:
        return self._scenes.production(production_id)

    def lines(self, scene_id: UUID) -> list[Row]:
        return self._scenes.lines(scene_id)

    def shots(self, scene_id: UUID) -> list[Row]:
        return self._scenes.shots(scene_id)

    def canon(self, production_id: UUID) -> list[Row]:
        return self._scenes.canon(production_id)

    def save_plan(self, scene_id: UUID, shots: list[Row], removed: list[str], lines: list[Row], scene_fields: Row,
                  removed_lines: list[str] | None = None) -> None:
        self._scenes.save_plan(scene_id, shots, removed, lines, scene_fields, removed_lines)

    # ── the director port ────────────────────────────────────────────────────────────────────────────────────────
    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        return self._director.scene(production_id, scene_id)

    def board(self, production_id: UUID) -> list[Row]:
        return self._director.board(production_id)

    def default_persona(self) -> Row | None:
        return self._director.default_persona()

    def messages(self, thread_id: UUID, limit: int = 12) -> list[Row]:
        return self._director.messages(thread_id, limit)

    def message(self, message_id: UUID | str) -> Row | None:
        return self._director.message(message_id)

    def open_pending(self, thread_id: UUID | str) -> Row | None:
        return self._director.open_pending(thread_id)

    def add_pending(self, row: Row) -> None:
        self._director.add_pending(row)

    def close_pending(self, thread_id: UUID | str, status: str) -> None:
        self._director.close_pending(thread_id, status)

    def set_blocks(self, message_id: UUID | str, blocks: list[Row]) -> None:
        self._director.set_blocks(message_id, blocks)

    def memory(self, production_id: UUID, limit: int = 20) -> list[Row]:
        return self._director.memory(production_id, limit)

    def open_questions(self, production_id: UUID) -> list[Row]:
        return self._director.open_questions(production_id)

    def ready_documents(self, production_id: UUID) -> list[Row]:
        return self._director.ready_documents(production_id)

    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID, document_ids: list[str],
               k: int = 6) -> list[Row]:
        return self._director.search(query=query, embedding=embedding, production_id=production_id,
                                     document_ids=document_ids, k=k)

    def add_message(self, row: Row) -> None:
        self._director.add_message(row)

    def add_memory(self, item: Row, embedding: list[float] | None, model: str) -> None:
        self._director.add_memory(item, embedding, model)

    def audit(self, row: Row) -> None:
        self._director.audit(row)
