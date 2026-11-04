"""The Supabase, storage and image adapters, over a mocked HTTP transport (no socket, no key).

Where a legacy service store does the same job, the adapter is held to the requests the legacy store makes
(method, URL, query, body, in order): the same bytes reach PostgREST, so the port can replace the store in Phase 6.
"""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest

from hiru_ai.adapters import images, storage, supabase_rest
from hiru_ai.adapters.supabase_rest import Rest
from hiru_ai.core.ports import ImageFailed, ImageRefused, Reference

URL = "https://example.supabase.co"
KEY = "service-key"


class Recorder:
    """A transport that answers from a script and remembers every request."""

    def __init__(self, *replies: httpx.Response | Any) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else (self.replies[0] if self.replies else None)
        if isinstance(reply, Exception):
            raise reply
        return reply if reply is not None else httpx.Response(200, json=[])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def seen(self) -> list[tuple[str, str, str, Any]]:
        return [(r.method, r.url.path, str(r.url.query, "utf-8"), json.loads(r.content) if r.content else None)
                for r in self.requests]


def rest(rec: Recorder) -> Rest:
    return Rest(URL, KEY, rec.client())


# ── Rest ───────────────────────────────────────────────────────────────────────────────────


def test_every_request_carries_the_service_role_key():
    rec = Recorder(httpx.Response(200, json=[{"id": 1}]))
    assert rest(rec).select("scenes", {"select": "id"}) == [{"id": 1}]
    assert rec.requests[0].headers["apikey"] == KEY and rec.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_first_asks_for_one_row_and_answers_none_for_no_rows():
    rec = Recorder(httpx.Response(200, json=[]))
    assert rest(rec).first("scenes", {"id": "eq.1"}) is None and "limit=1" in rec.seen()[0][2]


def test_a_bulk_insert_goes_in_batches():
    rec = Recorder(httpx.Response(201))
    rest(rec).insert("chunks", [{"i": n} for n in range(450)])
    assert [len(body) for *_, body in rec.seen()] == [200, 200, 50]


def test_an_upsert_merges_on_the_key_it_is_given():
    rec = Recorder(httpx.Response(201))
    rest(rec).upsert("shots", [{"id": "a"}], on_conflict="id")
    assert rec.requests[0].headers["prefer"] == "resolution=merge-duplicates" and "on_conflict=id" in rec.seen()[0][2]


def test_a_claim_returns_the_rows_it_changed():
    rec = Recorder(httpx.Response(200, json=[{"id": "f"}]))
    claimed = rest(rec).claim("first_frames", {"id": "eq.f", "status": "eq.queued"}, {"status": "running"})
    assert claimed == [{"id": "f"}]
    assert rec.requests[0].headers["prefer"] == "return=representation"


def test_an_error_says_what_postgrest_said():
    rec = Recorder(httpx.Response(400, text='{"message":"column x does not exist"}'))
    with pytest.raises(httpx.HTTPStatusError, match="column x does not exist"):
        rest(rec).select("scenes", {})


# ── parity with the legacy stores ──────────────────────────────────────────────────────────


def test_save_plan_sends_the_requests_the_directors_store_sends():
    from director_chat.runtime.rest import Rest as LegacyRest
    from director_chat.runtime.store import Store as LegacyStore

    scene_id = uuid4()
    shots = [{"id": "s1", "number": 1}, {"id": "s2", "number": 2}]
    lines = [{"id": "l1", "text": "a", "source_text": "x"}, {"id": "l2", "text": "b"}]
    args = (scene_id, shots, ["gone"], lines, {"status": "split"}, ["lx"])
    old, new = Recorder(httpx.Response(200, json=[])), Recorder(httpx.Response(200, json=[]))
    LegacyStore(LegacyRest(URL, KEY, old.client())).save_plan(*args)
    supabase_rest.SupabaseScenes(rest(new)).save_plan(*args)
    assert new.seen() == old.seen() and len(old.requests) == 5


def test_replace_shots_sends_the_requests_the_splitters_store_sends():
    from script_split.runtime.rest import Rest as LegacyRest
    from script_split.runtime.store import Store as LegacyStore

    scene_id = uuid4()
    args = (scene_id, [{"id": "s1", "scene_id": str(scene_id)}], [{"id": "l1", "text": "a"}], {"status": "split"})
    old, new = Recorder(httpx.Response(200, json=[])), Recorder(httpx.Response(200, json=[]))
    LegacyStore(LegacyRest(URL, KEY, old.client())).replace_shots(*args)
    supabase_rest.SupabaseScenes(rest(new)).replace_shots(*args)
    assert new.seen() == old.seen() and [m for m, *_ in old.seen()] == ["DELETE", "POST", "POST", "PATCH"]


