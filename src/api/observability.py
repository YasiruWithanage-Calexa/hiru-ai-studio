"""One log line per API request, with how long it took and how many database calls it made.

The count comes from an httpx hook on the Supabase REST client (`count_db_call`), kept in a context
variable that this middleware opens per request. The same figures go back to the caller as
`Server-Timing` (shown in the browser's network panel) and an `X-Request-ID` to match log lines.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_logger = logging.getLogger("api.request")


@dataclass
class _Stats:
    db_calls: int = 0


_stats: ContextVar[_Stats | None] = ContextVar("api_request_stats", default=None)


async def count_db_call(_: httpx.Request) -> None:
    stats = _stats.get()
    if stats is not None:
        stats.db_calls += 1


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
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            path = scope.get("path", "")
            if path != "/healthz":
                _logger.info("%s %s %s %.0fms db=%d rid=%s", scope.get("method", ""), path, status, elapsed,
                             stats.db_calls, request_id)
            _stats.reset(token)
