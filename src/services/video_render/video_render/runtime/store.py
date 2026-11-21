"""Supabase access for video_render: renders, the takes they make, and the private buckets."""
from __future__ import annotations

import logging

import httpx

from hiru_ai.core.file_store import CachedFiles
from video_render.runtime.rest import Rest, Row

_logger = logging.getLogger(__name__)

TAKES_BUCKET = "takes"


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest
        # plan/2026-11-21 D2: a reference picture crosses the internet once per machine, and the take stored here is
        # kept too (write-through).
        self.files = CachedFiles(rest)

    # ── reading ──────────────────────────────────────────────────────────────────────────
    def renders(self, render_ids: list[str]) -> list[Row]:
        if not render_ids:
            return []
        return self.rest.select("video_renders", {"id": f"in.({','.join(render_ids)})", "select": "*",
                                                  "order": "created_at"})

    def render(self, render_id: str) -> Row | None:
        return self.rest.first("video_renders", {"id": f"eq.{render_id}", "select": "*"})

    def download(self, bucket: str, path: str) -> bytes:
        return self.files.download(bucket, path)

    # ── writing ──────────────────────────────────────────────────────────────────────────
    def claim_render(self, render_id: str) -> bool:
        """queued → running, or False when another delivery already has it: the row IS the lock, so a re-delivered
        task never pays for a second video."""
        return bool(self.rest.claim("video_renders", {"id": f"eq.{render_id}", "status": "eq.queued"},
                                    {"status": "running"}))

    def mark_submitted(self, render_id: str, provider_id: str, usage: Row) -> None:
        """The moment the provider accepted the job: from here a video is being paid for."""
        self.rest.patch("video_renders", {"id": f"eq.{render_id}", "status": "eq.running"},
                        {"provider_id": provider_id, "usage": usage})

    def swap_provider_id(self, render_id: str, current: str, new: str, usage: Row) -> bool:
        """Compare-and-swap on `provider_id`: two re-deliveries racing cannot both resume."""
        return bool(self.rest.claim("video_renders",
                                    {"id": f"eq.{render_id}", "status": "eq.running", "provider_id": f"eq.{current}"},
                                    {"provider_id": new, "usage": usage}))

    def finish_render(self, render_id: str, fields: Row) -> None:
        self.rest.patch("video_renders", {"id": f"eq.{render_id}"}, fields)

    def create_take(self, row: Row) -> None:
        self.rest.insert("takes", [row])

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.files.upload(bucket, path, data, mime)

    def set_take(self, take_id: str, fields: Row) -> None:
        """The take's length and still, read once at write time (D8). `poster_path` is a schema v24 column: a database
        without it refuses the field (400), so the length is saved alone and the still waits for the upgrade."""
        try:
            self.rest.patch("takes", {"id": f"eq.{take_id}"}, fields)
        except httpx.HTTPStatusError as exc:
            if "poster_path" not in fields or exc.response.status_code != 400:
                raise
            _logger.warning("takes.poster_path missing (schema v24 not applied?); take %s saved without its still",
                            take_id)
            rest = {k: v for k, v in fields.items() if k != "poster_path"}
            if rest:
                self.rest.patch("takes", {"id": f"eq.{take_id}"}, rest)

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

