"""One disk copy of stored files for the API and the workers (plan/2026-11-21 D1-D6).

A file in a write-once bucket (`frames`, `references`, `takes`: a path there names one file forever, plan/2026-11-08c
1d) crosses the internet from Supabase ONCE per machine. The API's `/files` cache (`api/services/file_cache.py`) and the
render workers share this folder and this naming (`root`, `_file_for`), so a sheet the API already served is a hit for a
frame job, and a frame a worker just painted is a hit for the API.

`CachedFiles` wraps the `Files` port:

* `download` of a write-once path reads the disk first, else downloads once and keeps it. Other buckets (`documents`,
  which overwrite) pass straight through, never kept.
* Several threads asking for one path share ONE download (a per-key lock: frames paint in a thread pool).
* A file is written to `<name>.<pid>.part` and renamed, so a reader never sees half a file; its media type sits beside
  it in `<name>.type`.
* `upload` writes through: a picture or take just stored is also kept, so the next shot's same-setup reference and the
  video's first frame are never downloaded.
* Over the size cap the least recently used files go first (`trim`, the API's rule). A file bigger than the cap is not
  kept.
* No disk (`FILES__CACHE_MAX_GB=0`, e.g. Cloud Run where `/tmp` is memory): a bounded in-memory LRU for the life of the
  process instead (D4).
* A failed download (a 404 included) is never kept.
* `summary()` is the job's one log line (D6): `storage: n from Supabase (x MB), m from disk`.

Same settings as the API (`FILES__CACHE_DIR`, `FILES__CACHE_MAX_GB`); no switch of its own (D5).
"""
from __future__ import annotations

import contextlib
import hashlib
import mimetypes
import os
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

IMMUTABLE_BUCKETS = frozenset({"frames", "references", "takes"})  # a path here is written once, ever
TYPE_SUFFIX = ".type"
PART_SUFFIX = ".part"
STALE_PART_S = 3600
MEMORY_CAP_BYTES = 300 * 1024**2  # D4 (Q1 open): the in-memory fallback's cap when there is no disk


class _FilesPort(Protocol):
    def download(self, bucket: str, path: str) -> bytes: ...
    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None: ...


class _FilesSettings(Protocol):
    @property
    def cache_dir(self) -> str: ...

    @property
    def cache_max_gb(self) -> float: ...


class HasFiles(Protocol):
    """Anything with `.files.cache_dir` and `.files.cache_max_gb`: the API's `Settings`, or `CacheSettings` below."""

    @property
    def files(self) -> _FilesSettings: ...


@dataclass(frozen=True)
class FilesConfig:
    cache_dir: str = ""
    cache_max_gb: float = 5.0


@dataclass(frozen=True)
class CacheSettings:
    """The workers' view of the API's `FILES__*` settings."""

    files: FilesConfig = field(default_factory=FilesConfig)

    @classmethod
    def from_env(cls) -> CacheSettings:
        raw = os.environ.get("FILES__CACHE_MAX_GB", "").strip()
        try:
            cap = float(raw) if raw else 5.0
        except ValueError:
            cap = 5.0
        return cls(FilesConfig(cache_dir=os.environ.get("FILES__CACHE_DIR", "").strip(), cache_max_gb=cap))


# ── the folder (moved unchanged from api/services/file_cache.py) ────────────────────────────────────────────────────


def root(settings: HasFiles) -> Path | None:
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


def media_type(file: Path, path: str) -> str:
    with contextlib.suppress(OSError):
        text = file.with_name(file.name + TYPE_SUFFIX).read_text(encoding="ascii").strip()
        if text:
            return text
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def trim(base: Path, cap: int) -> None:
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
        if item.name.endswith(PART_SUFFIX):
            if now - stat.st_mtime > STALE_PART_S:
                with contextlib.suppress(OSError):
                    item.unlink()
            continue
        if item.name.endswith(TYPE_SUFFIX):
            continue
        entries.append((stat.st_mtime, stat.st_size, item))
        total += stat.st_size
    if total <= cap:
        return
    for _mtime, size, item in sorted(entries):
        with contextlib.suppress(OSError):
            item.unlink()
            item.with_name(item.name + TYPE_SUFFIX).unlink(missing_ok=True)
            total -= size
        if total <= cap:
            break


def keep(base: Path, bucket: str, path: str, data: bytes, mime: str = "") -> Path:
    """Write one object into the folder atomically (`.part` + rename), its media type beside it."""
    file = _file_for(base, bucket, path)
    part = file.with_name(file.name + f".{os.getpid()}.{threading.get_ident()}{PART_SUFFIX}")
    try:
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(data)
        if mime:
            file.with_name(file.name + TYPE_SUFFIX).write_text(mime, encoding="ascii", errors="ignore")
        os.replace(part, file)
    finally:
        with contextlib.suppress(OSError):
            part.unlink()
    return file


