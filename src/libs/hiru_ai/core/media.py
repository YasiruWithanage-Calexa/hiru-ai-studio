"""Where stored files live: Supabase Storage (default) or one Cloud Storage bucket (plan/2026-11-27 §4).

A database row names a file by a folder (`documents`, `frames`, `references`, `takes`) and a path. That pair never
changes; `FILES__BACKEND` only says where the bytes are:

* `supabase`: `{SUPABASE__URL}/storage/v1/object/{folder}/{path}`, as before.
* `gcs`: the object `{folder}/{path}` in the bucket `FILES__GCS_BUCKET`.

With `FILES__READ_FALLBACK=true` (while existing files are being moved) a file the bucket does not have is read from
Supabase, and a removal removes both. The database is shared, so every process that reads it (localhost included) must
use the same backend.

This module builds requests; each caller keeps its own client, retries and error handling. The API, the functions and
the scripts use it. `infra/assemble` is a container with no `hiru_ai`, so it has its own copy
(`tests/infra/test_assemble_gcs.py` holds the two equal).

Credentials: the service account of the machine (metadata server) in the cloud, application default credentials on a
developer's machine. No key files.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from urllib.parse import quote

import httpx

BACKENDS = ("supabase", "gcs")
GCS = "https://storage.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"  # noqa: S105  an address, not a credential
_EARLY_S = 300  # a token is renewed this long before it expires


@dataclass(frozen=True)
class MediaConfig:
    backend: str = "supabase"
    bucket: str = ""
    read_fallback: bool = False

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            raise ValueError(f"FILES__BACKEND must be one of {', '.join(BACKENDS)}, not {self.backend!r}")
        if self.backend == "gcs" and not self.bucket:
            raise ValueError("FILES__BACKEND=gcs needs FILES__GCS_BUCKET")

    @classmethod
    def from_env(cls) -> MediaConfig:
        def env(name: str) -> str:
            return os.environ.get(name, "").strip()

        return cls(backend=env("FILES__BACKEND").lower() or "supabase", bucket=env("FILES__GCS_BUCKET"),
                   read_fallback=env("FILES__READ_FALLBACK").lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class Request:
    url: str
    headers: dict[str, str] = field(repr=False)  # carries a credential: never printed


# ── the Google token ────────────────────────────────────────────────────────────────────────────────────────────────


class _Token:
    """One access token per process, renewed shortly before it expires."""

    def __init__(self) -> None:
        self._value = ""
        self._until = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if not self._value or time.time() >= self._until:
                try:
                    self._value, expires = _fetch_token()
                except httpx.HTTPError:
                    raise
                except Exception as exc:  # as a transport error, so callers treat it as storage being unreachable
                    raise httpx.TransportError(f"no Google credentials ({type(exc).__name__})") from exc
                self._until = expires - _EARLY_S
            return self._value


def _fetch_token() -> tuple[str, float]:
    """(token, the time it expires). `google-auth` when it is installed (a developer's application default credentials,
    or the machine's account); otherwise the metadata server every Google machine has."""
    try:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest
    except ImportError:
        r = httpx.get(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=10.0)
        r.raise_for_status()
        answer = r.json()
        return str(answer["access_token"]), time.time() + float(answer["expires_in"])
    credentials, _project = google.auth.default(scopes=[SCOPE])
    credentials.refresh(AuthRequest())
    expiry = getattr(credentials, "expiry", None)  # naive UTC
    until = expiry.replace(tzinfo=UTC).timestamp() if expiry else time.time() + 3000
    return str(credentials.token), until


_TOKEN = _Token()


# ── requests ────────────────────────────────────────────────────────────────────────────────────────────────────────


def object_url(bucket: str, folder: str, path: str) -> str:
    """The JSON API address of one object. The whole name is one path segment, so `/` is escaped too."""
    return f"{GCS}/storage/v1/b/{bucket}/o/{quote(f'{folder}/{path}', safe='')}"


def upload_url(bucket: str, folder: str, path: str, *, once: bool) -> str:
    url = f"{GCS}/upload/storage/v1/b/{bucket}/o?uploadType=media&name={quote(f'{folder}/{path}', safe='')}"
    return f"{url}&ifGenerationMatch=0" if once else url  # 0: only if the object does not exist yet


class Media:
    def __init__(self, supabase_url: str, service_role_key: str, config: MediaConfig | None = None,
                 token: Callable[[], str] | None = None) -> None:
        self.supabase = f"{supabase_url.rstrip('/')}/storage/v1/object"
        self._key = service_role_key
        self.config = config or MediaConfig.from_env()
        self._token = token or _TOKEN

    @property
    def gcs(self) -> bool:
        return self.config.backend == "gcs"

    def _supabase_headers(self) -> dict[str, str]:
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}"}

    def _google_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def reads(self, folder: str, path: str) -> list[Request]:
        """Where to read one file, in order. The next is tried only when the one before answers 404."""
        supabase = Request(f"{self.supabase}/{folder}/{path}", self._supabase_headers()) \
            if not self.gcs or self.config.read_fallback else None
        if not self.gcs:
            return [supabase] if supabase else []
        first = Request(f"{object_url(self.config.bucket, folder, path)}?alt=media", self._google_headers())
        return [first, supabase] if supabase else [first]

    def write(self, folder: str, path: str, mime: str, *, once: bool) -> Request:
        """A POST of the file's bytes. `once`: refused when the file is already there (see `already_exists`)."""
        if self.gcs:
            return Request(upload_url(self.config.bucket, folder, path, once=once),
                           {**self._google_headers(), "Content-Type": mime})
        return Request(f"{self.supabase}/{folder}/{path}",
                       {**self._supabase_headers(), "Content-Type": mime, "x-upsert": "false" if once else "true"})

    def removes(self, folder: str, path: str) -> list[Request]:
        """The DELETEs that remove one file (404: already gone)."""
        supabase = Request(f"{self.supabase}/{folder}/{path}", self._supabase_headers())
        if not self.gcs:
            return [supabase]
        first = Request(object_url(self.config.bucket, folder, path), self._google_headers())
        return [first, supabase] if self.config.read_fallback else [first]


def get(client: httpx.Client, media: Media, folder: str, path: str) -> httpx.Response:
    """The response of the first place that has the file (or the last one asked). The caller checks its status."""
    response: httpx.Response | None = None
    for request in media.reads(folder, path):
        response = client.get(request.url, headers=request.headers)
        if response.status_code != 404:
            break
    assert response is not None  # `reads` always names at least one place
    return response


def put(client: httpx.Client, media: Media, folder: str, path: str, data: bytes, mime: str, *,
        once: bool) -> httpx.Response:
    request = media.write(folder, path, mime, once=once)
    return client.post(request.url, headers=request.headers, content=data)


def already_exists(response: httpx.Response) -> bool:
    """A write-once upload met an existing file: Cloud Storage answers 412, Supabase Storage 400/409 with
    "Duplicate" / "already exists" in the body."""
    if response.status_code == 412:
        return True
    return response.status_code in (400, 409) and any(
        word in response.text.lower() for word in ("duplicate", "already exists"))
