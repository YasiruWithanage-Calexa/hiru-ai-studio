"""The API's own disk copy of stored files (plan/2026-11-08c 1b).

A file crosses the internet from Supabase ONCE. `GET /files/{ticket}` serves it from here after that, with Range support
(Starlette's `FileResponse` answers 206), so a person opening the same picture a hundred times costs Supabase one
download. Media paths are never overwritten (1d), which is what makes a copy keyed by path correct forever.

* Several first requests for one path share ONE download (single flight).
* A file is written to `<name>.part` and renamed, so a reader never sees half a file.
* Over the size cap the least recently used files go first (a hit refreshes the file's mtime).
* Removing an object (`repos.storage.remove`) removes its copy too.
* A file bigger than the cap is not kept: the caller streams it through, as before.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import mimetypes
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from api.cache import clear_after_job
from api.config import Settings

_logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_CHUNK = 256 * 1024
_TYPE_SUFFIX = ".type"
_PART_SUFFIX = ".part"
_STALE_PART_S = 3600

# Counters for the traffic log (plan §4 phase 0): how many requests the disk answered and how many went to Supabase.
STATS = {"hits": 0, "misses": 0, "upstream_bytes": 0}
# Called with "bucket/path" each time a file is fetched from Supabase (the traffic log watches for repeats).
ON_UPSTREAM: Callable[[str], None] | None = None


class NotFound(Exception):
    """Supabase has no such object (or refused it): the caller answers 404."""


class Unreachable(Exception):
    """Supabase could not be reached: the caller answers 502."""


class TooLarge(Exception):
    """The object is larger than the whole cache: stream it through instead."""


@dataclass(frozen=True)
class Cached:
    path: Path
    media_type: str


def root(settings: Settings) -> Path | None:
    """The cache folder, or None when the cache is turned off (`FILES__CACHE_MAX_GB=0`)."""
    if settings.files.cache_max_gb <= 0:
        return None
    if settings.files.cache_dir:
        return Path(settings.files.cache_dir)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "hiru-ai" / "files"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "hiru-ai" / "files"


def _file_for(base: Path, bucket: str, path: str) -> Path:
    """Where one object lives. Hashed, so no stored path (spaces, unicode, `..`) can ever name a file outside `base`
    or collide with another; the extension is kept so the folder is still readable."""
    digest = hashlib.sha256(f"{bucket}/{path}".encode()).hexdigest()
    suffix = Path(path).suffix.lower()
    suffix = suffix if suffix.isascii() and suffix[1:].isalnum() and len(suffix) <= 8 else ""
    return base / bucket_dir(bucket) / digest[:2] / f"{digest}{suffix}"


def bucket_dir(bucket: str) -> str:
    return "".join(c for c in bucket if c.isalnum() or c in "-_") or "bucket"


def _media_type(file: Path, path: str) -> str:
    with contextlib.suppress(OSError):
        text = file.with_name(file.name + _TYPE_SUFFIX).read_text(encoding="ascii").strip()
        if text:
            return text
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


# plan/2026-11-13b phase 9: a file Supabase does not have (a take's still that was never made) is not asked for again on
# every view. Remembered for 10 minutes, per process; forgotten when this process stores that path, and when a job ends
# (a worker may have just written it).
MISS_TTL_S = 600.0


class _Misses:
    def __init__(self) -> None:
        self.until: dict[tuple[str, str], float] = {}

    def has(self, key: tuple[str, str]) -> bool:
        stop = self.until.get(key)
        if stop is None:
            return False
        if stop <= time.monotonic():
            del self.until[key]
            return False
        return True

    def add(self, key: tuple[str, str]) -> None:
        if len(self.until) >= 4096:
            self.until.clear()
        self.until[key] = time.monotonic() + MISS_TTL_S

    def clear(self) -> None:
        self.until.clear()


MISSES = _Misses()
clear_after_job(MISSES)


class FileCache:
    """One per process (`get_cache`). Safe to share across requests: all state is on disk or in `_flights`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._flights: dict[tuple[str, str], asyncio.Task[Cached]] = {}

    # ── reading ────────────────────────────────────────────────────────────────────────────

    def lookup(self, bucket: str, path: str) -> Cached | None:
        base = root(self.settings)
        if base is None:
            return None
        file = _file_for(base, bucket, path)
        try:
            if not file.is_file():
                return None
            os.utime(file)  # least-recently-used eviction reads this
        except OSError:
            return None
        STATS["hits"] += 1
        return Cached(file, _media_type(file, path))

    async def fetch(self, bucket: str, path: str) -> Cached:
        """The object on disk, downloading it from Supabase if this is its first request."""
        hit = self.lookup(bucket, path)
        if hit is not None:
            return hit
        key = (bucket, path)
        if MISSES.has(key):
            raise NotFound
        task = self._flights.get(key)
        if task is None:
            task = asyncio.ensure_future(self._download(bucket, path))
            self._flights[key] = task
            task.add_done_callback(lambda _t: self._flights.pop(key, None))
        return await asyncio.shield(task)

    # ── removing ───────────────────────────────────────────────────────────────────────────

    def evict(self, bucket: str, path: str) -> None:
        base = root(self.settings)
        if base is None:
            return
        file = _file_for(base, bucket, path)
        for victim in (file, file.with_name(file.name + _TYPE_SUFFIX)):
            with contextlib.suppress(OSError):
                victim.unlink()

    # ── writing ────────────────────────────────────────────────────────────────────────────

    async def _download(self, bucket: str, path: str) -> Cached:
        base = root(self.settings)
        if base is None:
            raise TooLarge
        file = _file_for(base, bucket, path)
        part = file.with_name(file.name + f".{os.getpid()}{_PART_SUFFIX}")
        url = f"{self.settings.supabase.url.rstrip('/')}/storage/v1/object/{bucket}/{path}"
        key = self.settings.supabase.service_role_key.get_secret_value()
        cap = int(self.settings.files.cache_max_gb * 1024**3)
        STATS["misses"] += 1
        if ON_UPSTREAM is not None:
            ON_UPSTREAM(f"{bucket}/{path}")
        try:
            part.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            media_type = ""
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client, client.stream(
                    "GET", url, headers={"Authorization": f"Bearer {key}"}) as resp:
                if resp.status_code >= 400:
                    if resp.status_code == 404:
                        MISSES.add((bucket, path))
                    raise NotFound
                media_type = resp.headers.get("content-type", "").split(";")[0].strip()
                if int(resp.headers.get("content-length") or 0) > cap:
                    raise TooLarge
                with part.open("wb") as out:
                    async for chunk in resp.aiter_bytes(_CHUNK):
                        out.write(chunk)
                        size += len(chunk)
            STATS["upstream_bytes"] += size
            if media_type:
                file.with_name(file.name + _TYPE_SUFFIX).write_text(media_type, encoding="ascii", errors="ignore")
            os.replace(part, file)
        except (httpx.HTTPError, OSError) as exc:
            _logger.warning("storage unreachable bucket=%s", bucket, exc_info=True)
            raise Unreachable from exc
        finally:
            with contextlib.suppress(OSError):
                part.unlink()
        await asyncio.to_thread(self._trim, base, cap)
        return Cached(file, media_type or _media_type(file, path))

    def _trim(self, base: Path, cap: int) -> None:
        """Delete the least recently used files until the folder fits, and any `.part` left by a crash."""
        entries: list[tuple[float, int, Path]] = []
        total = 0
        now = time.time()
        for item in base.rglob("*"):
            try:
                if not item.is_file():
                    continue
                stat = item.stat()
            except OSError:
                continue
            if item.name.endswith(_PART_SUFFIX):
                if now - stat.st_mtime > _STALE_PART_S:
                    with contextlib.suppress(OSError):
                        item.unlink()
                continue
            if item.name.endswith(_TYPE_SUFFIX):
                continue
            entries.append((stat.st_mtime, stat.st_size, item))
            total += stat.st_size
        if total <= cap:
            return
        for _mtime, size, item in sorted(entries):
            with contextlib.suppress(OSError):
                item.unlink()
                item.with_name(item.name + _TYPE_SUFFIX).unlink(missing_ok=True)
                total -= size
            if total <= cap:
                break


_cache: FileCache | None = None


def get_cache(settings: Settings) -> FileCache:
    """The process's cache, rebuilt when the settings object changes (tests install their own)."""
    global _cache
    if _cache is None or _cache.settings is not settings:
        _cache = FileCache(settings)
    return _cache


def forget_missing(bucket: str, path: str) -> None:
    """This process just stored `path`: a remembered 404 for it is over."""
    MISSES.until.pop((bucket, path), None)


def evict(settings: Settings, bucket: str, path: str) -> None:
    get_cache(settings).evict(bucket, path)
