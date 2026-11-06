"""story_reader hooks.

The model reads the document once and says what is in it; `steps/story_check` then keeps only what is really in
the text.
The document is data: it is wrapped in tags and labelled, and never placed in the system message.
"""
from __future__ import annotations

from hiru_ai.agents.story_reader.schema import Input
from hiru_ai.core.middleware.base import Document
from hiru_ai.core.middleware.untrusted_text import wrap

MAX_DOC_CHARS = 60_000  # about 30 pages; a longer document is read up to here and warned about (plan D4)


def user_message(inp: Input) -> str:
    return wrap(Document(inp.filename, "unknown", inp.text[:MAX_DOC_CHARS]))
