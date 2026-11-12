"""Supabase access for frame_render: frames and reference sheets, their shots and canon."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from frame_render.runtime import thumbs
from frame_render.runtime.rest import Rest, Row

_logger = logging.getLogger(__name__)
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

    def shots(self, scene_id: str) -> list[Row]:
        return self.rest.select("shots", {"scene_id": f"eq.{scene_id}", "select": "id,slate,number,person_edits",
                                          "order": "number"})

    def accepted_finals(self, shot_ids: list[str]) -> dict[str, Row]:
        """shot id → its accepted FINAL frame with a picture: the same-setup frame (plan/2026-11-11b)."""
        if not shot_ids:
            return {}
        rows = self.rest.select("first_frames", {"shot_id": f"in.({','.join(shot_ids)})", "accepted_at": "not.is.null",
                                                 "stage": "neq.draft", "status": "eq.done",
                                                 "select": "id,shot_id,storage_path"})
        return {str(r["shot_id"]): r for r in rows if r.get("storage_path")}

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "order": "code",
                                                   "select": _CANON})

    def look(self, look_id: str) -> Row | None:
        return self.rest.first("canon_looks", {"id": f"eq.{look_id}", "select": "*"})

    def looks(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_looks", {"production_id": f"eq.{production_id}", "select": "*",
                                                "order": "created_at"})

    def scene_looks(self, scene_id: str) -> list[Row]:
        return self.rest.select("scene_looks", {"scene_id": f"eq.{scene_id}", "select": "*"})

    def episode_number(self, episode_id: str) -> int | None:
        row = self.rest.first("episodes", {"id": f"eq.{episode_id}", "select": "number"})
        return int(row["number"]) if row else None

    def download_reference(self, path: str) -> bytes:
        return self.rest.download(REFERENCES_BUCKET, path)

    def download_frame(self, path: str) -> bytes:
        """A painted frame (a draft a final is painted from)."""
        return self.rest.download(FRAMES_BUCKET, path)

    # ── writing ──────────────────────────────────────────────────────────────────────────
    def claim_frame(self, frame_id: str) -> bool:
        """queued → running, or False when another delivery already has it (the take-row lock
        from upstream: a re-delivered task must not pay for the same picture twice)."""
        return bool(self.rest.claim("first_frames", {"id": f"eq.{frame_id}", "status": "eq.queued"},
                                    {"status": "running"}))

    def finish_frame(self, frame_id: str, fields: Row) -> None:
        try:
            self.rest.patch("first_frames", {"id": f"eq.{frame_id}"}, fields)
        except httpx.HTTPStatusError as exc:
            # A database still on schema v8 has no `checks` column: the frame matters more than
            # its checks, so it is recorded without them (Database/README.md, v8 → v9).
            if "checks" not in fields or exc.response.status_code != 400:
                raise
            _logger.warning("first_frames.checks missing (schema v8?); frame %s saved without checks", frame_id)
            rest = {k: v for k, v in fields.items() if k != "checks"}
            self.rest.patch("first_frames", {"id": f"eq.{frame_id}"}, rest)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.rest.upload(bucket, path, data, mime)
        if thumbs.wants_thumb(bucket, path, mime):  # the small copy beside the picture (plan/2026-11-08c 1c)
            small = thumbs.make(data)
            if small is not None:
                try:
                    self.rest.upload(bucket, thumbs.thumb_path(path), small, thumbs.MIME)
                except Exception:  # best effort: the tile falls back to the full picture
                    _logger.warning("thumbnail of %s/%s not stored", bucket, path, exc_info=True)

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
