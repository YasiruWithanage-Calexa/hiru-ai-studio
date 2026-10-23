"""Supabase access for structure_build: documents and canon in; episodes, scenes, lines and
questions out."""
from __future__ import annotations

from uuid import UUID

import httpx

from structure_build.runtime.rest import Rest, Row

BUCKET = "documents"


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}", "select": "id,title,orientation,settings"})

    def documents(self, production_id: UUID) -> list[Row]:
        return self.rest.select("documents", {
            "production_id": f"eq.{production_id}", "status": "eq.ready",
            "select": "id,filename,detected_role,confirmed_role,text_path,created_at", "order": "created_at"})

    def text(self, path: str) -> str:
        return self.rest.download(BUCKET, path).decode("utf-8")

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}",
                                                   "select": "id,kind,code,name,aliases", "order": "code"})

    def create_entity(self, entity: Row, version: Row) -> None:
        self.rest.insert("canon_entities", [entity])
        self.rest.insert("canon_versions", [version])
        self.rest.patch("canon_entities", {"id": f"eq.{entity['id']}"}, {"current_version_id": version["id"]})

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.rest.select("episodes", {"production_id": f"eq.{production_id}", "select": "id,number,status"})

    def upsert_episodes(self, rows: list[Row]) -> None:
        self.rest.upsert("episodes", rows)

    def scenes(self, production_id: UUID) -> list[Row]:
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}",
                                           "select": "id,episode_id,number,status,envelope_s,script_version"})

    def write_scene(self, scene: Row, lines: list[Row]) -> None:
        """Replace one scene's content: its shots and lines go (they point at the old script)."""
        self.rest.upsert("scenes", [scene])
        self.rest.delete("shots", {"scene_id": f"eq.{scene['id']}"})
        self.rest.delete("dialogue_lines", {"scene_id": f"eq.{scene['id']}"})
        if lines:
            self.rest.insert("dialogue_lines", lines)

    def delete_scenes(self, scene_ids: list[str]) -> None:
        if scene_ids:
            self.rest.delete("scenes", {"id": f"in.({','.join(scene_ids)})"})

    def upsert_questions(self, rows: list[Row]) -> None:
        if rows:
            self.rest.upsert("questions", rows)

    def answers(self, job_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"job_id": f"eq.{job_id}", "select": "key,status,answer"})

    def earlier_answers(self, production_id: UUID) -> list[Row]:
        """Questions people answered in earlier builds, oldest first (the latest wins)."""
        return self.rest.select("questions", {"production_id": f"eq.{production_id}", "status": "eq.answered",
                                              "select": "key,answer", "order": "answered_at"})

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass  # accounting must never fail the work it accounts for
