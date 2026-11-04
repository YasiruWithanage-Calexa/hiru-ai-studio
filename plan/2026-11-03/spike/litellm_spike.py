"""Phase 0 spike (plan/2026-11-03 §7): does LiteLLM behind LangChain keep what the services rely on?

Throwaway: it talks to a local fake of the OpenAI chat endpoint, never to OpenAI, so it costs nothing
and needs no key. It sends the same call three ways (the `openai` SDK as the services do today,
`ChatOpenAI`, `ChatLiteLLMRouter`) and compares what went on the wire and what the usage callback saw.

    <venv with requirements/hiru_ai.txt + langchain-openai>/python litellm_spike.py

Checks (each prints PASS/FAIL):
  1. strict `json_schema` structured output reaches the wire, schema intact
  2. the messages are byte-identical (the cacheable prefix is not touched), `reasoning_effort` passes through
  3. the usage numbers a LiteLLM callback gets equal today's `token_usage` row
  4. a failing first deployment falls back to the next group, and retries are counted
  5. the embedding call goes through the router with the configured model and dimensions
  6. (fallback) `ChatOpenAI` gives the same wire call and usage, so `get_llm` can return it instead
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from pydantic import BaseModel

SEEN: list[dict[str, Any]] = []
FAIL_MODELS: set[str] = set()
USAGE = {"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280,
         "prompt_tokens_details": {"cached_tokens": 1024}, "completion_tokens_details": {"reasoning_tokens": 40}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"path": self.path, "body": body})
        model = body.get("model", "")
        if self.path.endswith("/embeddings"):
            n = len(body["input"]) if isinstance(body["input"], list) else 1
            data = [{"object": "embedding", "index": i, "embedding": [0.1] * int(body.get("dimensions", 8))}
                    for i in range(n)]
            out = {"object": "list", "model": model, "data": data, "usage": {"prompt_tokens": 7, "total_tokens": 7}}
        elif model in FAIL_MODELS:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"boom","type":"server_error"}}')
            return
        else:
            out = {"id": "c1", "object": "chat.completion", "created": 1, "model": model,
                   "choices": [{"index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": json.dumps({"title": "T", "seconds": 6})}}],
                   "usage": USAGE}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Shot(BaseModel):
    title: str
    seconds: int


SYSTEM = "You are the cinematographer. " + "Static craft rules. " * 200  # a long, byte-stable prefix
USER = "Scene 3: Kamala at the stove."
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    schema = Shot.model_json_schema()

    # ── today: the openai SDK, as runtime/llm.py calls it ─────────────────────────────────────
    from openai import OpenAI

    client = OpenAI(api_key="x", base_url=base, max_retries=0)
    resp = client.chat.completions.create(
        model="gpt-5", reasoning_effort="medium",
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        response_format={"type": "json_schema", "json_schema": {"name": "shot", "schema": schema, "strict": True}})
    today_row = {"input_tokens": resp.usage.prompt_tokens,
                 "cached_input_tokens": resp.usage.prompt_tokens_details.cached_tokens,
                 "output_tokens": resp.usage.completion_tokens}
    direct = SEEN[-1]["body"]

    # ── the router ──────────────────────────────────────────────────────────────────────────
    import litellm
    from langchain_litellm import ChatLiteLLMRouter, LiteLLMEmbeddingsRouter
    from litellm import Router
    from litellm.integrations.custom_logger import CustomLogger

    rows: list[dict[str, Any]] = []

    class Usage(CustomLogger):
        def log_success_event(self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any) -> None:
            u = response_obj.usage
            details = getattr(u, "prompt_tokens_details", None)
            rows.append({"input_tokens": u.prompt_tokens,
                         "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
                         "output_tokens": u.completion_tokens, "model": kwargs.get("model")})

    litellm.callbacks = [Usage()]
    router = Router(
        model_list=[
            {"model_name": "openai-smart",
             "litellm_params": {"model": "openai/gpt-5", "api_key": "x", "api_base": base, "max_retries": 0}},
            {"model_name": "openai-fast",
             "litellm_params": {"model": "openai/gpt-5-mini", "api_key": "x", "api_base": base, "max_retries": 0}},
            {"model_name": "openai-embed",
             "litellm_params": {"model": "openai/text-embedding-3-large", "api_key": "x", "api_base": base}}],
        fallbacks=[{"openai-smart": ["openai-fast"]}], num_retries=1, timeout=30)
    # a per-call setting such as reasoning_effort goes in model_kwargs (a bare keyword is silently dropped)
    llm = ChatLiteLLMRouter(router=router, model_name="openai-smart", model_kwargs={"reasoning_effort": "medium"})
    structured = llm.with_structured_output(Shot, method="json_schema", strict=True)
    out = structured.invoke([("system", SYSTEM), ("user", USER)])
    via = next(s["body"] for s in reversed(SEEN) if s["path"].endswith("/chat/completions"))
    litellm.flush_cache() if hasattr(litellm, "flush_cache") else None

    rf = via.get("response_format", {})
    js = rf.get("json_schema", {})
    check("1 strict json_schema on the wire", rf.get("type") == "json_schema" and js.get("strict") is True,
          f"type={rf.get('type')} strict={js.get('strict')} name={js.get('name')}")
    check("1 schema properties intact", set(js.get("schema", {}).get("properties", {})) == {"title", "seconds"}
          and js["schema"].get("additionalProperties") is False, f"keys={sorted(js.get('schema', {}).get('properties', {}))}")
    check("1 the parsed answer is the typed model", isinstance(out, Shot) and out.seconds == 6, repr(out))
    check("2 messages identical to the direct call", via["messages"] == direct["messages"],
          f"{len(json.dumps(via['messages']))} bytes")
    check("2 reasoning_effort passes through", via.get("reasoning_effort") == "medium", str(via.get("reasoning_effort")))
    check("2 no extra fields change the cache key", set(via) - set(direct) <= {"stream", "extra_body"},
          f"extra={sorted(set(via) - set(direct))}")

    # callbacks run on a worker thread: wait for it
    for _ in range(50):
        if rows:
            break
        threading.Event().wait(0.1)
    got = rows[0] if rows else {}
    check("3 usage callback equals today's token_usage row",
          {k: got.get(k) for k in today_row} == today_row, f"callback={got} today={today_row}")

    # ── fallback and retries ────────────────────────────────────────────────────────────────
    FAIL_MODELS.add("gpt-5")
    before = len(SEEN)
    try:
        llm.with_structured_output(Shot, method="json_schema", strict=True).invoke([("user", "hi")])
        models = [s["body"]["model"] for s in SEEN[before:]]
        check("4 falls back to the next group after retrying", models[-1] == "gpt-5-mini" and models.count("gpt-5") >= 2,
              f"calls={models}")
    except Exception as exc:
        check("4 falls back to the next group after retrying", False, repr(exc)[:200])
    FAIL_MODELS.clear()

    # ── embeddings ──────────────────────────────────────────────────────────────────────────
    emb = LiteLLMEmbeddingsRouter(router=router, model="openai-embed", dimensions=8)
    vec = emb.embed_documents(["a", "b"])
    sent = next(s["body"] for s in reversed(SEEN) if s["path"].endswith("/embeddings"))
    check("5 embeddings through the router with the configured dimensions",
          len(vec) == 2 and sent["model"] == "text-embedding-3-large" and sent.get("dimensions") == 8,
          f"model={sent['model']} dimensions={sent.get('dimensions')} keys={sorted(sent)}")

    try:
        from langchain_openai import ChatOpenAI

        co = ChatOpenAI(model="gpt-5", api_key="x", base_url=base, reasoning_effort="medium", max_retries=0)
        raw = co.with_structured_output(Shot, method="json_schema", strict=True, include_raw=True)
        answer = raw.invoke([("system", SYSTEM), ("user", USER)])
        wire = SEEN[-1]["body"]
        check("6 fallback ChatOpenAI: same messages, strict schema, effort",
              wire["messages"] == direct["messages"] and wire["response_format"]["json_schema"]["strict"] is True
              and wire.get("reasoning_effort") == "medium")
        meta = answer["raw"].usage_metadata
        check("6 fallback ChatOpenAI: usage equals today's row",
              (meta["input_tokens"], meta["input_token_details"].get("cache_read"), meta["output_tokens"])
              == (today_row["input_tokens"], today_row["cached_input_tokens"], today_row["output_tokens"]), str(meta))
    except ImportError:
        print("SKIP ChatOpenAI comparison (langchain-openai not installed)")

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
