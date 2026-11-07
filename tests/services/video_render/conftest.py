from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "video_render"))

from video_render.runtime.config import Config  # noqa: E402

from contracts.video_gen import (  # noqa: E402
    RefBinding,
    RefSource,
    RenderSpec,
    VideoOverrides,
    VideoSettings,
    request_hash,
    resolve,
    spec_for,
)

PID = UUID("00000000-0000-0000-0000-0000000000a1")
SHOT = UUID("00000000-0000-0000-0000-000000000301")
USER = UUID("00000000-0000-0000-0000-00000000000b")
PNG = b"\x89PNG\r\n\x1a\n" + b"nimal"
JPG = b"\xff\xd8\xff\xe0" + b"kitchen"


def config(**kw: Any) -> Config:
    base: dict[str, Any] = {"supabase_url": "http://x", "service_role_key": "k", "api_internal_url": "http://api",
                            "internal_secret": "s", "google_api_key": "g", "fake_provider": True,
                            "download_attempts": 1, "poll_interval_s": 0.0}
    return Config(**{**base, **kw})


def source(path: str, bucket: str = "references", kind: str = "canon_sheet") -> RefSource:
    return RefSource(kind=kind, id=uuid4(), path=path, bucket=bucket)  # type: ignore[arg-type]


def ref(label: str, path: str, slot: str = "reference", bucket: str = "references") -> RefBinding:
    return RefBinding(slot=slot, source=source(path, bucket), label=label, origin="person")  # type: ignore[arg-type]


def make_spec(refs: list[RefBinding] | None = None, engine: str = "omni_flash", **over: Any) -> RenderSpec:
    locked = {k: over.pop(k) for k in ("model", "resolution") if k in over}  # the production's, set past validation
    settings = resolve(VideoSettings(engine=engine), None, VideoOverrides(**over), production_aspect="16:9",
                       shot_seconds=8).model_copy(update=locked)
    return spec_for(settings, prose="Nimal opens the door.", references=refs or [], seed=7,
                    prompt_id=uuid4(), prompt_version=3)


def render_row(spec: RenderSpec | None = None, **over: Any) -> dict[str, Any]:
    spec = spec or make_spec([ref("the character sheet for Nimal", f"{PID}/nimal/sheet.png"),
                              ref("the location plate for the kitchen", f"{PID}/kitchen/plate.jpg")])
    row = {"id": str(uuid4()), "production_id": str(PID), "shot_id": str(SHOT), "job_id": None, "status": "queued",
           "engine": spec.engine, "model": spec.model, "spec": spec.model_dump(mode="json"),
           "request_hash": request_hash(spec), "seed": spec.seed, "provider_id": None, "take_id": None,
           "usage": {}, "created_by": str(USER)}
    return {**row, **over}


class FakeStore:
    """The Store's surface over dicts. `fail_create_take` raises the 409 an earlier attempt would have caused."""

    def __init__(self, *rows: dict[str, Any]) -> None:
        self.rows = {str(r["id"]): dict(r) for r in rows}
        self.files: dict[tuple[str, str], bytes] = {
            ("references", f"{PID}/nimal/sheet.png"): PNG, ("references", f"{PID}/kitchen/plate.jpg"): JPG}
        self.uploads: dict[tuple[str, str], bytes] = {}
        self.takes: list[dict[str, Any]] = []
        self.usage: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.downloads: list[tuple[str, str]] = []
        self.duplicate_take = False

    def renders(self, render_ids: list[str]) -> list[dict[str, Any]]:
        return [dict(self.rows[i]) for i in render_ids if i in self.rows]

    def render(self, render_id: str) -> dict[str, Any] | None:
        return dict(self.rows[render_id]) if render_id in self.rows else None

    def download(self, bucket: str, path: str) -> bytes:
        self.downloads.append((bucket, path))
        return self.files[(bucket, path)]

    def claim_render(self, render_id: str) -> bool:
        row = self.rows.get(render_id)
        if row is None or row["status"] != "queued":
            return False
        row["status"] = "running"
        return True

    def mark_submitted(self, render_id: str, provider_id: str, usage: dict[str, Any]) -> None:
        row = self.rows[render_id]
        if row["status"] == "running":
            row.update(provider_id=provider_id, usage=usage)

    def swap_provider_id(self, render_id: str, current: str, new: str, usage: dict[str, Any]) -> bool:
        row = self.rows[render_id]
        if row["status"] == "running" and row["provider_id"] == current:
            row.update(provider_id=new, usage=usage)
            return True
        return False

    def finish_render(self, render_id: str, fields: dict[str, Any]) -> None:
        self.rows[render_id].update(fields)

    def create_take(self, row: dict[str, Any]) -> None:
        if self.duplicate_take:
            request = httpx.Request("POST", "http://x/rest/v1/takes")
            raise httpx.HTTPStatusError("conflict", request=request, response=httpx.Response(409, request=request))
        self.takes.append(row)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.uploads[(bucket, path)] = data

    def audit(self, row: dict[str, Any]) -> None:
        self.audits.append(row)

    def record_usage(self, row: dict[str, Any]) -> None:
        self.usage.append(row)


@pytest.fixture(autouse=True)
def _never_the_real_google(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call the real video API: real takes cost the person money (their rule, 2026-11-06). The real key in
    `.env` is blanked and the fake provider forced, so even a test that reads the environment cannot reach Google."""
    monkeypatch.setenv("GOOGLE__API_KEY", "")
    monkeypatch.setenv("VIDEO__FAKE_PROVIDER", "true")
