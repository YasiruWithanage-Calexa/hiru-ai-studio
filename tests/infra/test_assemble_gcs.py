"""infra/assemble has no `hiru_ai`, so it carries its own copy of the Cloud Storage addresses (plan/2026-11-27 §4):
held equal to `hiru_ai/core/media.py` here. No ffmpeg and no network."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from hiru_ai.core import media
from tests.infra.test_assemble import load_app

PATH = "p1/තිරය 01/take.mp4"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = load_app()
    monkeypatch.setenv("SUPABASE__URL", "http://sb")
    monkeypatch.setenv("SUPABASE__SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("FILES__BACKEND", "gcs")
    monkeypatch.setenv("FILES__GCS_BUCKET", "bkt")
    monkeypatch.delenv("FILES__READ_FALLBACK", raising=False)
    monkeypatch.setattr(module, "_fetch_token", lambda: ("google-token", 10**12))
    return module


class Wire:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, app: Any, *answers: httpx.Response) -> None:
        self.seen: list[tuple[str, str, dict[str, str]]] = []
        self.answers = list(answers)
        for method in ("get", "post"):
            monkeypatch.setattr(app.httpx, method, self._call(method))

    def _call(self, method: str) -> Any:
        def call(url: str, **kw: Any) -> httpx.Response:
            self.seen.append((method, url, dict(kw.get("headers") or {})))
            answer = self.answers.pop(0)
            answer.request = httpx.Request(method.upper(), url)
            return answer

        return call


def test_the_addresses_equal_the_shared_module(app: Any):
    assert app.GCS == media.GCS and app.SCOPE == media.SCOPE and app.METADATA_TOKEN == media.METADATA_TOKEN
    assert app._object_url("bkt", "takes", PATH) == media.object_url("bkt", "takes", PATH)
    assert app._upload_url("bkt", "takes", PATH) == media.upload_url("bkt", "takes", PATH, once=False)


def test_a_take_is_downloaded_from_the_bucket_and_nothing_is_signed(app: Any, monkeypatch: pytest.MonkeyPatch,
                                                                    tmp_path: Any):
    wire = Wire(monkeypatch, app, httpx.Response(200, content=b"video"))
    assert open(app._input("takes", PATH, tmp_path), "rb").read() == b"video"
    [(method, url, headers)] = wire.seen
    assert method == "get" and url == f"{media.object_url('bkt', 'takes', PATH)}?alt=media"
    assert headers == {"Authorization": "Bearer google-token"}


def test_fallback_reads_a_missing_take_from_supabase(app: Any, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FILES__READ_FALLBACK", "true")
    wire = Wire(monkeypatch, app, httpx.Response(404), httpx.Response(200, content=b"old"))
    assert app._download("takes", "p/t.mp4") == b"old"
    assert wire.seen[1][1] == "http://sb/storage/v1/object/takes/p/t.mp4"


def test_without_fallback_a_missing_take_is_an_error(app: Any, monkeypatch: pytest.MonkeyPatch):
    wire = Wire(monkeypatch, app, httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        app._download("takes", "p/t.mp4")
    assert len(wire.seen) == 1


def test_a_still_is_uploaded_to_the_bucket_and_overwrites(app: Any, monkeypatch: pytest.MonkeyPatch):
    wire = Wire(monkeypatch, app, httpx.Response(200))
    app._upload("takes", "p/t.poster.webp", b"webp", "image/webp")
    [(method, url, headers)] = wire.seen
    assert method == "post" and url == media.upload_url("bkt", "takes", "p/t.poster.webp", once=False)
    assert headers["Content-Type"] == "image/webp"


def test_a_backend_that_is_not_set_up_refuses(app: Any, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FILES__GCS_BUCKET", "")
    with pytest.raises(app.HTTPException):
        app._download("takes", "p/t.mp4")
