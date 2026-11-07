"""The document reader in this function (plan/2026-11-06f §4.5): the run in `contracts.doc_read_run` with this
function's own model wrapper as its three calls. The graph engine runs the same run with its agents
(`hiru_ai.core.doc_reader`); the prompts in `reader_prompts/` are copies of the agents' (`tests/parity` holds them
equal), and the messages are built in `contracts`, so both engines send the same bytes.
"""
from __future__ import annotations

import io
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contracts.doc_read import READINGS, CanonRead, PatchW, PieceRead, strict_schema
from contracts.doc_read_run import (
    Calls,
    CanonAsk,
    PieceAsk,
    RepairAsk,
    Result,
    canon_message,
    piece_message,
    read_document,
    repair_message,
)
from doc_ingest.runtime.llm import LLM

PROMPTS = Path(__file__).resolve().parent / "reader_prompts"
TIER = "reader"


def system(ident: str) -> str:
    return (PROMPTS / f"{ident}.md").read_text(encoding="utf-8")


def wanted(llm: LLM, role: str) -> bool:
    return llm.config.reader_enabled and llm.enabled and role in READINGS


def _files(first: int, last: int, data: str) -> list[tuple[str, str]] | None:
    return [(f"pages-{first}-{last}.pdf", data)] if data else None


def pdf_slicer(load: Callable[[], bytes]) -> Callable[[int, int], bytes]:
    """pages first..last (1-based) as their own small PDF, in memory; the file is read once, slices one at a time."""
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


def calls(llm: LLM, pdf: Callable[[], bytes] | None) -> Calls:
    canon_system, piece_system, repair_system = (system(i) for i in ("reader_canon", "reader_episode",
                                                                     "reader_repair"))

    def canon(ask: CanonAsk) -> CanonRead:
        return CanonRead.model_validate(llm.json(
            tier=TIER, phase="doc_ingest.reader.canon", system=canon_system, user=canon_message(ask),
            schema_name="CanonRead", schema=strict_schema(CanonRead),
            files=_files(ask.first_page, ask.last_page, ask.pdf_b64)))

    def piece(ask: PieceAsk) -> PieceRead:
        return PieceRead.model_validate(llm.json(
            tier=TIER, phase="doc_ingest.reader.episode", system=piece_system, user=piece_message(ask),
            schema_name="PieceRead", schema=strict_schema(PieceRead),
            files=_files(ask.first_page, ask.last_page, ask.pdf_b64)))

    def repair(ask: RepairAsk) -> PatchW:
        return PatchW.model_validate(llm.json(
            tier=TIER, phase="doc_ingest.reader.repair", system=repair_system, user=repair_message(ask),
            schema_name="PatchW", schema=strict_schema(PatchW),
            files=_files(ask.piece.first_page, ask.piece.last_page, ask.piece.pdf_b64)))

    return Calls(canon=canon, piece=piece, repair=repair, pdf=pdf_slicer(pdf) if pdf is not None else None)


def read(llm: LLM, *, filename: str, role: str, text: str, pdf: Callable[[], bytes] | None,
         progress: Callable[[str], None] | None = None) -> Result:
    return read_document(filename, role, text, calls(llm, pdf), workers=llm.config.reader_workers, progress=progress)
