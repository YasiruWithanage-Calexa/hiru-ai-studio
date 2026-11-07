"""reader_canon hooks (plan/2026-11-06f §4.3).

One call per front part (the pages before the first episode) or per window of a bible. The message is built by
`contracts.doc_read_run`, the same bytes the doc_ingest service sends. The document is data: it is inside labelled
`<document>` tags, never in the system message. In pages mode the pages go with it as a PDF (OpenAI's file input
gives the model each page's image and text). No fallback: with no key, or a failed call, the run in
`contracts.doc_read_run` keeps the rules.
"""
from __future__ import annotations

from contracts.doc_read_run import canon_message
from hiru_ai.agents.reader.reader_canon.schema import Input


def user_message(inp: Input) -> str:
    return canon_message(inp)


def files(inp: Input) -> list[tuple[str, str]]:
    ask = inp
    if not ask.pdf_b64:
        return []
    return [(f"pages-{ask.first_page}-{ask.last_page}.pdf", ask.pdf_b64)]
