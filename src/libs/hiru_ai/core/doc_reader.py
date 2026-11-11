"""The document reader in the graph engine (plan/2026-11-06f §4.5): the run in `contracts.doc_read_run` with the
`reader_canon`, `reader_episode` and `reader_repair` agents as its model calls.

Ingest reads a document once (`read`) and keeps the reading beside its text (`save`, `documents.reading_path`). The
structure build and the canon extraction load it (`load`) and make no model call. Off unless `READER__ENABLED` (a
person turns it on after the live eval) and a key is set; with it off nothing here is asked and every ingest is as
before.
"""
from __future__ import annotations

import io
import logging
import threading
from collections.abc import Callable
from typing import Any

from contracts.doc_read import READINGS, Reading, reading_path
from contracts.doc_read_run import Calls, Result, read_document
from hiru_ai.core import agents, llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings

_logger = logging.getLogger(__name__)
BUCKET = "documents"


def enabled() -> bool:
    return get_settings().reader.enabled and llm.models_enabled()


def wanted(role: str) -> bool:
    """The roles the reader reads (decision 4): a script, a bible, a canon index, an outline."""
    return enabled() and role in READINGS


def pdf_slicer(load: Callable[[], bytes]) -> Callable[[int, int], bytes]:
    """pages first..last (1-based) of the PDF as their own small PDF, in memory (pypdf; no new dependency). The file is
    read once, on the first slice; the slices are made one at a time (episode calls run in parallel)."""
    lock = threading.Lock()
    held: dict[str, Any] = {}

    def cut(first: int, last: int) -> bytes:
        from pypdf import PdfReader, PdfWriter

        with lock:
            if "reader" not in held:
                held["reader"] = PdfReader(io.BytesIO(load()))
            source = held["reader"]
            writer = PdfWriter()
            for n in range(max(1, first), min(len(source.pages), last) + 1):
                writer.add_page(source.pages[n - 1])
            out = io.BytesIO()
            writer.write(out)
            return out.getvalue()

    return cut


def read(ctx: RunContext, *, filename: str, role: str, text: str, pdf: Callable[[], bytes] | None,
         progress: Callable[[str], None] | None = None) -> Result:
    """Read one document with the three agents. `pdf` gives the original file's bytes (asked for only when the text
    is scrambled); None for a text file."""
    canon, piece, repair = (agents.build(i) for i in ("reader_canon", "reader_episode", "reader_repair"))
    calls = Calls(canon=lambda ask: canon.run(ask, ctx), piece=lambda ask: piece.run(ask, ctx),
                  repair=lambda ask: repair.run(ask, ctx), pdf=pdf_slicer(pdf) if pdf is not None else None)
    return read_document(filename, role, text, calls, workers=get_settings().reader.workers, progress=progress)


def save(ctx: RunContext, text_path: str, reading: Reading) -> str:
    """Keep the reading beside the document's text. -> its path."""
    path = reading_path(text_path)
    files = ctx.need("files")
    # the documents bucket allows text/plain (the doc_ingest service saves it so): application/json is refused (415)
    files.upload(BUCKET, path, reading.dumps().encode("utf-8"), "text/plain; charset=utf-8")
    return path


def load(ctx: RunContext, document: dict[str, Any]) -> Reading | None:
    """The document's stored reading, or None (never read, an older format, or storage cannot say)."""
    path = str(document.get("reading_path") or "")
    docs = ctx.ports.docs
    if not path or docs is None:
        return None
    try:
        return Reading.loads(docs.text(path))
    except Exception:
        _logger.warning("the reading of %s could not be loaded; the rules read it", document.get("filename"),
                        exc_info=True)
        return None
