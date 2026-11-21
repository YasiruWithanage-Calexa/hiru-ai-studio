"""plan/2026-11-21 phases 1-2: a write-once file crosses the internet once per machine.

Unit: hit, miss, write-through, one download for N threads, atomic write, LRU trim, `documents` pass through, the
in-memory fallback and its cap, a 404 never kept, the API's folder is the workers' folder.
System: a frame job over several frames that share two sheets downloads each sheet once; a second job downloads
nothing; a frame just painted (a draft) is never downloaded to paint its final.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from frame_render.engine.image import RefusedError

from hiru_ai.core import file_store
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.file_store import CachedFiles, CacheSettings, FilesConfig
from hiru_ai.core.ports import ImageRefused
from hiru_ai.systems.frame_render import graph
from tests.parity.graph_support import environment
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import FakePainter, FakeStore
from tests.services.frame_render.test_frame_render import payload, shots


class Upstream:
    """Supabase stood in for: counts every download."""

    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None, delay: float = 0.0) -> None:
        self.objects = dict(objects or {})
        self.downloads: Counter[tuple[str, str]] = Counter()
        self.uploads: list[tuple[str, str]] = []
        self.delay = delay

    def download(self, bucket: str, path: str) -> bytes:
        self.downloads[(bucket, path)] += 1
        if self.delay:
            time.sleep(self.delay)
        if (bucket, path) not in self.objects:
            request = httpx.Request("GET", f"http://x/storage/v1/object/{bucket}/{path}")
            raise httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))
        return self.objects[(bucket, path)]

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.uploads.append((bucket, path))
        self.objects[(bucket, path)] = data


def settings(tmp_path: Path, gb: float = 1.0) -> CacheSettings:
    return CacheSettings(FilesConfig(cache_dir=str(tmp_path / "cache"), cache_max_gb=gb))


# ── unit ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_write_once_file_is_downloaded_once_then_read_from_disk(tmp_path: Path):
    up = Upstream({("references", "p/kamala.png"): b"sheet"})
    files = CachedFiles(up, settings(tmp_path))
    assert files.download("references", "p/kamala.png") == b"sheet"
    assert CachedFiles(up, settings(tmp_path)).download("references", "p/kamala.png") == b"sheet", "another job"
    assert up.downloads[("references", "p/kamala.png")] == 1
    assert (files.stats.misses, files.stats.hits, files.stats.upstream_bytes) == (1, 0, 5)
    assert files.summary() == "storage: 1 from Supabase (0.0 MB), 0 from disk"


def test_an_upload_is_written_through_and_never_downloaded(tmp_path: Path):
    up = Upstream()
    files = CachedFiles(up, settings(tmp_path))
    files.upload("frames", "p/s/f.png", b"painted", "image/png")
    assert files.download("frames", "p/s/f.png") == b"painted"
    assert not up.downloads and files.stats.hits == 1 and up.uploads == [("frames", "p/s/f.png")]
    kept = file_store._file_for(tmp_path / "cache", "frames", "p/s/f.png")
    assert file_store.media_type(kept, "p/s/f.png") == "image/png"


def test_documents_overwrite_so_they_pass_through_and_are_never_kept(tmp_path: Path):
    up = Upstream({("documents", "p/d.txt"): b"v1"})
    files = CachedFiles(up, settings(tmp_path))
    files.download("documents", "p/d.txt")
    files.upload("documents", "p/d.txt", b"v2", "text/plain")
    assert files.download("documents", "p/d.txt") == b"v2"
    assert up.downloads[("documents", "p/d.txt")] == 2 and not (tmp_path / "cache").exists()


def test_a_404_is_raised_and_not_kept(tmp_path: Path):
    up = Upstream()
    files = CachedFiles(up, settings(tmp_path))
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            files.download("frames", "p/missing.png")
    assert up.downloads[("frames", "p/missing.png")] == 2, "a miss is asked again (it may have been painted since)"
    up.objects[("frames", "p/missing.png")] = b"now"
    assert files.download("frames", "p/missing.png") == b"now"


def test_many_threads_asking_for_one_sheet_make_one_download(tmp_path: Path):
    up = Upstream({("references", "p/kamala.png"): b"sheet"}, delay=0.05)
    files = CachedFiles(up, settings(tmp_path))
    got: list[bytes] = []
    threads = [threading.Thread(target=lambda: got.append(files.download("references", "p/kamala.png")))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert got == [b"sheet"] * 8 and up.downloads[("references", "p/kamala.png")] == 1
    assert files.stats.misses == 1 and files.stats.hits == 7


def test_the_write_is_atomic_and_leaves_no_part_file(tmp_path: Path):
    base = tmp_path / "cache"
    file = file_store.keep(base, "takes", "p/t.mp4", b"video", "video/mp4")
    assert file.read_bytes() == b"video"
    assert not [p for p in base.rglob("*") if p.name.endswith(file_store.PART_SUFFIX)]


def test_over_the_cap_the_least_recently_used_go_first(tmp_path: Path):
    up = Upstream({("frames", f"p/{i}.png"): bytes(4000) for i in range(3)})
    files = CachedFiles(up, settings(tmp_path, gb=9000 / 1024**3))  # room for two
    base = tmp_path / "cache"
    files.download("frames", "p/0.png")
    old = file_store._file_for(base, "frames", "p/0.png")
    os.utime(old, (time.time() - 100, time.time() - 100))
    files.download("frames", "p/1.png")
    files.download("frames", "p/2.png")
    assert not old.exists(), "the oldest went"
    assert file_store._file_for(base, "frames", "p/2.png").exists()


def test_without_a_disk_a_bounded_memory_cache_serves_the_process(tmp_path: Path):
    up = Upstream({("references", "a.png"): bytes(60), ("references", "b.png"): bytes(60)})
    memory = file_store._MemoryLRU(cap=100)
    off = CacheSettings(FilesConfig(cache_dir=str(tmp_path / "unused"), cache_max_gb=0))
    files = CachedFiles(up, off, memory=memory)
    files.download("references", "a.png")
    CachedFiles(up, off, memory=memory).download("references", "a.png")
    assert up.downloads[("references", "a.png")] == 1, "kept for the life of the process"
    files.download("references", "b.png")  # over the cap: a goes
    files.download("references", "a.png")
    assert up.downloads[("references", "a.png")] == 2 and memory.size <= 100
    assert not (tmp_path / "unused").exists() and "from memory" in files.summary()


def test_the_api_and_the_workers_share_one_folder_and_one_name(tmp_path: Path):
    from api.services import file_cache

    assert file_cache.root is file_store.root and file_cache._file_for is file_store._file_for
    up = Upstream({("frames", "p/x.png"): b"pic"})
    files = CachedFiles(up, settings(tmp_path))
    files.download("frames", "p/x.png")
    api_settings = type("S", (), {"files": FilesConfig(cache_dir=str(tmp_path / "cache"), cache_max_gb=1)})()
    assert file_cache.root(api_settings) == tmp_path / "cache"
    assert file_cache._file_for(tmp_path / "cache", "frames", "p/x.png").read_bytes() == b"pic"


def test_settings_come_from_the_apis_environment_names(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("FILES__CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FILES__CACHE_MAX_GB", "0.5")
    assert CacheSettings.from_env() == CacheSettings(FilesConfig(cache_dir=str(tmp_path), cache_max_gb=0.5))


def test_the_ports_wrap_supabase_files_in_the_cache():
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.adapters.storage import SupabaseFiles

    ports = supabase_rest._ports(supabase_rest.Rest("http://x", "k"))
    assert isinstance(ports.files, CachedFiles) and isinstance(ports.files.inner, SupabaseFiles)
    assert ports.files.rest is ports.files.inner.rest, "the adapter's own attributes still reach through"


# ── system: a frame job (phase 2) ───────────────────────────────────────────────────────────────────────────────


class StoreFiles:
    """The FakeStore's pictures as the `Files` port, every download counted (what Supabase would serve)."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.downloads: Counter[tuple[str, str]] = Counter()

    def download(self, bucket: str, path: str) -> bytes:
        self.downloads[(bucket, path)] += 1
        if (bucket, path) in self.store.uploads:
            return self.store.uploads[(bucket, path)]
        return self.store.download_frame(path) if bucket == "frames" else self.store.download_reference(path)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.store.upload(bucket, path, data, mime)


