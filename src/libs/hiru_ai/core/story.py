"""A document's reading: what the story reader found in it, checked against the text, kept beside `extracted.txt`
(plan/2026-11-05c S3).

The ingest makes it once (`read` + `save`). Anything that needs it later (the structure build, the canon) asks
`story_for`, which loads the saved reading, or reads then and keeps it, so a document ingested before the reader existed
works without a re-ingest. Absent-safe: with no model, or a model that fails, the answer is None and the caller keeps
its rules.
"""
from __future__ import annotations

import logging
from typing import Any

from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext

_logger = logging.getLogger(__name__)
BUCKET = "documents"


def read(ctx: RunContext, filename: str, text: str) -> dict[str, Any] | None:
    """Ask the reader about `text`, check every quote it gave against `text`. None when it cannot answer."""
    if not llm.models_enabled() or not text.strip():
        return None
    agent = agents.build("story_reader")
    try:
        out = agent.run({"filename": filename, "text": text}, ctx)
    except Exception:
        _logger.warning("story reader failed for %s", filename, exc_info=True)
        return None
    check = parts.step("story_check")
    return check.check(out.model_dump(), text, limit=agent.hooks.MAX_DOC_CHARS)


def save(ctx: RunContext, text_path: str, story: dict[str, Any]) -> None:
    files = ctx.ports.files
    if files is None:
        return
    check = parts.step("story_check")
    files.upload(BUCKET, check.story_path(text_path), check.dumps(story).encode("utf-8"), "application/json")


def load(ctx: RunContext, text_path: str, text: str) -> dict[str, Any] | None:
    """The saved reading of `text`, or None (never read, read from other text, or storage cannot say)."""
    docs = ctx.ports.docs
    if docs is None or not text_path:
        return None
    check = parts.step("story_check")
    try:
        raw = docs.text(check.story_path(text_path))
    except Exception:  # not there yet: the usual case for a document ingested before the reader existed
        return None
    return check.loads(raw, text)


def story_for(ctx: RunContext, doc: dict[str, Any], text: str) -> dict[str, Any] | None:
    """`doc`'s reading: the saved one, else read now and keep it (a failure to keep it is only logged)."""
    path = str(doc.get("text_path") or "")
    story = load(ctx, path, text)
    if story is not None:
        return story
    story = read(ctx, str(doc.get("filename") or ""), text)
    if story is not None and path:
        try:
            save(ctx, path, story)
        except Exception:
            _logger.warning("could not keep the reading of %s", doc.get("filename"), exc_info=True)
    return story
