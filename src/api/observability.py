"""One log line per API request, with how long it took and how many database calls it made.

The count comes from an httpx hook on the Supabase REST client (`count_db_call`), kept in a context
variable that this middleware opens per request. The same figures go back to the caller as
`Server-Timing` (shown in the browser's network panel) and an `X-Request-ID` to match log lines.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import httpx
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.repositories.memo import close_memo, open_memo

_logger = logging.getLogger("api.request")


@dataclass
class _Stats:
    db_calls: int = 0
    out_bytes: int = 0  # response body bytes (the trace's "bytes")
    # Filled only when a trace file is set (`DEBUG_TRAFFIC_LOG`): every query this request made, in order.
    queries: list[dict[str, object]] = field(default_factory=list)


# `DEBUG_TRAFFIC_LOG=<path>` (local only, set by api.main): one JSON line per request with each query it made, so
# repeated and redundant reads can be found offline (scripts/traffic_report.py). None = off.
TRACE_PATH: Path | None = None


_stats: ContextVar[_Stats | None] = ContextVar("api_request_stats", default=None)


async def count_db_call(request: httpx.Request) -> None:
    stats = _stats.get()
    if stats is not None:
        stats.db_calls += 1
        if TRACE_PATH is not None:
            request.extensions["trace_t0"] = time.perf_counter()
            path = request.url.path.split("/rest/v1/", 1)[-1]
            entry: dict[str, object] = {"m": request.method, "t": path, "q": unquote(request.url.query.decode())}
            request.extensions["trace_entry"] = entry
            stats.queries.append(entry)


async def time_db_call(response: httpx.Response) -> None:
    """Response hook (trace only): how long the query took and how many bytes came back."""
    entry = response.request.extensions.get("trace_entry")
    if isinstance(entry, dict):
        entry["ms"] = round((time.perf_counter() - response.request.extensions["trace_t0"]) * 1000, 1)
        entry["s"] = response.status_code
        entry["cr"] = response.headers.get("content-range", "")


def note_trace(kind: str, detail: str) -> None:
    """Something other than a REST query worth seeing in the trace (a file fetched from Supabase)."""
    stats = _stats.get()
    if stats is not None and TRACE_PATH is not None:
        stats.queries.append({"m": kind, "t": detail, "q": ""})


def db_calls() -> int:
    """Database calls made so far in this request (0 outside one)."""
    stats = _stats.get()
    return stats.db_calls if stats else 0


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming[:64] or uuid.uuid4().hex[:12]
        stats = _Stats()
        token = _stats.set(stats)
        memo_token = open_memo()
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                elapsed = (time.perf_counter() - start) * 1000
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
                headers.append("Server-Timing", f'app;dur={elapsed:.1f}, db;desc="{stats.db_calls} calls"')
            elif message["type"] == "http.response.body":
                stats.out_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            path = scope.get("path", "")
            if path != "/healthz":
                _logger.info("%s %s %s %.0fms db=%d rid=%s", scope.get("method", ""), path, status, elapsed,
                             stats.db_calls, request_id)
                if TRACE_PATH is not None:
                    _write_trace(scope, status, elapsed, request_id, stats)
            close_memo(memo_token)
            _stats.reset(token)


def _write_trace(scope: Scope, status: int, elapsed: float, request_id: str, stats: _Stats) -> None:
    headers = dict(scope.get("headers") or [])
    route = getattr(scope.get("route"), "path", None)
    line = {"at": time.time(), "rid": request_id, "method": scope.get("method", ""), "path": scope.get("path", ""),
            "route": route, "query": scope.get("query_string", b"").decode("latin-1"), "status": status,
            "ms": round(elapsed, 1), "db": stats.db_calls, "bytes": stats.out_bytes, "queries": stats.queries,
            "page": headers.get(b"referer", b"").decode("latin-1")}
    try:
        assert TRACE_PATH is not None
        with TRACE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        _logger.warning("could not write the traffic trace", exc_info=True)
