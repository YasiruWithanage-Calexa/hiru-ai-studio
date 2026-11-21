"""plan/2026-11-21: the API's own reads of write-once files (the scene bundle's frames and sheets) come from its disk
copy, fetched once; documents and a cache that cannot help go to Storage as before."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from api.repositories.supabase import SupabaseStorage
from api.services import file_cache


class Bucket:
    def __init__(self, asked: list[str]) -> None:
        self.asked = asked

    async def download(self, path: str) -> bytes:
        self.asked.append(path)
        return b"from storage"


class Db:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.storage = self

    def from_(self, bucket: str) -> Bucket:
        return Bucket(self.asked)


class Cache:
    def __init__(self, file: Path, error: Exception | None = None) -> None:
        self.file, self.error, self.fetched = file, error, 0

    async def fetch(self, bucket: str, path: str) -> file_cache.Cached:
        self.fetched += 1
        if self.error:
            raise self.error
        return file_cache.Cached(self.file, "image/png")


def test_a_write_once_file_is_read_from_the_disk_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    kept = tmp_path / "f.png"
    kept.write_bytes(b"from disk")
    cache = Cache(kept)
    monkeypatch.setattr(file_cache, "get_cache", lambda settings: cache)
    db = Db()
    storage = SupabaseStorage(db)  # type: ignore[arg-type]
    assert asyncio.run(storage.download("frames", "p/s/f.png")) == b"from disk"
    assert asyncio.run(storage.download("documents", "p/d.pdf")) == b"from storage", "documents overwrite"
    assert cache.fetched == 1 and db.asked == ["p/d.pdf"]


@pytest.mark.parametrize("error", [file_cache.TooLarge(), file_cache.Unreachable(), file_cache.NotFound()])
def test_a_cache_that_cannot_help_falls_back_to_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Any):
    monkeypatch.setattr(file_cache, "get_cache", lambda settings: Cache(tmp_path / "x", error))
    db = Db()
    assert asyncio.run(SupabaseStorage(db).download("takes", "p/t.mp4")) == b"from storage"  # type: ignore[arg-type]
    assert db.asked == ["p/t.mp4"]
