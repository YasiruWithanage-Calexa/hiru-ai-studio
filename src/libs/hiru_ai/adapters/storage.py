"""Supabase Storage over HTTP: the adapter behind the `Files` port.

Downloads and uploads retry a dropped connection or a 5xx with a doubling pause; a 4xx is never retried.

Documents and their text overwrite (`x-upsert`), so a repeat is safe. PICTURES AND VIDEO NEVER DO (plan/2026-11-08c 1d):
the API and the browser keep a copy of a file by its path, which is only correct if a path names one file forever. A
second write to a media path is a bug and fails loudly, except when it is our own retry of the write that just landed
(the first answer was lost on the way back): that is success. Every picture is also stored small (`core/thumbs.py`).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from hiru_ai.adapters.supabase_rest import Rest, _ok
from hiru_ai.core import thumbs

_log = logging.getLogger("hiru_ai.adapters.storage")
IMMUTABLE_BUCKETS = frozenset({"frames", "references", "takes"})  # a path here is written once, ever
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
        self._put(bucket, path, data, mime)
        if thumbs.wants_thumb(bucket, path, mime):
            small = thumbs.make(data)
            if small is not None:
                try:
                    self._put(bucket, thumbs.thumb_path(path), small, thumbs.MIME)
                except Exception:  # best effort: the tile falls back to the full picture
                    _log.warning("thumbnail of %s/%s not stored", bucket, path, exc_info=True)

    def _put(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        once = bucket in IMMUTABLE_BUCKETS
        headers = {"apikey": self.rest.headers["apikey"], "Authorization": self.rest.headers["Authorization"],
                   "Content-Type": mime, "x-upsert": "false" if once else "true"}
        tries = 0

        def post() -> None:
            nonlocal tries
            tries += 1
            r = self.rest.client.post(f"{self.rest.storage}/object/{bucket}/{path}", headers=headers, content=data)
            if once and tries > 1 and already_exists(r):
                return  # our own earlier attempt landed; only its answer was lost
            _ok(r)

        _retrying(post, self._sleep)


def already_exists(response: httpx.Response) -> bool:
    """Storage answers a write to an existing path with 400/409 and "Duplicate"/"already exists" in the body."""
    return response.status_code in (400, 409) and any(
        word in response.text.lower() for word in ("duplicate", "already exists"))
