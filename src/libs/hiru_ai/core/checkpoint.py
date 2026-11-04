"""The LangGraph checkpointer: durable and resumable workflows.

With `SUPABASE__DB_URL` set, checkpoints live in Postgres (schema `graph`; the checkpointer creates and migrates
its own tables), so a graph survives the function instance: a retry resumes from the last finished node, and a
graph stopped on a question resumes hours later in another instance. Without it, an in-memory saver runs the
graph to the end in one go. Moved from structure_build's and canon_extract's `runtime/checkpoint.py` unchanged.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

_ready: set[str] = set()


@contextmanager
def saver(db_url: str) -> Iterator[tuple[BaseCheckpointSaver[Any], bool]]:
    """→ (checkpointer, durable?)."""
    if not db_url:
        yield InMemorySaver(), False
        return
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    with psycopg.connect(db_url, autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
        conn.execute("set search_path to graph")
        cp = PostgresSaver(conn)
        if db_url not in _ready:  # creates or migrates the checkpoint tables; once per instance
            cp.setup()
            _ready.add(db_url)
        yield cp, True


def thread_config(job_id: UUID | str) -> dict[str, Any]:
    """The run config that keys a graph's checkpoints by job (`thread_id = job_id`)."""
    return {"configurable": {"thread_id": str(job_id)}}
