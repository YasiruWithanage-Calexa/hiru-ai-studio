"""One document, start to finish: download → extract → role → chunk → headers → embed → index.

Outcomes, each written to the document row:
  ready     indexed. With no OpenAI key, or if embedding fails, it is still indexed for
            keyword search and says so in `warnings`; re-ingest later to add meaning search.
  rejected  the FILE is unusable as given (scanned PDF, not UTF-8 …). The job itself is DONE:
            it did its work, and a retry would reject it again.
  failed    OUR failure (an exception). Re-ingest can fix it.

Idempotent for Cloud Tasks re-delivery: a finished job is skipped, chunks are replaced (not
appended), and embeddings are reused by hash so a re-run does not pay for them twice.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Protocol
from uuid import UUID

from contracts.doc_read import READINGS, Reading, reading_path
from contracts.doc_read_quality import SCRAMBLED_WARNING, quality
from contracts.doc_read_run import transcribed_text
from contracts.documents import DocumentRole, DocumentStatus
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from doc_ingest.engine import context, reader, roles
from doc_ingest.engine.chunking import chunk
from doc_ingest.engine.extract import Extracted, Line, Rejected, extract
from doc_ingest.runtime.llm import LLM

_logger = logging.getLogger(__name__)

BUCKET = "documents"
EMBED_BATCH = 64
FORM_FEED = "\f"  # between PDF pages in the stored text
AGENT = "document_reader"

NO_KEY_WARNING = ("Indexed for keyword search only (no OpenAI key configured). Re-ingest after "
                  "adding the key to enable search by meaning.")
EMBED_FAILED_WARNING = ("Search by meaning is unavailable for this document because the "
                        "embedding step failed. Keyword search works; re-ingest to retry.")
LEGACY_FONT_WARNING = ("No Sinhala Unicode text was found in this script. If its Sinhala is typed "
                       "in a legacy font (such as FM Abhaya), the text could not be read: export "
                       "it again using a Unicode Sinhala font (such as Iskoola Pota or Noto Sans "
                       "Sinhala).")


class StoreLike(Protocol):
    def get_job(self, job_id: UUID) -> dict[str, Any] | None: ...
    def set_job(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any],
              agent: str | None = None) -> None: ...
    def get_document(self, document_id: UUID) -> dict[str, Any] | None: ...
    def update_document(self, document_id: UUID, fields: dict[str, Any]) -> None: ...
    def download(self, bucket: str, path: str) -> bytes: ...
    def upload_text(self, bucket: str, path: str, text: str) -> None: ...
    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]: ...
    def replace_chunks(self, document_id: UUID, rows: list[dict[str, Any]]) -> None: ...


def legacy_font_warning(extracted: Extracted, role: DocumentRole) -> str | None:
    """Hiru's dialogue is Sinhala, so a script PDF with no Sinhala code points is suspicious. Sinhala that is there but
    scrambled (a font that stores the vowel signs in the wrong order, plan/2026-11-06f §4.1) is warned about too."""
    if extracted.kind != "pdf":
        return None
    if role == DocumentRole.SCRIPT and not extracted.has_sinhala:
        return LEGACY_FONT_WARNING
    if role.value in READINGS and extracted.has_sinhala and \
            quality(paged_text(extracted).split(FORM_FEED)).mode == "pages":
        return SCRAMBLED_WARNING
    return None


def from_transcription(extracted: Extracted, reading: Reading) -> Extracted:
    """The reader's clean transcription as the text to chunk and search (decision 8), page by page."""
    clean = transcribed_text(reading, extracted.page_count or 1)
    lines = [Line(line, n) for n, page in enumerate(clean.split(FORM_FEED), start=1)
             for line in page.split("\n") if line.strip()]
    return Extracted(extracted.kind, lines, extracted.page_count, list(extracted.warnings))


def paged_text(extracted: Extracted) -> str:
    """The normalised text with a form feed between PDF pages: what later engines read (the
    structure build parses scripts from it) instead of parsing the original file again."""
    pages: list[list[str]] = []
    page: object = object()
    for line in extracted.lines:
        if line.page != page or not pages:
            pages.append([])
            page = line.page
        pages[-1].append(line.text)
    return FORM_FEED.join("\n".join(p) for p in pages)


def embed_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def read_whole(store: StoreLike, llm: LLM, job_id: UUID, document_id: UUID, filename: str, role: DocumentRole,
               extracted: Extracted, text_path: str, data: bytes,
               progress: Any) -> tuple[dict[str, Any], Reading | None]:
    """Read the document with the reader and keep the reading beside its text. -> (the document row's reading
    columns, the reading or None). No reading: the rules read the document as before, and the job says why."""
    try:
        outcome = reader.read(llm, filename=filename, role=role.value, text=paged_text(extracted),
                              pdf=(lambda: data) if extracted.kind == "pdf" else None, progress=progress)
    except Exception:
        _logger.warning("the document reader failed for %s; the rules read it", filename, exc_info=True)
        outcome = None
    if outcome is None or outcome.reading is None:
        why = outcome.reason if outcome is not None else "the reader failed"
        store.event(job_id, JobEventType.WARNING,
                    {"text": f"{filename}: the reader could not read it ({why}); the rules read it instead.",
                     "document_id": str(document_id)}, agent=AGENT)
        return {"reading_path": None, "read_from": None}, None
    read = outcome.reading
    path = reading_path(text_path)
    store.upload_text(BUCKET, path, read.dumps())
    scenes = sum(len(e.scenes) for e in read.episodes)
    lines = sum(1 for e in read.episodes for s in e.scenes for b in s.blocks if b.kind == "dialogue")
    progress(f"Read {filename}: {len(read.episodes)} episodes, {scenes} scenes, {lines} spoken lines, "
             f"{len(read.canon.characters)} people"
             + (" (from the page images: check the dialogue)" if read.source == "pages" else ""))
    for note in [*read.notes, *read.unresolved]:
        store.event(job_id, JobEventType.WARNING, {"text": f"{filename}: {note}", "document_id": str(document_id)},
                    agent=AGENT)
    return {"reading_path": path, "read_from": read.source}, read


