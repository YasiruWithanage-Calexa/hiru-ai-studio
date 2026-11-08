"""What the API costs, per route, once a minute (plan/2026-11-08c phase 0). Off unless `DEBUG_TRAFFIC=true`.

One log line per route per minute: calls, database queries made, bytes sent, and for `/files` how many were served from
the disk copy and how many had to cross the internet from Supabase. Two things log a WARNING: a route called more than
60 times in a minute, and one stored file fetched from Supabase more than twice in an hour (the cache is not working).
`scripts/traffic_scene.py` reads the same numbers from the JSON snapshot at `GET /debug/traffic` (also only when on).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api import observability
from api.services import file_cache

_logger = logging.getLogger("api.traffic")

WINDOW_S = 60.0
CALLS_WARN = 60
UPSTREAM_WARN = 2
UPSTREAM_WINDOW_S = 3600.0

_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass
class RouteCount:
    calls: int = 0
    db: int = 0
    bytes: int = 0


@dataclass
class Traffic:
    routes: dict[str, RouteCount] = field(default_factory=lambda: defaultdict(RouteCount))
    upstream: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    window_start: float = field(default_factory=time.monotonic)
    file_marks: dict[str, int] = field(default_factory=lambda: dict(file_cache.STATS))

    def note_call(self, route: str, db: int, size: int) -> None:
        count = self.routes[route]
        count.calls += 1
        count.db += db
        count.bytes += size

    def note_upstream(self, key: str, now: float | None = None) -> bool:
        """A stored file was fetched from Supabase. True when that is more than UPSTREAM_WARN in the last hour."""
        now = time.monotonic() if now is None else now
        recent = [t for t in self.upstream[key] if now - t < UPSTREAM_WINDOW_S] + [now]
        self.upstream[key] = recent
        return len(recent) > UPSTREAM_WARN

    def snapshot(self) -> dict[str, object]:
        return {"routes": {r: vars(c) for r, c in sorted(self.routes.items())},
                "files": {k: file_cache.STATS[k] - self.file_marks.get(k, 0) for k in file_cache.STATS}}

    def flush(self) -> list[str]:
        """Log and reset one window. Returns the lines (for tests)."""
        lines = []
        for route, c in sorted(self.routes.items()):
            lines.append(f"{route} calls={c.calls} db={c.db} bytes={c.bytes}")
            if c.calls > CALLS_WARN:
                _logger.warning("route called %d times in a minute: %s", c.calls, route)
        files = {k: file_cache.STATS[k] - self.file_marks.get(k, 0) for k in file_cache.STATS}
        if self.routes:
            lines.append("files " + " ".join(f"{k}={v}" for k, v in sorted(files.items())))
        for line in lines:
            _logger.info(line)
        self.routes.clear()
        self.file_marks = dict(file_cache.STATS)
        self.window_start = time.monotonic()
        return lines


TRAFFIC = Traffic()


def route_name(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None) or _ID.sub("{id}", scope.get("path", ""))
    if path.startswith("/files/"):
        path = "/files/{ticket}"
    return f"{scope.get('method', '')} {path}"


class TrafficMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in ("/healthz", "/debug/traffic"):
            await self.app(scope, receive, send)
            return
        sent = 0

        async def wrapper(message: Message) -> None:
            nonlocal sent
            if message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, wrapper)
        finally:
            TRAFFIC.note_call(route_name(scope), observability.db_calls(), sent)


async def flush_forever(every_s: float = WINDOW_S) -> None:
    while True:
        await asyncio.sleep(every_s)
        with contextlib.suppress(Exception):
            TRAFFIC.flush()
