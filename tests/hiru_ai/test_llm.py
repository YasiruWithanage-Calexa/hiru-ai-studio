"""The model door (ADR 0003): what goes on the wire, tokens counted, streaming, fallbacks, absent key.

The real `ChatOpenAI` runs here, on top of an httpx mock transport: no socket is opened, so the checks cover the
actual request bytes and response parsing, never a network service (CLAUDE.md "Tests never call OpenAI").
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from hiru_ai.core import llm as door
from hiru_ai.core import models as models_mod
from hiru_ai.core.errors import ManifestError, ModelUnavailable
from hiru_ai.core.settings import AISettings, OpenAISettings
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.core.usage import UsageCallback

USAGE = {"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280,
         "prompt_tokens_details": {"cached_tokens": 1024}}
SYSTEM = "You are the cinematographer. " + "Static craft rules. " * 50
USER = "Scene 3: Kamala at the stove."


class Shot(BaseModel):
    title: str
    seconds: int


def settings(key: str = "sk-test") -> AISettings:
    return AISettings(openai=OpenAISettings(api_key=key))  # type: ignore[arg-type]


def completion(content: str) -> dict[str, Any]:
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "gpt-5-mini-2026",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": USAGE}


def sse(chunks: list[dict[str, Any]]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


class Wire:
    """An httpx client that records every request and answers from `respond`."""

    def __init__(self, respond: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond or (lambda request: httpx.Response(200, json=completion('{"title": "T", "seconds": 6}')))
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def body(self, n: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[n].content)  # type: ignore[no-any-return]


def messages() -> list[tuple[str, str]]:
    return [("system", SYSTEM), ("user", USER)]


# ── no key ───────────────────────────────────────────────────────────────────────────────────


def test_without_a_key_the_door_says_so_and_nothing_is_built():
    with pytest.raises(ModelUnavailable):
        door.get_llm("high", settings=settings(""))
    assert door.models_enabled(settings("")) is False and door.models_enabled(settings()) is True


def test_an_unknown_tier_is_a_manifest_error_not_a_key_error():
    with pytest.raises(ManifestError, match="unknown model tier"):
        door.get_llm("smart", settings=settings())


# ── the request ──────────────────────────────────────────────────────────────────────────────


def test_a_structured_call_sends_a_strict_json_schema_and_the_messages_unchanged():
    wire = Wire()
    out = door.get_structured("high", Shot, settings=settings(), http_client=wire.client).invoke(messages())
    assert out == Shot(title="T", seconds=6)
    request = wire.requests[0]
    assert request.url.path.endswith("/chat/completions")
    body = wire.body()
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert set(body["response_format"]["json_schema"]["schema"]["properties"]) == {"title", "seconds"}
    # OpenAI's prompt cache keys on the leading bytes: the system text must arrive exactly as given
    assert body["messages"] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
    assert body["model"] == "gpt-5" and body["reasoning_effort"] == "medium"


@pytest.mark.parametrize(("tier", "model", "effort"), [("ultra", "gpt-5", "high"), ("medium", "gpt-5-mini", "low"),
                                                       ("low", "gpt-5-nano", "minimal")])
def test_each_tier_sends_its_model_and_reasoning_effort(tier: str, model: str, effort: str):
    wire = Wire()
    door.get_structured(tier, Shot, settings=settings(), http_client=wire.client).invoke(messages())
    assert (wire.body()["model"], wire.body()["reasoning_effort"]) == (model, effort)


def test_model_ids_come_from_settings_not_code():
    wire = Wire()
    cfg = AISettings(openai=OpenAISettings(api_key="k", model_high="gpt-next", effort_high=""))  # type: ignore[arg-type]
    door.get_structured("high", Shot, settings=cfg, http_client=wire.client).invoke(messages())
    assert wire.body()["model"] == "gpt-next" and "reasoning_effort" not in wire.body()


# ── tokens ───────────────────────────────────────────────────────────────────────────────────


def test_tokens_are_counted_exactly_as_the_services_count_them_today():
    wire, rows = Wire(), []
    cb = UsageCallback(rows.append, "director.reply")
    door.get_structured("high", Shot, settings=settings(), http_client=wire.client).invoke(
        messages(), config={"callbacks": [cb]})
    assert rows == [{"phase": "director.reply", "model": "gpt-5-mini-2026", "input_tokens": 1200,
                     "cached_input_tokens": 1024, "output_tokens": 80}]


def test_a_streamed_call_still_reports_its_tokens():
    final = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-5-mini-2026",
             "choices": [], "usage": USAGE}
    chunks = [{"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-5-mini-2026",
               "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
              for text in ("Hel", "lo")] + [final]
    wire = Wire(lambda r: httpx.Response(200, content=sse(chunks), headers={"content-type": "text/event-stream"}))
    rows: list[dict[str, Any]] = []
    model = door.get_llm("medium", settings=settings(), http_client=wire.client)
    text = "".join(c.content for c in model.stream(messages(), config={"callbacks": [UsageCallback(rows.append, "p")]})
                   if isinstance(c.content, str))
    assert text == "Hello"
    assert wire.body()["stream_options"] == {"include_usage": True}
    assert [(r["input_tokens"], r["cached_input_tokens"], r["output_tokens"]) for r in rows] == [(1200, 1024, 80)]


def test_a_sink_that_fails_never_fails_the_call():
    wire = Wire()

    def broken(row: dict[str, Any]) -> None:
        raise RuntimeError("table is down")

    out = door.get_structured("high", Shot, settings=settings(), http_client=wire.client).invoke(
        messages(), config={"callbacks": [UsageCallback(broken, "p")]})
    assert out.seconds == 6


# ── retries and fallbacks ────────────────────────────────────────────────────────────────────


def test_a_server_error_is_retried_then_succeeds():
    calls = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": {"message": "boom", "type": "server_error"}})
        return httpx.Response(200, json=completion('{"title": "T", "seconds": 6}'))

    wire = Wire(respond)
    out = door.get_structured("low", Shot, settings=settings(), http_client=wire.client).invoke(messages())
    assert out.title == "T" and calls["n"] == 2


def test_a_tier_with_fallbacks_tries_the_next_tier_after_failing(monkeypatch: pytest.MonkeyPatch):
    real = models_mod.load_models()
    custom = real.model_copy(update={"tiers": {**real.tiers, "high": real.tiers["high"].model_copy(
        update={"fallbacks": ["medium"]})}})
    monkeypatch.setattr(models_mod, "load_models", lambda *a, **k: custom)
    first = ScriptedChatModel(replies=[RuntimeError("down")], model_name="high-model")
    second = ScriptedChatModel(replies=[Shot(title="from medium", seconds=4)], model_name="medium-model")
    with door.use_models(lambda tier: {"high": first, "medium": second}[tier.name]):
        out = door.get_structured("high", Shot, settings=settings("")).invoke(messages())
    assert out.title == "from medium"


def test_a_fallback_naming_an_unknown_tier_is_refused_at_load(tmp_path: Any):
    bad = tmp_path / "models.yaml"
    bad.write_text("tiers:\n  a: { model: model_low, fallbacks: [zzz] }\nembed: { model: embedding_model, dimensions: "
                   "embedding_dimensions }\nimage: { model: model_image }\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown tier"):
        models_mod.load_models.__wrapped__(bad)  # type: ignore[attr-defined]


# ── test doubles ─────────────────────────────────────────────────────────────────────────────


def test_use_models_replaces_the_door_inside_the_block_only():
    fake = ScriptedChatModel(replies=[Shot(title="x", seconds=1)])
    with door.use_models(fake):
        assert door.models_enabled(settings("")) is True
        assert door.get_structured("low", Shot, settings=settings("")).invoke(messages()) == Shot(title="x", seconds=1)
    assert door.models_enabled(settings("")) is False


# ── embeddings ───────────────────────────────────────────────────────────────────────────────


class FakeEmbeddingsAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        from types import SimpleNamespace

        self.calls.append(kw)
        order = reversed(range(len(kw["input"])))
        data = [SimpleNamespace(index=i, embedding=[float(i)] * kw["dimensions"]) for i in order]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=7 * len(kw["input"])))


def test_embeddings_report_their_tokens_and_keep_input_order():
    from types import SimpleNamespace

    api, rows = FakeEmbeddingsAPI(), []
    client = SimpleNamespace(embeddings=api)
    emb = door.get_embeddings("doc_ingest.embed", rows.append, settings=settings(), client=client)
    vectors = emb.embed_documents(["a", "b"])
    assert [v[0] for v in vectors] == [0.0, 1.0]  # sorted by index, not by arrival
    assert api.calls[0]["model"] == "text-embedding-3-large" and api.calls[0]["dimensions"] == 1536
    assert rows == [{"phase": "doc_ingest.embed", "model": "text-embedding-3-large", "input_tokens": 14,
                     "cached_input_tokens": 0, "output_tokens": 0}]


def test_embeddings_without_a_key_say_so():
    with pytest.raises(ModelUnavailable):
        door.get_embeddings("p", None, settings=settings("")).embed_query("x")
