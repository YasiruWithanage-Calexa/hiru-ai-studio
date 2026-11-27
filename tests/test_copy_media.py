"""`scripts/copy_media.py` (plan/2026-11-27 §4): copies what the bucket lacks, overwrites and deletes nothing, and says
whether the fallback can be turned off. Both stores are stood in for; no network."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from hiru_ai.core import media

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
copy_media = importlib.import_module("copy_media")


class Stores:
    def __init__(self, supabase: dict[str, bytes], bucket: dict[str, bytes] | None = None) -> None:
        self.supabase = supabase
        self.bucket = dict(bucket or {})
        self.methods: set[tuple[str, str]] = set()

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.methods.add((request.method, url.host))
        if url.host == "storage.googleapis.com":
            if request.method == "POST":
                name = url.params["name"]
                if name in self.bucket:
                    return httpx.Response(412)
                self.bucket[name] = request.content
                return httpx.Response(200)
            prefix = url.params["prefix"]
            items = [{"name": n, "size": str(len(d))} for n, d in self.bucket.items() if n.startswith(prefix)]
            return httpx.Response(200, json={"items": items})
        if "/object/list/" in url.path:
            folder = url.path.rsplit("/", 1)[1]
            prefix = json.loads(request.content)["prefix"]
            level: dict[str, dict[str, object]] = {}
            for name, data in self.supabase.items():
                if not name.startswith(f"{folder}/{prefix}"):
                    continue
                head, _, tail = name.removeprefix(f"{folder}/{prefix}").partition("/")
                level[head] = {"name": head, "id": None} if tail else {
                    "name": head, "id": "x", "metadata": {"size": len(data), "mimetype": "image/png"}}
            return httpx.Response(200, json=list(level.values()))
        name = url.path.split("/object/")[1]
        return httpx.Response(200, content=self.supabase[name]) if name in self.supabase else httpx.Response(404)


def run(stores: Stores, *, apply: bool, folder: str = "frames") -> copy_media.Result:
    source = media.Media("http://sb", "key", media.MediaConfig())
    target = media.Media("http://sb", "key", media.MediaConfig(backend="gcs", bucket="bkt"), token=lambda: "t")
    return copy_media.copy_folder(stores.client(), source, target, "http://sb", "key", folder, apply)


FILES = {"frames/p1/s1/a.png": b"aaa", "frames/p1/s1/a.png.thumb.webp": b"t", "frames/p2/b.png": b"bb",
         "frames/p2/.emptyFolderPlaceholder": b"", "takes/p1/t.mp4": b"video"}


def test_a_dry_run_counts_and_writes_nothing():
    stores = Stores(FILES)
    result = run(stores, apply=False)
    assert result.found == 3 and len(result.missing) == 3 and not result.complete and stores.bucket == {}
    assert ("POST", "storage.googleapis.com") not in stores.methods


def test_applying_copies_every_nested_file_and_a_second_run_copies_nothing():
    stores = Stores(FILES)
    first = run(stores, apply=True)
    assert first.copied == 3 and first.complete
    assert stores.bucket["frames/p1/s1/a.png"] == b"aaa" and "takes/p1/t.mp4" not in stores.bucket
    second = run(stores, apply=True)
    assert (second.copied, second.present) == (0, 3) and second.complete
    assert not any(method == "DELETE" for method, _host in stores.methods)


def test_a_file_already_in_the_bucket_is_never_overwritten():
    stores = Stores(FILES, {"frames/p2/b.png": b"newer text"})
    result = run(stores, apply=True)
    assert result.differ == ["p2/b.png"] and stores.bucket["frames/p2/b.png"] == b"newer text" and result.complete


def test_a_file_that_cannot_be_read_leaves_the_move_incomplete():
    stores = Stores(FILES)
    handle = stores.handle
    def broken(r: httpx.Request) -> httpx.Response:
        return httpx.Response(500) if r.url.path.endswith("/frames/p2/b.png") else handle(r)

    stores.handle = broken  # type: ignore[method-assign]
    result = run(stores, apply=True)
    assert result.failed == ["p2/b.png"] and not result.complete and result.copied == 2


def test_it_asks_for_a_bucket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(copy_media._common, "load_env", lambda: None)
    monkeypatch.setenv("SUPABASE__URL", "http://sb")
    monkeypatch.setenv("SUPABASE__SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("FILES__GCS_BUCKET", "")
    assert copy_media.main([]) == 2
