"""The production's memory, as the ingest makes it and the agents' middleware reads it (plan/2026-11-05d).

`read` asks the memory reader about one document and checks every quote it gave; `save` writes the result for that
document. `entries` is what the middleware (and anything else that wants the direction) loads: the production's usable
entries, read once per run. In `core` so the ingest, the middleware and the adapters share one rule without importing
each other. Absent-safe: with no model, no port, a table the database does not have yet, or a call that fails, the
answer is None or no entries, and the caller carries on as it did before the memory existed.
"""
from __future__ import annotations

import logging
from typing import Any

from contracts.jobs import JobEventType
from contracts.memory import target_text, topic_key
from hiru_ai.core.context import RunContext

_logger = logging.getLogger(__name__)
_LOADED = "entries"


def read(ctx: RunContext, filename: str, text: str) -> dict[str, Any] | None:
    """Ask the reader about `text` and check every quote it gave against `text`: `{"entries", "dropped", "warnings"}`.
    None when it cannot answer (no model, or the call failed): the document's earlier entries then stay as they are."""
    from hiru_ai.core import (  # lazy: the middleware imports this module, and the registry the middleware
        agents,
        llm,
        parts,
    )

    if not llm.models_enabled() or not text.strip():
        return None
    agent = agents.build("memory_reader")
    limit = agent.hooks.MAX_DOC_CHARS
    try:
        out = agent.run({"filename": filename, "text": text}, ctx)
    except Exception:
        _logger.warning("memory reader failed for %s", filename, exc_info=True)
        return None
    checked: dict[str, Any] = parts.step("memory_check").check([e.model_dump() for e in out.entries], text[:limit])
    if len(text) > limit:
        checked["warnings"] = [f"only the first {limit} characters were read for direction", *checked["warnings"]]
    return checked


def key(row: dict[str, Any]) -> tuple[str, str, str]:
    """What makes two entries the same direction: topic, target and words (case and spacing aside)."""
    from hiru_ai.core import parts

    flat = parts.step("verbatim_check").flat
    return (topic_key(str(row.get("topic") or "")), target_text(str(row.get("applies_to") or "")).casefold(),
            str(flat(str(row.get("says") or ""))))


def fresh(kept: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The new entries that are not already said by one a person has touched (`kept`): a rejected direction does not
    come back as a draft, and an approved one is not written twice."""
    said = {key(row) for row in kept}
    return [e for e in entries if key(e) not in said]


def is_reader_draft(row: dict[str, Any]) -> bool:
    return row.get("source") == "reader" and row.get("status") == "draft"


def entries(ctx: RunContext) -> list[dict[str, Any]]:
    """The production's entries a run may use (`draft` and `approved`, never `rejected`), read once per run. Empty when
    the run has no production or no memory port, or the table cannot be read (the migration is not applied yet)."""
    if _LOADED in ctx.memory_cache:
        loaded: list[dict[str, Any]] = ctx.memory_cache[_LOADED]
        return loaded
    rows: list[dict[str, Any]] = []
    port = ctx.ports.memory
    if port is not None and ctx.production_id is not None:
        try:
            rows = [r for r in port.entries(ctx.production_id) if r.get("status") != "rejected"]
        except Exception:
            _logger.warning("production memory could not be read; going on without it", exc_info=True)
    ctx.memory_cache[_LOADED] = rows
    return rows


def genre(ctx: RunContext, default: str) -> str:
    """What the production says its genre is (a `fact` about the whole drama that names the genre), or `default`."""
    for row in entries(ctx):
        if (row.get("strength") == "fact" and row.get("applies_to") == "production" and row.get("topic") == "series"
                and "genre" in f"{row.get('says')} {row.get('quote')}".casefold()):
            return " ".join(str(row["says"]).split())
    return default


def conflicts(ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The conflicts in the production's memory (`steps/memory_conflicts`): entries that disagree across documents, and
    entries that ask for what the system cannot make. `rows` default to the run's entries. Never raises."""
    from hiru_ai.core import parts

    rows = entries(ctx) if rows is None else rows
    if not rows:
        return []
    dates: dict[str, str] = {}
    docs = ctx.ports.docs
    if docs is not None and ctx.production_id is not None:
        try:
            dates = {str(d["id"]): str(d.get("created_at") or "") for d in docs.documents(ctx.production_id)}
        except Exception:
            _logger.warning("documents could not be listed for the memory's conflicts", exc_info=True)
    try:
        found: list[dict[str, Any]] = parts.step("memory_conflicts").find(rows, dates)
    except Exception:
        _logger.warning("memory conflicts could not be checked", exc_info=True)
        return []
    return found


def report(ctx: RunContext, jobs: Any, job_id: Any, agent: str | None = None) -> int:
    """Put each conflict of the production's memory on the job's events as a warning, once. -> how many."""
    found = conflicts(ctx)
    for conflict in found:
        jobs.event(job_id, JobEventType.WARNING, {"text": conflict["text"]}, agent=agent)
    return len(found)
