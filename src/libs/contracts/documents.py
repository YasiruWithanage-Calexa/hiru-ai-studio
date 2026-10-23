"""Uploaded production documents and retrieval (PLAN.md §7)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentRole(StrEnum):
    BIBLE = "bible"  # series / production bible: premise, tone, characters, world
    SCRIPT = "script"  # screenplay pages (scenes, dialogue)
    CANON_INDEX = "canon_index"  # lists of characters, locations, props with codes
    OUTLINE = "outline"  # episode or season outline / synopsis
    NOTES = "notes"  # director's or producer's notes
    OTHER = "other"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    REJECTED = "rejected"  # unusable as given (scanned PDF, wrong encoding); re-upload needed
    FAILED = "failed"  # our failure; re-ingest can fix it


class Corpus(StrEnum):
    CRAFT = "craft"  # global craft knowledge
    PRODUCTION_DOCS = "production_docs"
    CANON = "canon"
    MEMORY = "memory"


# Upload policy: text-layer PDF, Markdown and plain text only (PLAN.md Q8). No OCR.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".fountain": "text/plain",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Below this detection confidence the UI asks a person to confirm the role, and lists the file
# first ("files needing a role are listed first", context doc §6).
ROLE_CONFIRM_THRESHOLD = 0.6


class Document(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    detected_role: DocumentRole | None = None
    role_confidence: float | None = None
    role_reason: str = ""
    confirmed_role: DocumentRole | None = None
    page_count: int | None = None
    char_count: int | None = None
    chunk_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def role(self) -> DocumentRole | None:
        return self.confirmed_role or self.detected_role

    @property
    def needs_role(self) -> bool:
        if self.confirmed_role is not None:
            return False
        return self.detected_role is None or (self.role_confidence or 0) < ROLE_CONFIRM_THRESHOLD


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    corpora: list[Corpus] = Field(default_factory=lambda: [Corpus.PRODUCTION_DOCS])
    roles: list[DocumentRole] | None = None  # only documents with these (effective) roles
    k: int = Field(default=8, ge=1, le=30)
    rerank: bool = True


class Citation(BaseModel):
    document_id: UUID | None = None
    filename: str = ""
    source: str = ""  # repo path for craft knowledge
    heading: str = ""
    page_start: int | None = None
    page_end: int | None = None


class SearchHit(BaseModel):
    chunk_id: UUID
    corpus: Corpus
    heading: str
    context_header: str
    content: str
    score: float
    matched_by: list[str]  # "vector", "text", "rerank"
    citation: Citation
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    # "hybrid" with embeddings, "text" when no embedding was available (no OpenAI key yet,
    # or the embedding call failed); retrieval never fails just because one half is missing.
    mode: str
    reranked: bool