# ── the workers' cache ──────────────────────────────────────────────────────────────────────────────────────────────


class _MemoryLRU:
    """D4: the cache when there is no disk. Shared by every job in the process; bounded by bytes."""

    def __init__(self, cap: int = MEMORY_CAP_BYTES) -> None:
        self.cap = cap
        self.items: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> bytes | None:
        with self.lock:
            data = self.items.get(key)
            if data is not None:
                self.items.move_to_end(key)
            return data

    def put(self, key: tuple[str, str], data: bytes) -> None:
        if len(data) > self.cap:
            return
        with self.lock:
            old = self.items.pop(key, None)
            if old is not None:
                self.size -= len(old)
            self.items[key] = data
            self.size += len(data)
            while self.size > self.cap and self.items:
                _key, gone = self.items.popitem(last=False)
                self.size -= len(gone)

    def clear(self) -> None:
        with self.lock:
            self.items.clear()
            self.size = 0


MEMORY = _MemoryLRU()


class _KeyLocks:
    """One lock per (bucket, path), so N threads asking for one sheet make one download."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}

    def get(self, key: tuple[str, str]) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                if len(self._locks) >= 4096:
                    self._locks = {k: v for k, v in self._locks.items() if v.locked()}
                lock = self._locks[key] = threading.Lock()
            return lock


_LOCKS = _KeyLocks()


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    upstream_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, *, hit: bool, size: int = 0) -> None:
        with self.lock:
            if hit:
                self.hits += 1
            else:
                self.misses += 1
                self.upstream_bytes += size


class CachedFiles:
    """The `Files` port with a local copy of write-once files (D2). One per job: its `stats` are that job's."""

    def __init__(self, inner: _FilesPort, settings: HasFiles | None = None, *,
                 memory: _MemoryLRU | None = None) -> None:
        self.inner = inner
        self.settings: HasFiles = settings or CacheSettings.from_env()
        self.memory = memory or MEMORY
        self.stats = Stats()

    def __getattr__(self, name: str) -> Any:  # anything else the wrapped adapter offers (e.g. `rest`)
        if name == "inner":
            raise AttributeError(name)
        return getattr(self.inner, name)

    # ── reading ────────────────────────────────────────────────────────────────────────────────────────────────

    def _cap(self) -> int:
        return int(self.settings.files.cache_max_gb * 1024**3)

    def _read(self, base: Path | None, key: tuple[str, str]) -> bytes | None:
        if base is None:
            return self.memory.get(key)
        file = _file_for(base, *key)
        try:
            data = file.read_bytes()
            os.utime(file)  # least-recently-used eviction reads this
        except OSError:
            return None
        return data

    def download(self, bucket: str, path: str) -> bytes:
        if bucket not in IMMUTABLE_BUCKETS:
            data = self.inner.download(bucket, path)
            self.stats.add(hit=False, size=len(data))
            return data
        key = (bucket, path)
        base = root(self.settings)
        with _LOCKS.get(key):
            kept = self._read(base, key)
            if kept is not None:
                self.stats.add(hit=True)
                return kept
            data = self.inner.download(bucket, path)  # raises on a 404: nothing is kept
            self.stats.add(hit=False, size=len(data))
            self._keep(base, bucket, path, data, mimetypes.guess_type(path)[0] or "")
            return data

    # ── writing ────────────────────────────────────────────────────────────────────────────────────────────────

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.inner.upload(bucket, path, data, mime)
        if bucket in IMMUTABLE_BUCKETS:  # D3: write-through
            self._keep(root(self.settings), bucket, path, data, mime)

    def _keep(self, base: Path | None, bucket: str, path: str, data: bytes, mime: str) -> None:
        if base is None:
            self.memory.put((bucket, path), data)
            return
        cap = self._cap()
        if len(data) > cap:
            return
        try:
            keep(base, bucket, path, data, mime)
            trim(base, cap)
        except OSError:  # a full or read-only disk costs a download next time, never the job
            return

    # ── the job's log line ─────────────────────────────────────────────────────────────────────────────────────

    def summary(self) -> str:
        where = "disk" if root(self.settings) is not None else "memory"
        mb = self.stats.upstream_bytes / 1024**2
        return f"storage: {self.stats.misses} from Supabase ({mb:.1f} MB), {self.stats.hits} from {where}"


def storage_summary(files: object) -> str:
    """The job-end line for any `Files` (""): only `CachedFiles` counts."""
    return files.summary() if isinstance(files, CachedFiles) else ""
