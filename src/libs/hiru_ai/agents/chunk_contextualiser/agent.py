"""chunk_contextualiser hooks. Ported from `doc_ingest/engine/context.py`.

The document prefix comes first and is identical for every batch of a document, so the prompt cache discounts every
batch after the first; the batch's own passages come last. The deterministic base header (file, role, section, pages) is
the system's; a model line is appended to it only when this agent answers.
"""
from __future__ import annotations

from hiru_ai.agents.chunk_contextualiser.schema import Input

SNIPPET_CHARS = 500
OVERVIEW_CHARS = 4000
ROLE_LABEL = {"bible": "series bible", "script": "script", "canon_index": "canon index", "outline": "outline",
              "notes": "notes", "other": "document"}


def user_message(inp: Input) -> str:
    prefix = (f"Document: {inp.filename} ({ROLE_LABEL[inp.role]})\n<overview>\n"
              f"{inp.overview[:OVERVIEW_CHARS]}\n</overview>\n\n")
    passages = "\n\n".join(
        f'<passage ord="{p.ord}">\n{p.heading}\n{p.content[:SNIPPET_CHARS]}\n</passage>' for p in inp.passages)
    return prefix + passages