def test_scenes_are_read_for_one_production_with_their_episode():
    rec = Recorder(httpx.Response(200, json=[{"id": "a"}]))
    pid = uuid4()
    supabase_rest.SupabaseScenes(rest(rec)).scenes(pid, ["a", "b"])
    query = rec.seen()[0][2]
    assert f"production_id=eq.{pid}" in query and "id=in.%28a%2Cb%29" in query and "episode%3Aepisodes" in query


def test_no_scene_ids_means_no_request_not_all_scenes():
    rec = Recorder(httpx.Response(200, json=[{"id": "a"}]))
    assert supabase_rest.SupabaseScenes(rest(rec)).scenes(uuid4(), []) == [] and rec.requests == []


def test_a_prompt_version_taken_meanwhile_is_retried_once_with_the_next_number():
    rec = Recorder(httpx.Response(409), httpx.Response(200, json=[{"version": 3}]), httpx.Response(201),
                   httpx.Response(204))
    supabase_rest.SupabaseScenes(rest(rec)).add_prompt({"shot_id": "s1", "version": 2})
    posts = [b for m, p, q, b in rec.seen() if m == "POST"]
    assert [b[0]["version"] for b in posts] == [2, 4] and rec.seen()[-1][0] == "PATCH"


def test_canon_is_written_as_entity_then_version_then_the_pointer():
    rec = Recorder(httpx.Response(201))
    supabase_rest.SupabaseCanon(rest(rec)).create_entity({"id": "e1"}, {"id": "v1"})
    assert [(m, p.rsplit("/", 1)[-1]) for m, p, *_ in rec.seen()] == [
        ("POST", "canon_entities"), ("POST", "canon_versions"), ("PATCH", "canon_entities")]
    assert rec.seen()[-1][3] == {"current_version_id": "v1"}


def test_a_scene_is_written_after_its_old_shots_and_lines_go():
    rec = Recorder(httpx.Response(201))
    supabase_rest.SupabaseStructure(rest(rec)).write_scene({"id": "sc"}, [{"id": "l1"}])
    assert [m for m, *_ in rec.seen()] == ["POST", "DELETE", "DELETE", "POST"]


# ── search ─────────────────────────────────────────────────────────────────────────────────


def test_chunks_are_matched_by_the_runs_scope_and_the_embedding_is_a_vector_literal():
    rec = Recorder(httpx.Response(200, json=[{"id": "c"}]))
    pid = uuid4()
    out = supabase_rest.SupabaseSearch(rest(rec)).chunks(
        query="boat", embedding=[0.5, 0.25], production_id=pid, corpora=["production_docs"], document_ids=None, k=4)
    assert out == [{"id": "c"}]
    (_, path, _, body) = rec.seen()[0]
    assert path.endswith("/rpc/match_chunks") and body == {
        "query_text": "boat", "query_embedding": "[0.5,0.25]", "p_production_id": str(pid),
        "p_corpora": ["production_docs"], "p_document_ids": None, "match_count": 4}


def test_a_technique_lookup_that_fails_answers_with_none():
    rec = Recorder(httpx.Response(500, text="boom"))
    assert supabase_rest.SupabaseSearch(rest(rec)).techniques("dread", None) == []


# ── storage ────────────────────────────────────────────────────────────────────────────────


def files(rec: Recorder) -> tuple[storage.SupabaseFiles, list[float]]:
    pauses: list[float] = []
    return storage.SupabaseFiles(rest(rec), sleep=pauses.append), pauses


def test_a_dropped_download_is_retried_with_a_doubling_pause():
    rec = Recorder(httpx.Response(503), httpx.ConnectError("reset"), httpx.Response(200, content=b"bytes"))
    f, pauses = files(rec)
    assert f.download("references", "a.png") == b"bytes" and pauses == [1.0, 2.0]


def test_a_missing_object_is_not_retried():
    rec = Recorder(httpx.Response(404, text="not found"))
    f, pauses = files(rec)
    with pytest.raises(httpx.HTTPStatusError):
        f.download("references", "a.png")
    assert len(rec.requests) == 1 and pauses == []


def test_a_download_that_keeps_failing_gives_up_after_four_tries():
    rec = Recorder(httpx.Response(500))
    f, pauses = files(rec)
    with pytest.raises(httpx.HTTPStatusError):
        f.download("references", "a.png")
    assert len(rec.requests) == 4 and pauses == [1.0, 2.0, 4.0]


def test_an_upload_overwrites_so_a_retried_job_leaves_one_object():
    rec = Recorder(httpx.Response(200))
    f, _ = files(rec)
    f.upload("frames", "p/f.png", b"png", "image/png")
    req = rec.requests[0]
    assert req.url.path.endswith("/object/frames/p/f.png") and req.headers["x-upsert"] == "true"
    assert req.headers["content-type"] == "image/png" and req.content == b"png"


