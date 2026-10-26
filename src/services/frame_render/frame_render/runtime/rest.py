"""Supabase PostgREST + Storage over HTTP with the service role. Vendored per service
(PLAN.md §4). This copy adds `claim` (a conditional update that returns the rows it changed) and
`upload` (private buckets; the path is derived from the frame id, so a retry overwrites)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

Row = dict[str, Any]
_BATCH = 200
_ATTEMPTS = 4
_BACKOFF = 1.0  # seconds; doubles each retry
# Picture-sized bodies on a slow link need a long read/write; a dead host should still fail fast.
_TIMEOUT = httpx.Timeout(60.0, connect=10.0, write=120.0)
_logger = logging.getLogger(__name__)


def _transient(exc: Exception) -> bool:
    """A dropped or stalled connection, or a 5xx: worth another go. A 4xx is not."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _retrying[T](call: Callable[[], T]) -> T:
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == _ATTEMPTS or not _transient(exc):
                raise
            _logger.warning("storage call failed (%s); retry %d/%d", type(exc).__name__, attempt, _ATTEMPTS - 1)
            time.sleep(_BACKOFF * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


class Rest:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None) -> None:
        base = url.rstrip("/")
        self.rest = f"{base}/rest/v1"
        self.storage = f"{base}/storage/v1"
        self.client = client or httpx.Client(timeout=_TIMEOUT)
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}",
                        "Content-Type": "application/json"}

    def select(self, table: str, params: dict[str, str]) -> list[Row]:
        r = self.client.get(f"{self.rest}/{table}", headers=self.headers, params=params)
        r.raise_for_status()
        return list(r.json())

    def first(self, table: str, params: dict[str, str]) -> Row | None:
        rows = self.select(table, {**params, "limit": "1"})
        return rows[0] if rows else None

    def insert(self, table: str, rows: list[Row]) -> None:
        for i in range(0, len(rows), _BATCH):
            r = self.client.post(f"{self.rest}/{table}", headers=self.headers, json=rows[i: i + _BATCH])
            r.raise_for_status()

    def patch(self, table: str, params: dict[str, str], fields: Row) -> None:
        r = self.client.patch(f"{self.rest}/{table}", headers=self.headers, params=params, json=fields)
        r.raise_for_status()

    def claim(self, table: str, params: dict[str, str], fields: Row) -> list[Row]:
        """PATCH … WHERE params, returning the rows changed. Zero rows: someone else has it."""
        headers = {**self.headers, "Prefer": "return=representation"}
        r = self.client.patch(f"{self.rest}/{table}", headers=headers, params=params, json=fields)
        r.raise_for_status()
        return list(r.json())

    def download(self, bucket: str, path: str) -> bytes:
        def get() -> bytes:
            r = self.client.get(f"{self.storage}/object/{bucket}/{path}", headers=self.headers)
            r.raise_for_status()
            return r.content
        return _retrying(get)

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        headers = {"apikey": self.headers["apikey"], "Authorization": self.headers["Authorization"],
                   "Content-Type": content_type, "x-upsert": "true"}

        def post() -> None:
            r = self.client.post(f"{self.storage}/object/{bucket}/{path}", headers=headers, content=data)
            r.raise_for_status()
        _retrying(post)  # x-upsert makes a repeat safe
