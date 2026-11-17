"""What the browser is told about work in progress (plan/2026-11-13d): `GET /live` answers with these, and the pushed
stream (`GET /stream`) sends the same shapes one at a time. Ids, statuses, timestamps and event numbers only: never a
row, a cost, a model, a prompt or a storage path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ACTIVE = frozenset({"pending", "queued", "running", "processing"})
BUILD = "structure_build"


class LiveItem(BaseModel):
    kind: Literal["frame", "render", "document", "job"]
    id: str
    shot_id: str | None = None
    status: str
    job_kind: str | None = None  # for kind "job": which job
    updated_at: datetime
    # For the structure build's job: its newest event number (plan/2026-11-13d phase 2). The build page reads only the
    # events after the one it has when this moves; nothing else carries it.
    seq: int | None = None


class LiveNotice(BaseModel):
    """Something changed that is not work in progress (stream only): the director board, or a chat thread another
    person wrote in. The page reads the one thing named, if it shows it."""

    kind: Literal["board", "thread"]
    id: str | None = None  # the thread's id; None for the board
    at: datetime


class Live(BaseModel):
    busy: bool  # any item still active: the caller polls only while this is true
    version: datetime | None  # newest `updated_at` seen; pass it back as `since`
    items: list[LiveItem]