def test_documents_text_is_decoded_as_utf8():
    rec = Recorder(httpx.Response(200, content="බෝට්ටුව".encode()))
    f, _ = files(rec)
    assert supabase_rest.SupabaseDocs(rest(rec), f).text("p/doc.txt") == "බෝට්ටුව"


def test_a_usage_row_that_cannot_be_written_never_fails_the_work():
    rec = Recorder(httpx.Response(500, text="down"))
    supabase_rest.usage_sink(rest(rec))({"phase": "x", "model": "m"})


def test_the_ports_for_a_run_are_all_there():
    settings = SimpleNamespace(supabase=SimpleNamespace(url=URL, service_role_key=SimpleNamespace(
        get_secret_value=lambda: KEY)))
    ports = supabase_rest.build_ports(settings, client=Recorder().client())  # type: ignore[arg-type]
    assert all(getattr(ports, n) is not None for n in ("scenes", "canon", "structure", "docs", "search", "files"))


# ── images ─────────────────────────────────────────────────────────────────────────────────


class Images:
    """The slice of the OpenAI SDK the adapter uses."""

    def __init__(self, *, fail: Exception | None = None, empty: bool = False) -> None:
        self.fail, self.empty, self.calls = fail, empty, []

    def _answer(self, kind: str, **kw: Any) -> Any:
        self.calls.append((kind, kw))
        if self.fail:
            raise self.fail
        data = [] if self.empty else [SimpleNamespace(b64_json=base64.b64encode(b"PNG").decode())]
        return SimpleNamespace(data=data, usage=SimpleNamespace(input_tokens=11, output_tokens=22))

    def generate(self, **kw: Any) -> Any:
        return self._answer("generate", **kw)

    def edit(self, **kw: Any) -> Any:
        return self._answer("edit", **kw)


def painter(sdk: Images, rows: list[dict[str, Any]] | None = None) -> images.OpenAIImages:
    return images.OpenAIImages(SimpleNamespace(images=sdk), model="gpt-image-2", quality="medium",
                               sink=(rows.append if rows is not None else None))


def test_without_references_it_generates_at_the_aspect_size_and_records_its_tokens():
    sdk, rows = Images(), []
    picture = painter(sdk, rows)("a harbour", "16:9", [])
    assert picture.data == b"PNG" and (picture.input_tokens, picture.output_tokens) == (11, 22)
    assert sdk.calls[0][0] == "generate" and sdk.calls[0][1]["size"] == "1536x1024"
    assert rows == [{"phase": "frame_render.image", "model": "gpt-image-2", "input_tokens": 11,
                     "cached_input_tokens": 0, "output_tokens": 22}]


def test_with_references_it_edits_and_sends_them_in_the_order_given():
    sdk = Images()
    painter(sdk)("a harbour", "9:16", [Reference("one", b"1"), Reference("two", b"2")])
    kind, kw = sdk.calls[0]
    assert kind == "edit" and kw["size"] == "1024x1536"
    assert [name for name, *_ in kw["image"]] == ["reference-1.png", "reference-2.png"]
    assert [data for _, data, _ in kw["image"]] == [b"1", b"2"]


def test_a_moderation_block_is_a_refusal():
    class Blocked(Exception):
        code = "moderation_blocked"

    with pytest.raises(ImageRefused, match="declined"):
        painter(Images(fail=Blocked("no")))("a harbour", "16:9", [])


def test_a_400_that_talks_about_safety_is_a_refusal_and_any_other_failure_is_not():
    class Bad(Exception):
        status_code = 400

    with pytest.raises(ImageRefused):
        painter(Images(fail=Bad("blocked by the safety system")))("p", "16:9", [])
    with pytest.raises(ImageFailed):
        painter(Images(fail=Bad("invalid size")))("p", "16:9", [])
    with pytest.raises(ImageFailed):
        painter(Images(fail=TimeoutError("slow")))("p", "16:9", [])


def test_an_answer_with_no_picture_is_a_failure():
    with pytest.raises(ImageFailed, match="no image"):
        painter(Images(empty=True))("p", "16:9", [])


def test_no_key_means_no_painter():
    from hiru_ai.core.errors import ModelUnavailable

    with pytest.raises(ModelUnavailable):
        images.build()


def test_the_legacy_painter_and_the_adapter_agree_on_what_counts_as_a_refusal():
    from frame_render.engine import image as legacy

    class Coded(Exception):
        code = "content_policy_violation"

    class Blocked(Exception):
        status_code = 400

    for exc in (Coded("x"), Blocked("moderation said no"), Blocked("invalid size"), ValueError("fine")):
        assert images._refused(exc) == legacy._refused(exc)
