"""Supabase access for canon_extract: documents in, canon entities and versions out."""
from __future__ import annotations

from uuid import UUID

import httpx

from canon_extract.runtime.rest import Rest, Row

BUCKET = "documents"


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}", "select": "id,title,orientation,settings"})

    def documents(self, production_id: UUID) -> list[Row]:
        """Ready documents, oldest first (a canon index uploaded first keeps its codes)."""
        return self.rest.select("documents", {
            "production_id": f"eq.{production_id}", "status": "eq.ready",
            "select": "id,filename,detected_role,confirmed_role,text_path", "order": "created_at"})

    def text(self, path: str) -> str:
        return self.rest.download(BUCKET, path).decode("utf-8")

    def entities(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {
            "production_id": f"eq.{production_id}",
            "select": "id,kind,code,name,aliases,core,locked,current_version_id,"
                      "current:canon_versions!canon_entities_current_version_fkey(version,card,card_hash,source)",
            "order": "code"})

    def create_entity(self, entity: Row, version: Row) -> None:
        self.rest.insert("canon_entities", [entity])
        self.rest.insert("canon_versions", [version])
        self.rest.patch("canon_entities", {"id": f"eq.{entity['id']}"}, {"current_version_id": version["id"]})

    def add_version(self, entity_id: str, version: Row, fields: Row) -> None:
        self.rest.insert("canon_versions", [version])
        self.rest.patch("canon_entities", {"id": f"eq.{entity_id}"},
                        {**fields, "current_version_id": version["id"]})

    def update_entity(self, entity_id: str, fields: Row) -> None:
        self.rest.patch("canon_entities", {"id": f"eq.{entity_id}"}, fields)

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass  # accounting must never fail the work it accounts for
