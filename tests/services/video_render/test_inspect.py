"""plan/2026-11-21 D8 and D2 for video_render: a take's length and still are read ONCE, when it is stored; a reference
picture crosses the internet once per machine; each job logs one storage line."""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from video_render.engine import render
from video_render.runtime import assemble
from video_render.runtime.store import Store

from hiru_ai.core.file_store import CachedFiles
from tests.services.video_render.conftest import USER, FakeStore, config, render_row

_CLIENT = httpx.Client  # the real one: the tests below patch `httpx.Client` for assemble.inspect


def run(store: FakeStore, row: dict[str, Any], **cfg: Any) -> str:
    return render.run_render(store, config(**cfg), row, job_id="job-1", actor=str(USER))


class Assemble:
    """infra/assemble stood in for: answers /inspect and records what it was asked."""

    def __init__(self, answer: dict[str, Any] | None = None, status: int = 200) -> None:
        self.answer = answer if answer is not None else {"duration_s": 8.04, "poster_path": "", "error": ""}
        self.status = status
        self.calls: list[tuple[str, dict, dict]] = []

    def client(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.calls.append((request.url.path, body, dict(request.headers)))
            answer = dict(self.answer)
            if answer.get("poster_path") is None:
                answer["poster_path"] = body["out_path"]
            return httpx.Response(self.status, json=answer)

        return _CLIENT(transport=httpx.MockTransport(handle))


def test_a_stored_take_is_inspected_once_and_its_length_and_still_saved(monkeypatch: pytest.MonkeyPatch):
    service = Assemble({"duration_s": 8.04, "poster_path": None, "error": ""})
    monkeypatch.setattr(assemble.httpx, "Client", lambda **kw: service.client())
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, assemble_url="http://localhost:8209", assemble_secret="dev") == "done"
    (take,) = store.takes
    path = take["storage_path"]
    assert take["duration_s"] == 8.04 and take["poster_path"] == assemble.poster_path(path)
    ((route, body, headers),) = service.calls
    assert route == "/inspect" and body == {"bucket": "takes", "path": path, "out_path": assemble.poster_path(path)}
    assert headers["x-assemble-secret"] == "dev" and "authorization" not in headers, "no token for a local port"


def test_without_assemble_or_when_it_fails_the_take_is_still_done(monkeypatch: pytest.MonkeyPatch):
    row = render_row()
    store = FakeStore(row)
    assert run(store, row) == "done" and store.takes[0]["duration_s"] is None, "no ASSEMBLE__URL: nothing asked"

    service = Assemble(status=500)
    monkeypatch.setattr(assemble.httpx, "Client", lambda **kw: service.client())
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, assemble_url="http://localhost:8209") == "done"
    assert store.takes[0]["duration_s"] is None and store.rows[row["id"]]["status"] == "done"


def test_the_poster_path_waits_for_schema_v24_but_the_length_is_saved():
    patched: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        fields = json.loads(request.content)
        patched.append(fields)
        if "poster_path" in fields:
            return httpx.Response(400, json={"message": "Could not find the 'poster_path' column"})
        return httpx.Response(204)

    from video_render.runtime.rest import Rest

    store = Store(Rest("http://sb", "k", client=httpx.Client(transport=httpx.MockTransport(handle))))
    store.set_take("t1", {"duration_s": 8.0, "poster_path": "p/t.poster.webp"})
    assert patched == [{"duration_s": 8.0, "poster_path": "p/t.poster.webp"}, {"duration_s": 8.0}]


def test_on_cloud_run_the_call_carries_an_id_token_from_the_metadata_server(monkeypatch: pytest.MonkeyPatch):
    service = Assemble()
    monkeypatch.setattr(assemble, "_id_token", lambda audience: f"token-for-{audience}")
    cfg = config(assemble_url="https://assemble.run.app", assemble_secret="s")
    assert assemble.inspect(cfg, "takes", "p/t.mp4", client=service.client()) == {"duration_s": 8.04}
    assert service.calls[0][2]["authorization"] == "Bearer token-for-https://assemble.run.app"


def test_the_store_reads_references_through_the_cache_and_keeps_the_take():
    downloads: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            downloads.append(request.url.path)
            return httpx.Response(200, content=b"\x89PNG sheet")
        return httpx.Response(200, json={})

    from video_render.runtime.rest import Rest

    store = Store(Rest("http://sb", "k", client=httpx.Client(transport=httpx.MockTransport(handle))))
    assert isinstance(store.files, CachedFiles)
    for _ in range(3):
        assert store.download("references", "p/sheet.png") == b"\x89PNG sheet"
    store.upload("takes", "p/s/t.mp4", b"video", "video/mp4")
    assert store.download("takes", "p/s/t.mp4") == b"video"
    assert downloads == ["/storage/v1/object/references/p/sheet.png"]
    assert store.files.summary() == "storage: 1 from Supabase (0.0 MB), 3 from disk"
