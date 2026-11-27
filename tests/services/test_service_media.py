"""Every function's storage calls follow `FILES__BACKEND` (plan/2026-11-27 §4): a function that kept its own Supabase
address would read and write the wrong store once the files move. No network."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from hiru_ai.core import media

SERVICES = Path(__file__).resolve().parents[2] / "src" / "services"
REST = sorted(p.parent.parent.name for p in SERVICES.glob("*/*/runtime/rest.py"))


def _module(service: str, name: str) -> Any:
    path = str(SERVICES / service)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(f"{service}.runtime.{name}")


@pytest.fixture
def gcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILES__BACKEND", "gcs")
    monkeypatch.setenv("FILES__GCS_BUCKET", "bkt")
    monkeypatch.setattr(media, "_TOKEN", lambda: "google-token")


def _client(seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"bytes")

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_every_service_with_a_storage_client_is_checked():
    assert len(REST) >= 11


@pytest.mark.parametrize("service", REST)
def test_a_download_reads_the_bucket(service: str, gcs: None):
    seen: list[httpx.Request] = []
    rest = _module(service, "rest").Rest("http://sb", "key", _client(seen))
    assert rest.download("documents", "p/d.txt") == b"bytes"
    assert seen[0].url.host == "storage.googleapis.com"


@pytest.mark.parametrize("service", ["frame_render", "video_render"])
def test_a_picture_or_take_is_written_once(service: str, gcs: None):
    seen: list[httpx.Request] = []
    rest = _module(service, "rest").Rest("http://sb", "key", _client(seen))
    rest.upload("takes", "p/t.mp4", b"video", "video/mp4")
    assert seen[0].url.params["ifGenerationMatch"] == "0" and seen[0].content == b"video"


@pytest.mark.parametrize("service", ["frame_render", "video_render"])
def test_our_own_retry_of_a_write_that_landed_is_success(service: str, gcs: None, monkeypatch: pytest.MonkeyPatch):
    module = _module(service, "rest")
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    answers = [httpx.Response(503), httpx.Response(412)]
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: answers.pop(0)))
    module.Rest("http://sb", "key", client).upload("takes", "p/t.mp4", b"video", "video/mp4")
    assert answers == []


def test_a_first_write_that_meets_an_existing_file_fails(gcs: None):
    module = _module("frame_render", "rest")
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(412)))
    with pytest.raises(httpx.HTTPStatusError):
        module.Rest("http://sb", "key", client).upload("frames", "p/f.png", b"png", "image/png")


def test_doc_ingest_reads_and_overwrites_in_the_bucket(gcs: None):
    seen: list[httpx.Request] = []
    store = _module("doc_ingest", "store").Store("http://sb", "key", _client(seen))
    store.download("documents", "p/d.pdf")
    store.upload_text("documents", "p/d.txt", "තිරය")
    assert [r.url.host for r in seen] == ["storage.googleapis.com"] * 2
    assert "ifGenerationMatch" not in str(seen[1].url) and seen[1].content == "තිරය".encode()


def test_no_service_names_the_supabase_storage_address_itself():
    named = [str(p.relative_to(SERVICES)) for p in SERVICES.rglob("*.py")
             if "storage/v1" in p.read_text(encoding="utf-8")]
    assert named == []
