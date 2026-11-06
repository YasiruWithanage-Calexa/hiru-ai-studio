"""memory_reader hooks (plan/2026-11-05d M1).

The model reads the document once and lists the direction it gives; `steps/memory_check` then keeps only what is really
in the text. The document is data: it is wrapped in tags and labelled (`untrusted_text.wrap`), and never placed in the
system message. With no model there is nothing to read, so there is no fallback: the ingest leaves the
document's entries as they were.
"""
from __future__ import annotations

from hiru_ai.agents.memory_reader.schema import Input
from hiru_ai.core.middleware.base import Document
from hiru_ai.core.middleware.untrusted_text import wrap

MAX_DOC_CHARS = 60_000  # about 30 pages; a longer document is read up to here and warned about


def user_message(inp: Input) -> str:
    return wrap(Document(inp.filename, "unknown", inp.text[:MAX_DOC_CHARS]))
