"""The live hub (plan/2026-11-13d phase 5): one per API instance.

It listens to Postgres changes through Supabase Realtime with the service key (the browser never opens a channel) and
turns each change into the small shapes of `contracts.live` (the `/live` item, or a notice), for the streams open on
that change's production. Rows are never forwarded: only ids, statuses, timestamps and event numbers.

It listens only while at least one stream is open, and stops when the last one closes. Nothing is shared between
instances, so nothing needs to be: a stream lives on one instance and catches up from the database when it reconnects.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from api.repositories import Repos, Row
from contracts.live import BUILD, LiveItem, LiveNotice

_logger = logging.getLogger(__name__)

# The tables a stream needs (each is in the `supabase_realtime` publication).
TABLES = ("first_frames", "video_renders", "documents", "jobs", "job_events", "chat_messages",
          "production_director_board")
_KIND = {"first_frames": "frame", "video_renders": "render", "documents": "document", "jobs": "job"}
JOB_CACHE = 2000

# table, INSERT | UPDATE | DELETE, the record, the commit timestamp
Change = Callable[[str, str, Row, str], Coroutine[Any, Any, None]]
Message = LiveItem | LiveNotice
CLOSE = object()  # put on a stream's queue to end it


class ChangeSource(Protocol):
    """Where changes come from: Supabase Realtime in the API, a fake in tests (tests never touch the network)."""

    async def start(self, on_change: Change) -> None: ...
    async def stop(self) -> None: ...


@dataclass(eq=False)
class Subscriber:
    production_id: str
    user_id: str
    queue: asyncio.Queue[Any]
    opened: float = field(default_factory=lambda: asyncio.get_running_loop().time())
    overflowed: bool = False
    ended: bool = False

    def end(self) -> None:
        """Make room for the close and nothing else: what was waiting is read again on reconnect."""
        self.ended = True
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(CLOSE)


def _when(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


class LiveHub:
    def __init__(self, source_factory: Callable[[], ChangeSource], repos: Repos, *, per_person: int = 3,
                 queue: int = 200) -> None:
        self._factory = source_factory
        self._repos = repos
        self._per_person = per_person
        self._queue = queue
        self._streams: dict[str, list[Subscriber]] = {}
        self._source: ChangeSource | None = None
        self._lock = asyncio.Lock()
        # job id -> (production id, kind, status), and the build's newest event number, from the changes seen (a job
        # an event names before its row was seen is read once).
        self._jobs: OrderedDict[str, tuple[str, str, str]] = OrderedDict()
        self._seq: dict[str, int] = {}
        self.sent = 0

    @property
    def listening(self) -> bool:
        return self._source is not None

    async def open(self, production_id: UUID, user_id: UUID) -> Subscriber:
        sub = Subscriber(str(production_id), str(user_id), asyncio.Queue(maxsize=self._queue))
        async with self._lock:
            mine = [s for s in self._streams.get(sub.production_id, []) if s.user_id == sub.user_id]
            for old in sorted(mine, key=lambda s: s.opened)[: max(0, len(mine) - self._per_person + 1)]:
                old.end()  # a fourth tab closes the oldest
            self._streams.setdefault(sub.production_id, []).append(sub)
            if self._source is None:
                source = self._factory()
                try:
                    await source.start(self._on_change)
                except Exception:
                    _logger.warning("the live hub could not listen; streams get their catch-up only", exc_info=True)
                else:
                    self._source = source
        return sub

    async def close(self, sub: Subscriber) -> None:
        async with self._lock:
            subs = self._streams.get(sub.production_id, [])
            if sub in subs:
                subs.remove(sub)
            if not subs:
                self._streams.pop(sub.production_id, None)
            if not self._streams and self._source is not None:
                source, self._source = self._source, None
                try:
                    await source.stop()
                except Exception:
                    _logger.warning("the live hub did not stop cleanly", exc_info=True)

    async def _job(self, job_id: str) -> tuple[str, str, str] | None:
        known = self._jobs.get(job_id)
        if known is None:
            row = await self._repos.jobs.get(UUID(job_id))
            if row is None or not row.get("production_id"):
                return None
            known = self._remember(job_id, str(row["production_id"]), str(row["kind"]), str(row["status"]))
        return known

    def _remember(self, job_id: str, production_id: str, kind: str, status: str) -> tuple[str, str, str]:
        self._jobs[job_id] = (production_id, kind, status)
        self._jobs.move_to_end(job_id)
        while len(self._jobs) > JOB_CACHE:
            gone, _ = self._jobs.popitem(last=False)
            self._seq.pop(gone, None)
        return self._jobs[job_id]

    async def _on_change(self, table: str, event: str, record: Row, at: str) -> None:
        try:
            out = await self._message(table, event, record, at)
        except Exception:  # one odd row must never stop the hub
            _logger.warning("live hub could not read a change table=%s", table, exc_info=True)
            return
        if out is not None:
            self.deliver(*out)

    async def _message(self, table: str, event: str, record: Row, at: str) -> tuple[str, Message, str | None] | None:
        """(production id, message, the writer to leave out) for one change, or None when no stream wants it."""
        if not record or event == "DELETE":
            return None
        if table in _KIND:
            production_id = record.get("production_id")
            if not production_id:
                return None
            item = LiveItem(kind=_KIND[table], id=str(record["id"]),  # type: ignore[arg-type]
                            shot_id=str(record["shot_id"]) if record.get("shot_id") else None,
                            status=str(record.get("status")), updated_at=_when(record.get("updated_at") or at))
            if table == "jobs":
                item.job_kind = str(record.get("kind"))
                self._remember(item.id, str(production_id), item.job_kind, item.status)
                if item.job_kind == BUILD:
                    item.seq = self._seq.get(item.id)
            return str(production_id), item, None
        if table == "job_events":
            job_id = str(record.get("job_id"))
            known = await self._job(job_id)
            if known is None or known[1] != BUILD:
                return None
            seq = int(record.get("seq") or 0)
            self._seq[job_id] = max(seq, self._seq.get(job_id, 0))
            return known[0], LiveItem(kind="job", id=job_id, status=known[2], job_kind=BUILD,
                                      updated_at=_when(record.get("created_at") or at), seq=self._seq[job_id]), None
        if table == "chat_messages" and record.get("production_id"):
            author = record.get("author_user_id")
            return (str(record["production_id"]), LiveNotice(kind="thread", id=str(record.get("thread_id")),
                                                             at=_when(record.get("created_at") or at)),
                    str(author) if author else None)
        if table == "production_director_board" and record.get("production_id"):
            return str(record["production_id"]), LiveNotice(kind="board", at=_when(at)), None
        return None

    def deliver(self, production_id: str, message: Message, skip_user: str | None = None) -> None:
        for sub in list(self._streams.get(production_id, [])):
            if sub.ended or (skip_user is not None and sub.user_id == skip_user):
                continue  # closing; or a person's own message, already on their screen
            try:
                sub.queue.put_nowait(message)
                self.sent += 1
            except asyncio.QueueFull:
                sub.overflowed = True
                sub.end()


class NullSource:
    """No changes at all (tests that inject repos; a test that wants changes puts its own hub on `app.state`)."""

    async def start(self, on_change: Change) -> None:
        return None

    async def stop(self) -> None:
        return None


class RealtimeSource:
    """Supabase Realtime, server side, with the service key: one channel, the tables of `TABLES`."""

    def __init__(self, url: str, key: str) -> None:
        self._url = url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/realtime/v1"
        self._key = key
        self._client: Any = None
        self._tasks: set[asyncio.Task[None]] = set()  # each change in flight (kept, so none is collected early)

    async def start(self, on_change: Change) -> None:
        from realtime import AsyncRealtimeClient
        from realtime.types import RealtimePostgresChangesListenEvent

        loop = asyncio.get_running_loop()
        client = AsyncRealtimeClient(self._url, token=self._key, params={"apikey": self._key})
        await client.connect()
        channel = client.channel("hiru-live")

        def handle(payload: Any) -> None:
            data = payload.get("data") or {}
            change = on_change(str(data.get("table")), str(data.get("type")), data.get("record") or {},
                               str(data.get("commit_timestamp") or ""))
            task: asyncio.Task[None] = loop.create_task(change)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        for table in TABLES:
            channel.on_postgres_changes(RealtimePostgresChangesListenEvent.All, handle, table=table, schema="public")
        await channel.subscribe()
        self._client = client

    async def stop(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await client.close()
