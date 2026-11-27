"""The API on Cloud Storage (plan/2026-11-27 §4): the repository, the disk cache and `/files` read and write the
bucket, and fall back to Supabase while files are being moved. No network: a mock transport stands in for both."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from api.config import Settings, get_settings
from api.repositories.supabase import SupabaseStorage
from api.services import file_cache, media_store
from hiru_ai.core import media

_REAL_CLIENT = httpx.AsyncClient


class Cloud:
    """Both stores behind one mock transport: `bucket` and `supabase` hold "folder/path" -> bytes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bucket: dict[str, bytes] = {}
        self.supabase: dict[str, bytes] = {}
        self.seen: list[tuple[str, str]] = []
        transport = httpx.MockTransport(self.handle)
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _REAL_CLIENT(transport=transport))
        monkeypatch.setattr(media, "_TOKEN", lambda: "google-token")

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "storage.googleapis.com":
            store = self.bucket
            name = url.params["name"] if request.method == "POST" else httpx.URL(
                "http://x/" + url.raw_path.decode().split("/o/")[1].split("?")[0]).path[1:]
        else:
            store, name = self.supabase, url.path.split("/object/")[1]
        self.seen.append((request.method, url.host))
        if request.method == "POST":
            if url.params.get("ifGenerationMatch") == "0" and name in store:
                return httpx.Response(412)
            store[name] = request.content
            return httpx.Response(200)
        if request.method == "DELETE":
            if name in store:
                del store[name]
                return httpx.Response(204)
            return httpx.Response(404) if store is self.bucket else httpx.Response(400, text='{"error":"not_found"}')
        return httpx.Response(200, content=store[name], headers={"content-type": "image/png"}) \
            if name in store else httpx.Response(404)


def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, fallback: bool = False) -> Settings:
    monkeypatch.setenv("FILES__BACKEND", "gcs")
    monkeypatch.setenv("FILES__GCS_BUCKET", "bkt")
    monkeypatch.setenv("FILES__READ_FALLBACK", "true" if fallback else "false")
    monkeypatch.setenv("FILES__CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    return get_settings()


def test_the_repository_writes_reads_and_removes_in_the_bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    settings(monkeypatch, tmp_path)
    cloud = Cloud(monkeypatch)
    repo = SupabaseStorage(db=None)  # type: ignore[arg-type]  # the Supabase client is not touched

    async def go() -> None:
        await repo.upload("documents", "p/d 1.txt", b"hello", "text/plain")
        assert cloud.bucket == {"documents/p/d 1.txt": b"hello"} and cloud.supabase == {}
        with pytest.raises(httpx.HTTPStatusError):  # create only, as the Supabase client's default
            await repo.upload("documents", "p/d 1.txt", b"again", "text/plain")
        assert await repo.download("documents", "p/d 1.txt") == b"hello"
        await repo.remove("documents", "p/d 1.txt")
        await repo.remove("documents", "p/d 1.txt")  # already gone is fine
        assert cloud.bucket == {}

    asyncio.run(go())


def test_the_disk_cache_falls_back_to_supabase_and_then_serves_from_disk(monkeypatch: pytest.MonkeyPatch,
                                                                        tmp_path: Path):
    config = settings(monkeypatch, tmp_path, fallback=True)
    cloud = Cloud(monkeypatch)
    cloud.supabase["frames/p/old.png"] = b"old"
    cache = file_cache.FileCache(config)

    async def go() -> None:
        assert (await cache.fetch("frames", "p/old.png")).path.read_bytes() == b"old"
        await cache.fetch("frames", "p/old.png")

    asyncio.run(go())
    supabase_host = httpx.URL(config.supabase.url).host
    assert [host for _m, host in cloud.seen] == ["storage.googleapis.com", supabase_host]  # then the disk


def test_without_fallback_a_file_only_in_supabase_is_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config = settings(monkeypatch, tmp_path)
    cloud = Cloud(monkeypatch)
    cloud.supabase["frames/p/old.png"] = b"old"
    file_cache.MISSES.clear()

    async def go() -> None:
        with pytest.raises(file_cache.NotFound):
            await file_cache.FileCache(config).fetch("frames", "p/old.png")

    asyncio.run(go())
    assert [host for _m, host in cloud.seen] == ["storage.googleapis.com"]


def test_a_removal_during_the_move_leaves_no_copy_to_fall_back_to(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config = settings(monkeypatch, tmp_path, fallback=True)
    cloud = Cloud(monkeypatch)
    cloud.supabase["documents/p/d.txt"] = b"old"

    async def go() -> None:
        await media_store.remove(config, "documents", "p/d.txt")

    asyncio.run(go())
    assert cloud.supabase == {} and cloud.bucket == {}


def test_a_backend_without_a_bucket_stops_the_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    settings(monkeypatch, tmp_path)
    monkeypatch.setenv("FILES__GCS_BUCKET", "")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="FILES__GCS_BUCKET"):
        media_store.media_for(get_settings())
