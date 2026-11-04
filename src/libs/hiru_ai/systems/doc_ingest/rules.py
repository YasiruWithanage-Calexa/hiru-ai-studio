"""The deterministic glue of the ingest: text with page breaks, embedding hashes, the warnings a person reads, and the
rows that go to `chunks`. Ported from `doc_ingest/engine/pipeline.py`; no model, no I/O."""
from __future__ import annotations

import hashlib
from typing import Any

FORM_FEED = "\f"  # between PDF pages in the stored text
BUCKET = "documents"
EMBED_BATCH = 64
AGENT = "document_reader"

NO_KEY_WARNING = ("Indexed for keyword search only (no OpenAI key configured). Re-ingest after "
                  "adding the key to enable search by meaning.")
EMBED_FAILED_WARNING = ("Search by meaning is unavailable for this document because the "
                        "embedding step failed. Keyword search works; re-ingest to retry.")
LEGACY_FONT_WARNING = ("No Sinhala Unicode text was found in this script. If its Sinhala is typed "
                       "in a legacy font (such as FM Abhaya), the text could not be read: export "
                       "it again using a Unicode Sinhala font (such as Iskoola Pota or Noto Sans "
                       "Sinhala).")


def legacy_font_warning(extracted: dict[str, Any], role: str) -> str | None:
    """Hiru's dialogue is Sinhala, so a script PDF with no Sinhala code points is suspicious."""
    if extracted["kind"] == "pdf" and role == "script" and not extracted["has_sinhala"]:
        return LEGACY_FONT_WARNING
    return None


def paged_text(lines: list[dict[str, Any]]) -> str:
    """The normalised text with a form feed between PDF pages: what later engines read (the structure build parses
    scripts from it) instead of parsing the original file again."""
    pages: list[list[str]] = []
    page: object = object()
    for line in lines:
        if line["page"] != page or not pages:
            pages.append([])
            page = line["page"]
        pages[-1].append(line["text"])
    return FORM_FEED.join("\n".join(p) for p in pages)


def embed_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def chunk_rows(doc: dict[str, Any], document_id: str, chunks: list[dict[str, Any]], headers: dict[str, str],
               hashes: dict[int, str], vectors: dict[int, list[float]], model: str) -> list[dict[str, Any]]:
    return [{
        "corpus": "production_docs",
        "production_id": doc["production_id"],
        "document_id": document_id,
        "ord": c["ord"],
        "heading": c["heading"],
        "context_header": headers[str(c["ord"])],
        "content": c["content"],
        "content_hash": hashes[c["ord"]],
        "embedding": vectors.get(c["ord"]),
        "embedding_model": model if c["ord"] in vectors else "",
        "meta": {"page_start": c["page_start"], "page_end": c["page_end"], "kind": c["kind"]},
    } for c in chunks]
