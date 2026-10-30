"""Supabase access for frame_render: frames and reference sheets, their shots and canon."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from frame_render.runtime.rest import Rest, Row

FRAMES_BUCKET = "frames"
REFERENCES_BUCKET = "references"
_CANON = ("id,kind,code,name,aliases,"
          "current:canon_versions!canon_entities_current_version_fkey"
          "(id,version,card,wardrobe_anchor,voice_pin,reference_prompt,reference_assets)")


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    # ── reading ──────────────────────────────────────────────────────────────────────────
    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}", "select": "id,title,orientation"})

    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[Row]:
        if not frame_ids:
            return []
        return self.rest.select("first_frames", {"production_id": f"eq.{production_id}",
                                                 "id": f"in.({','.join(frame_ids)})", "select": "*",
                                                 "order": "created_at"})

    def shot(self, shot_id: str) -> Row | None:
        return self.rest.first("shots", {"id": f"eq.{shot_id}", "select": "*"})

    def scene(self, scene_id: str) -> Row | None:
        return self.rest.first("scenes", {"id": f"eq.{scene_id}", "select": "*"})

    def lines(self, scene_id: str) -> list[Row]:
        return self.rest.select("dialogue_lines", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "ord"})

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "order": "code",
                                                   "select": _CANON})

    def look(self, look_id: str) -> Row | None:
        return self.rest.first("canon_looks", {"id": f"eq.{look_id}", "select": "*"})

    def looks(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_looks", {"production_id": f"eq.{production_id}", "select": "*",
                                                "order": "created_at"})

    def scene_looks(self, scene_id: str) -> list[Row]:
        return self.rest.select("scene_looks", {"scene_id": f"eq.{scene_id}", "select": "entity_id,look_id"})

    def episode_number(self, episode_id: str) -> int | None:
        row = self.rest.first("episodes", {"id": f"eq.{episode_id}", "select": "number"})
        return int(row["number"]) if row else None

    def download_reference(self, path: str) -> bytes:
        return self.rest.download(REFERENCES_BUCKET, path)

    # ── writing ──────────────────────────────────────────────────────────────────────────
    def claim_frame(self, frame_id: str) -> bool:
        """queued → running, or False when another delivery already has it (the take-row lock
        from upstream: a re-delivered task must not pay for the same picture twice)."""
        return bool(self.rest.claim("first_frames", {"id": f"eq.{frame_id}", "status": "eq.queued"},
                                    {"status": "running"}))

    def finish_frame(self, frame_id: str, fields: Row) -> None:
        self.rest.patch("first_frames", {"id": f"eq.{frame_id}"}, fields)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.rest.upload(bucket, path, data, mime)

    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None:
        self.rest.patch("canon_versions", {"id": f"eq.{version_id}"}, {"reference_assets": assets})

    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None:
        """A new sheet is not the one a person approved: the look goes back to draft."""
        self.rest.patch("canon_looks", {"id": f"eq.{look_id}"}, {"sheet_assets": assets, "status": "draft"})

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass
