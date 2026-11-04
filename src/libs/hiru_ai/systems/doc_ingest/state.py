"""The doc_ingest system's state. Plain data only (JSON-able), so a checkpointer could hold it."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    document: dict[str, Any]  # the documents row
    filename: str
    extracted: dict[str, Any]  # kind, lines [{text, page}], page_count, char_count, has_sinhala
    text: str
    text_path: str
    guess: dict[str, Any]  # role, confidence, reason, source
    role: str  # the role chunks and headers use: the person's confirmed one, else the guess
    chunks: list[dict[str, Any]]
    headers: dict[str, str]  # "<ord>" -> header
    warnings: list[str]
    vectors: dict[int, list[float]]
    embedding_model: str
    hashes: dict[int, str]
    result: dict[str, Any]
    rejected: bool
