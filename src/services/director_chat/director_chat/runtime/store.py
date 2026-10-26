"""Supabase access for director_chat: the scene in, the edited plan and the messages out."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

import httpx

from director_chat.runtime.rest import Rest, Row


def vector(values: list[float] | None) -> str | None:
    return None if values is None else "[" + ",".join(f"{v:.7g}" for v in values) + "]"


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    # ── reading ──────────────────────────────────────────────────────────────────────────
    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}",
                                               "select": "id,title,orientation,settings,summary"})

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        return self.rest.first("scenes", {"id": f"eq.{scene_id}", "production_id": f"eq.{production_id}",
                                          "select": "*,episode:episodes(number,title)"})

    def lines(self, scene_id: UUID) -> list[Row]:
        return self.rest.select("dialogue_lines", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "ord"})

    def shots(self, scene_id: UUID) -> list[Row]:
        return self.rest.select("shots", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "number"})

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {
            "production_id": f"eq.{production_id}", "order": "code",
            "select": "id,kind,code,name,aliases,locked,"
                      "current:canon_versions!canon_entities_current_version_fkey(card,wardrobe_anchor,voice_pin)"})

    def board(self, production_id: UUID) -> list[Row]:
        return self.rest.select("production_director_board", {
            "production_id": f"eq.{production_id}",
            "select": "seat,persona:director_personas(id,name,initials,specialty,style_note,charter)"})

    def default_persona(self) -> Row | None:
        return self.rest.first("director_personas", {"active": "eq.true", "slug": "eq.classic-teledrama",
                                                     "select": "id,name,initials,specialty,style_note,charter"})

    def messages(self, thread_id: UUID, limit: int = 12) -> list[Row]:
        rows = self.rest.select("chat_messages", {"thread_id": f"eq.{thread_id}",
                                                  "select": "id,kind,speaker,text,blocks",
                                                  "order": "created_at.desc", "limit": str(limit)})
        return rows[::-1]

    def memory(self, production_id: UUID, limit: int = 20) -> list[Row]:
        return self.rest.select("memory_items", {"production_id": f"eq.{production_id}", "select": "kind,text",
                                                 "order": "created_at.desc", "limit": str(limit)})

    def open_questions(self, production_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"production_id": f"eq.{production_id}", "status": "eq.open",
                                              "select": "scope,title,body"})

    def ready_documents(self, production_id: UUID) -> list[Row]:
        return self.rest.select("documents", {"production_id": f"eq.{production_id}", "status": "eq.ready",
                                              "select": "id,filename"})

    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID,
               document_ids: list[str], k: int = 6) -> list[Row]:
        r = self.rest.client.post(f"{self.rest.rest}/rpc/match_chunks", headers=self.rest.headers, json={
            "query_text": query, "query_embedding": vector(embedding), "p_production_id": str(production_id),
            "p_corpora": ["production_docs", "memory"], "p_document_ids": document_ids, "match_count": k})
        r.raise_for_status()
        return list(r.json())

    # ── writing ──────────────────────────────────────────────────────────────────────────
    def save_plan(self, scene_id: UUID, shots: list[Row], removed: list[str], lines: list[Row],
                  scene_fields: Row, removed_lines: list[str] | None = None) -> None:
        """Shots keep their ids (frames and prompts hang off them); numbering is checked at the
        end of the statement (deferred unique), so one upsert can renumber them. Lines a script
        change removed go first, and the scene's script last, once every line it names exists."""
        if removed_lines:
            self.rest.delete("dialogue_lines", {"id": f"in.({','.join(removed_lines)})"})
        if removed:
            self.rest.delete("shots", {"id": f"in.({','.join(removed)})"})
        if shots:
            self.rest.upsert("shots", shots)
        if lines:
            self.rest.upsert("dialogue_lines", lines)
        self.rest.patch("scenes", {"id": f"eq.{scene_id}"}, scene_fields)

    def add_message(self, row: Row) -> None:
        self.rest.insert("chat_messages", [row])

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass  # the audit trail never fails the change it records

    def add_memory(self, item: Row, embedding: list[float] | None, model: str) -> None:
        self.rest.insert("memory_items", [item])
        text = str(item["text"])
        self.rest.insert("chunks", [{
            "corpus": "memory", "production_id": item["production_id"], "source": f"memory:{item['id']}",
            "heading": item["kind"].capitalize(), "context_header": "Production memory", "content": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(), "embedding": embedding,
            "embedding_model": model if embedding else "", "meta": json.loads(json.dumps(item["source_ref"]))}])

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass
