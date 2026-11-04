"""Supabase Storage over HTTP: the adapter behind the `Files` port.

Downloads and uploads retry a dropped connection or a 5xx with a doubling pause; a 4xx is never retried. Uploads
overwrite (`x-upsert`), so a repeat is safe and the path can be derived from the row id (a retried job rewrites the
same object instead of leaving a second one).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from hiru_ai.adapters.supabase_rest import Rest, _ok

_log = logging.getLogger("hiru_ai.adapters.storage")
ATTEMPTS = 4
BACKOFF_S = 1.0  # doubles each retry


def _transient(exc: Exception) -> bool:
    """A dropped or stalled connection, or a 5xx: worth another go. A 4xx is not."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _retrying[T](call: Callable[[], T], sleep: Callable[[float], None] = time.sleep) -> T:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == ATTEMPTS or not _transient(exc):
                raise
            _log.warning("storage call failed (%s); retry %d/%d", type(exc).__name__, attempt, ATTEMPTS - 1)
            sleep(BACKOFF_S * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


class SupabaseFiles:
    def __init__(self, rest: Rest, sleep: Callable[[float], None] = time.sleep) -> None:
        self.rest = rest
        self._sleep = sleep

    def download(self, bucket: str, path: str) -> bytes:
        def get() -> bytes:
            r = self.rest.client.get(f"{self.rest.storage}/object/{bucket}/{path}", headers=self.rest.headers)
            _ok(r)
            return r.content

        return _retrying(get, self._sleep)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        headers = {"apikey": self.rest.headers["apikey"], "Authorization": self.rest.headers["Authorization"],
                   "Content-Type": mime, "x-upsert": "true"}

        def post() -> None:
            _ok(self.rest.client.post(f"{self.rest.storage}/object/{bucket}/{path}", headers=headers, content=data))

        _retrying(post, self._sleep)
