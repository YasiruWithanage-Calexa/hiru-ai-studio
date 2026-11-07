"""reader_episode hooks (plan/2026-11-06f §4.3).

One call per episode, run four at a time; the cast list (names, aliases, codes) keeps the speakers the same people
across episodes. The message is built by `contracts.doc_read_run`, the same bytes the doc_ingest service sends. The
document is data: it is inside labelled `<document>` tags, never in the system message. In pages mode the pages go
with it as a PDF (OpenAI's file input gives the model each page's image and text). No fallback: with no key, or a
failed call, the run in `contracts.doc_read_run` keeps the rules.
"""
from __future__ import annotations

from contracts.doc_read_run import piece_message
from hiru_ai.agents.reader.reader_episode.schema import Input


def user_message(inp: Input) -> str:
    return piece_message(inp)


def files(inp: Input) -> list[tuple[str, str]]:
    ask = inp
    if not ask.pdf_b64:
        return []
    return [(f"pages-{ask.first_page}-{ask.last_page}.pdf", ask.pdf_b64)]
