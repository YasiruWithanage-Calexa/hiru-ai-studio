"""Supabase access for script_split: scenes, their lines, the shots written for them."""
from __future__ import annotations

from uuid import UUID

import httpx

from script_split.runtime.rest import Rest, Row


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}", "select": "id,title,orientation,settings"})

    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[Row]:
        params = {"production_id": f"eq.{production_id}", "select": "*", "order": "episode_id,number"}
        if scene_ids is not None:
            if not scene_ids:
                return []
            params["id"] = f"in.({','.join(scene_ids)})"
        return self.rest.select("scenes", params)

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.rest.select("episodes", {"production_id": f"eq.{production_id}",
                                             "select": "id,number,status", "order": "number"})

    def lines(self, scene_id: UUID) -> list[Row]:
        return self.rest.select("dialogue_lines", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "ord"})

    def characters(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "kind": "eq.character",
                                                   "select": "id,code,name", "order": "code"})

    def scene_status(self, production_id: UUID) -> list[Row]:
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}", "select": "episode_id,status"})

    def replace_shots(self, scene_id: UUID, shots: list[Row], lines: list[Row], scene_fields: Row) -> None:
        """Delete the scene's shots, write the new ones, re-bind its lines, update the scene.
        Re-running it gives the same rows (idempotent for Cloud Tasks re-delivery)."""
        self.rest.delete("shots", {"scene_id": f"eq.{scene_id}"})
        if shots:
            self.rest.insert("shots", shots)
        if lines:
            self.rest.upsert("dialogue_lines", lines)
        self.rest.patch("scenes", {"id": f"eq.{scene_id}"}, scene_fields)

    def set_episode_status(self, episode_id: str, status: str) -> None:
        self.rest.patch("episodes", {"id": f"eq.{episode_id}"}, {"status": status})

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass  # accounting must never fail the work it accounts for
