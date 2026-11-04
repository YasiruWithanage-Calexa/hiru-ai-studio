"""A one-line context header per chunk ("Episode 3 script - Scene 12, Nimal and Kamala at the harbour at night"), stored
next to the chunk and embedded WITH it.

A chunk alone often lacks the facts that make it findable: dialogue never says which episode it is in. Every chunk
always gets the deterministic base header (file, role, section, pages); when the `chunk_contextualiser` agent answers
for a batch, its short line is appended. The agent is asked in batches of `BATCH`, against a document prefix identical
for every batch (the prompt cache discounts every batch after the first). This module is the code half of that.
"""
from __future__ import annotations

# Ported from services/doc_ingest/doc_ingest/engine/context.py (plan/2026-11-03 Phase 6).
import logging
from typing import Any

_logger = logging.getLogger(__name__)

BATCH = 20
MAX_LINE_CHARS = 240
ROLE_LABEL = {"bible": "series bible", "script": "script", "canon_index": "canon index", "outline": "outline",
              "notes": "notes", "other": "document"}


def base_header(filename: str, role: str, chunk: dict[str, Any]) -> str:
    parts = [filename, ROLE_LABEL[role]]
    if chunk.get("heading"):
        parts.append(chunk["heading"])
    if chunk.get("page_start"):
        pages = (f"p. {chunk['page_start']}" if chunk["page_start"] == chunk.get("page_end")
                 else f"pp. {chunk['page_start']}-{chunk.get('page_end')}")
        parts.append(pages)
    return " \u2014 ".join(parts)


def batches(chunks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [chunks[i: i + BATCH] for i in range(0, len(chunks), BATCH)]


def add_model_lines(out: dict[int, str], batch: list[dict[str, Any]], answer: list[dict[str, Any]] | None,
                    index: int = 0) -> None:
    """Append the model's line to the base header of each passage of `batch` it covered, in place. A passage it skipped
    or misnumbered keeps its base header; `answer` None (the call failed) leaves the whole batch on base headers."""
    if answer is None:
        return
    wanted = {int(c["ord"]) for c in batch}
    written = 0
    for item in answer:
        ord_ = int(item["ord"])
        line = " ".join(str(item["header"]).split())[:MAX_LINE_CHARS]
        if ord_ in wanted and line:
            out[ord_] = f"{out[ord_]} \u2014 {line}"
            wanted.discard(ord_)
            written += 1
    if wanted:
        _logger.warning("header batch %d: model covered %d of %d passages", index, written, len(batch))


def embedding_input(header: str, content: str) -> str:
    return f"{header}\n\n{content}"