def run(payload: DispatchPayload, store: StoreLike, llm: LLM) -> dict[str, Any]:
    job_id = payload.job_id
    job = store.get_job(job_id)
    if job is None:
        return {"skipped": "missing job"}
    if job["status"] in ("done", "failed", "cancelled"):
        return {"skipped": job["status"]}

    document_id = UUID(str(payload.state["document_id"]))
    doc = store.get_document(document_id)
    if doc is None:  # deleted while queued
        store.set_job(job_id, JobStatus.DONE, result={"skipped": "document deleted"})
        return {"skipped": "document deleted"}

    def progress(text: str, **extra: Any) -> None:
        store.event(job_id, JobEventType.PROGRESS, {"text": text, "document_id": str(document_id), **extra},
                    agent=AGENT)

    store.set_job(job_id, JobStatus.RUNNING)
    store.update_document(document_id, {"status": DocumentStatus.PROCESSING.value, "error": None})
    filename = doc["filename"]

    progress(f"Reading {filename}")
    data = store.download(BUCKET, doc["storage_path"])
    try:
        extracted = extract(data, filename, doc["mime_type"])
    except Rejected as rejected:
        store.update_document(document_id, {"status": DocumentStatus.REJECTED.value,
                                            "error": str(rejected), "chunk_count": 0})
        store.replace_chunks(document_id, [])
        result: dict[str, Any] = {"document_id": str(document_id), "status": "rejected", "reason": str(rejected)}
        store.set_job(job_id, JobStatus.DONE, result=result)
        return result

    text = extracted.text
    text_path = f"{doc['production_id']}/{document_id}/extracted.txt"
    store.upload_text(BUCKET, text_path, paged_text(extracted))
    guess = roles.detect(filename, text, llm.asker(tier="medium", phase="doc_ingest.role",
                                                   schema_name="document_role", schema=roles.ROLE_SCHEMA))
    role = DocumentRole(doc["confirmed_role"]) if doc.get("confirmed_role") else guess.role
    progress(f"{filename} looks like a {context.ROLE_LABEL[guess.role]}", role=guess.role.value,
             confidence=guess.confidence)

    original = extracted
    reading_fields: dict[str, Any] = {}
    if reader.wanted(llm, role.value):  # plan/2026-11-06f: the model reads the whole document into one format
        reading_fields, read = read_whole(store, llm, job_id, document_id, filename, role, extracted, text_path,
                                          data, progress)
        if read is not None and read.source == "pages":
            extracted = from_transcription(extracted, read)
            text = extracted.text

    chunks = chunk(extracted, script_like=role == DocumentRole.SCRIPT)
    progress(f"Split into {len(chunks)} passages")
    head = context.headers(filename, role, text, chunks,
                           llm.asker(tier="low", phase="doc_ingest.headers",
                                     schema_name="chunk_headers", schema=context.HEADER_SCHEMA))

    warnings: list[str] = []
    if (w := legacy_font_warning(original, role)) is not None:
        warnings.append(w)

    model = llm.config.embedding_model
    inputs = {c.ord: context.embedding_input(head[c.ord], c) for c in chunks}
    hashes = {o: embed_hash(model, t) for o, t in inputs.items()}
    vectors: dict[int, list[float]] = {}
    if llm.enabled:
        reuse = store.existing_embeddings(document_id)
        for o, h in hashes.items():
            if h in reuse and reuse[h][1] == model:
                vectors[o] = reuse[h][0]
        todo = [o for o in inputs if o not in vectors]
        try:
            for i in range(0, len(todo), EMBED_BATCH):
                batch = todo[i: i + EMBED_BATCH]
                for o, vec in zip(batch, llm.embed([inputs[o] for o in batch], phase="doc_ingest.embed"),
                                  strict=True):
                    vectors[o] = vec
            progress(f"Embedded {len(todo)} passages ({len(inputs) - len(todo)} reused)")
        except Exception:
            _logger.exception("embedding failed document=%s", document_id)
            vectors = {}
            warnings.append(EMBED_FAILED_WARNING)
    else:
        warnings.append(NO_KEY_WARNING)

    rows = [{
        "corpus": "production_docs",
        "production_id": doc["production_id"],
        "document_id": str(document_id),
        "ord": c.ord,
        "heading": c.heading,
        "context_header": head[c.ord],
        "content": c.content,
        "content_hash": hashes[c.ord],
        "embedding": vectors.get(c.ord),
        "embedding_model": model if c.ord in vectors else "",
        "meta": {"page_start": c.page_start, "page_end": c.page_end, "kind": c.kind},
    } for c in chunks]
    store.replace_chunks(document_id, rows)

    store.update_document(document_id, {
        "status": DocumentStatus.READY.value,
        "detected_role": guess.role.value,
        "role_confidence": guess.confidence,
        "role_reason": f"{guess.reason} ({guess.source})",
        "page_count": extracted.page_count,
        "char_count": extracted.char_count,
        "chunk_count": len(rows),
        "text_path": text_path,
        "warnings": warnings,
        "error": None,
        **reading_fields,
    })
    result = {"document_id": str(document_id), "status": "ready", "role": guess.role.value,
              "chunks": len(rows), "embedded": len(vectors)}
    store.set_job(job_id, JobStatus.DONE, result=result)
    return result