def run_job(store: FakeStore, upstream: StoreFiles, frame_ids: list[str], tmp_path: Path) -> CachedFiles:
    def images(prompt: str, aspect: str, references: list[Any], *, draft: bool = False, sheet: bool = False,
               quality: str = "") -> Any:
        try:
            return FakePainter()(prompt, aspect, references, draft=draft, sheet=sheet)
        except RefusedError as exc:  # pragma: no cover
            raise ImageRefused(str(exc)) from exc

    files = CachedFiles(upstream, settings(tmp_path))
    p = payload(frame_ids=frame_ids)
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=files, images=images))
    with environment(OPENAI__API_KEY=""):
        graph.run(p, ctx)
    return files


def test_a_frame_job_downloads_each_shared_sheet_once_and_a_second_job_nothing(tmp_path: Path):
    store = FakeStore()
    s1, s2 = shots(store)[0], shots(store)[1]
    first = [store.add_frame(s["id"]) for s in (s1, s1, s2, s1, s2)]
    upstream = StoreFiles(store)
    files = run_job(store, upstream, first, tmp_path)
    assert all(store.frame_rows[f]["status"] == "done" for f in first)
    sheets = {k: n for k, n in upstream.downloads.items() if k[0] == "references"}
    assert sheets and set(sheets.values()) == {1}, f"each sheet once for five frames: {sheets}"
    assert files.stats.hits >= 5 and files.summary().startswith(f"storage: {len(upstream.downloads)} from Supabase")

    upstream.downloads.clear()
    again = [store.add_frame(s["id"]) for s in (s1, s2)]
    run_job(store, upstream, again, tmp_path)
    assert all(store.frame_rows[f]["status"] == "done" for f in again)
    assert not upstream.downloads, "a second job on this machine downloads nothing"


def test_a_frame_just_painted_is_never_downloaded_to_paint_from_it(tmp_path: Path):
    store = FakeStore()
    s1 = shots(store)[0]
    upstream = StoreFiles(store)
    draft = store.add_frame(s1["id"], stage="draft")
    run_job(store, upstream, [draft], tmp_path)
    path = store.frame_rows[draft]["storage_path"]
    assert store.frame_rows[draft]["status"] == "done" and ("frames", path) in store.uploads

    final = store.add_frame(s1["id"], draft_id=draft)
    asked: list[tuple[str, str]] = []
    read = CachedFiles.download
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CachedFiles, "download", lambda self, b, n: asked.append((b, n)) or read(self, b, n))
        run_job(store, upstream, [final], tmp_path)
    assert store.frame_rows[final]["status"] == "done"
    assert ("frames", path) in asked, "the final is painted from its draft"
    assert upstream.downloads[("frames", path)] == 0, "the draft was kept when it was stored (write-through)"
