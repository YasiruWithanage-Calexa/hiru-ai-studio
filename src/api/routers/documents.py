"""Production documents: upload, list, confirm role, re-ingest, delete.

Upload policy (PLAN.md Q8): text-layer PDF, Markdown, plain text / Fountain, at most 25 MB.
The API checks what it can cheaply and safely (extension, size, magic bytes, binary content);
everything that needs parsing happens in the doc_ingest function, which reports per document
(status `rejected` with a message the uploader can act on).

The same file uploaded twice to one production is one document (SHA-256), so a double click
or a re-upload does not index the same text twice.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, computed_field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import media_links
from api.workers import task_manager
from contracts.documents import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    Document,
    DocumentRole,
    DocumentStatus,
)
from contracts.jobs import JobKind
from contracts.roles import Permission

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/productions/{production_id}/documents", tags=["documents"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanManage = Annotated[ProductionAccess, Depends(require_permission(Permission.MANAGE_DOCUMENTS))]
BUCKET = "documents"
_READ_CHUNK = 1024 * 1024


class DocumentOut(Document):
    file_url: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_role(self) -> DocumentRole | None:
        return self.role

    @computed_field  # type: ignore[prop-decorator]
    @property
    def role_needs_confirmation(self) -> bool:
        return self.needs_role


class UploadResult(BaseModel):
    document: DocumentOut
    job_id: UUID | None
    duplicate: bool


class RoleUpdate(BaseModel):
    role: DocumentRole


class Dispatched(BaseModel):
    job_id: UUID


def _out(row: Row) -> DocumentOut:
    doc = DocumentOut.model_validate(row)
    doc.file_url = media_links.url(BUCKET, row["storage_path"], download=row["filename"])
    return doc


def safe_filename(name: str) -> str:
    """Display name kept as uploaded (minus path parts); storage gets an ASCII-safe slug."""
    return (name or "document").replace("\\", "/").split("/")[-1].strip()[:255] or "document"


def _storage_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip("-.")
    return slug[-120:] or "document"


async def _read_limited(file: UploadFile) -> bytes:
    data = bytearray()
    while chunk := await file.read(_READ_CHUNK):
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"Files can be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return bytes(data)


def _check_content(ext: str, data: bytes) -> None:
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This file is not a valid PDF.")
    elif b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "This does not look like a text file. Upload a PDF, Markdown or plain text file.")


async def _dispatch_ingest(repos: Repos, access: ProductionAccess, document_id: UUID) -> UUID:
    return await task_manager.dispatch(
        JobKind.DOC_INGEST, repos, actor_user_id=access.user.id, production_id=access.production_id,
        request={"document_id": str(document_id)}, state={"document_id": str(document_id)})


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_document(production_id: UUID, access: CanManage, repos: ReposDep, response: Response,
                          file: Annotated[UploadFile, File()],
                          role: Annotated[DocumentRole | None, Form()] = None) -> UploadResult:
    """`role` is optional: a person who already knows what the file is says so here, and the
    reader uses it from the start (no race with a later confirmation). Otherwise it is detected."""
    filename = safe_filename(file.filename or "")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Upload a PDF, Markdown (.md) or plain text (.txt, .fountain) file.")
    data = await _read_limited(file)
    _check_content(ext, data)
    sha = hashlib.sha256(data).hexdigest()

    existing = await repos.documents.find_by_hash(production_id, sha)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return UploadResult(document=_out(existing), job_id=None, duplicate=True)

    document_id = uuid4()
    mime = ALLOWED_EXTENSIONS[ext]
    path = f"{production_id}/{document_id}/{_storage_slug(filename)}"
    await repos.storage.upload(BUCKET, path, data, mime)
    try:
        row = await repos.documents.create({
            "id": str(document_id), "production_id": str(production_id), "filename": filename,
            "mime_type": mime, "size_bytes": len(data), "sha256": sha, "storage_path": path,
            "status": DocumentStatus.UPLOADED.value, "uploaded_by": str(access.user.id),
            **({"confirmed_role": role.value, "confirmed_by": str(access.user.id)} if role else {}),
        })
    except Exception:
        await repos.storage.remove(BUCKET, path)  # no orphaned file without a row
        raise
    await repos.audit.record(action="document.upload", entity="document", entity_id=str(document_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"filename": filename, "size_bytes": len(data)})
    job_id = await _dispatch_ingest(repos, access, document_id)
    return UploadResult(document=_out(row), job_id=job_id, duplicate=False)


@router.get("", response_model=list[DocumentOut])
async def list_documents(production_id: UUID, _: CanView, repos: ReposDep) -> list[DocumentOut]:
    """Files that need a person to confirm their role come first, then newest first."""
    docs = [_out(r) for r in await repos.documents.list(production_id)]
    return sorted(docs, key=lambda d: (not d.needs_role, -d.created_at.timestamp()))


async def _get(repos: Repos, production_id: UUID, document_id: UUID) -> Row:
    row = await repos.documents.get(production_id, document_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    return row


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(production_id: UUID, document_id: UUID, _: CanView, repos: ReposDep) -> DocumentOut:
    return _out(await _get(repos, production_id, document_id))


@router.patch("/{document_id}", response_model=UploadResult)
async def confirm_role(production_id: UUID, document_id: UUID, body: RoleUpdate, access: CanManage,
                       repos: ReposDep) -> UploadResult:
    """A person confirms (or corrects) what the document is. Scripts are chunked by scene, so
    switching into or out of `script` re-ingests the document."""
    row = await _get(repos, production_id, document_id)
    before = row.get("confirmed_role") or row.get("detected_role")
    row = await repos.documents.update(document_id, {"confirmed_role": body.role.value,
                                                     "confirmed_by": str(access.user.id)})
    await repos.audit.record(action="document.confirm_role", entity="document", entity_id=str(document_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"role": [before, body.role.value]})
    job_id = None
    rechunk = (before == DocumentRole.SCRIPT) != (body.role == DocumentRole.SCRIPT)
    if rechunk and row["status"] not in (DocumentStatus.REJECTED, DocumentStatus.PROCESSING):
        job_id = await _dispatch_ingest(repos, access, document_id)
    return UploadResult(document=_out(row), job_id=job_id, duplicate=False)


@router.post("/{document_id}/reingest", response_model=Dispatched, status_code=status.HTTP_202_ACCEPTED)
async def reingest(production_id: UUID, document_id: UUID, access: CanManage, repos: ReposDep) -> Dispatched:
    row = await _get(repos, production_id, document_id)
    if row["status"] == DocumentStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document is being read right now.")
    return Dispatched(job_id=await _dispatch_ingest(repos, access, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(production_id: UUID, document_id: UUID, access: CanManage,
                          repos: ReposDep) -> Response:
    row = await _get(repos, production_id, document_id)
    await repos.documents.delete(document_id)  # chunks go with it (on delete cascade)
    try:
        await repos.storage.remove(BUCKET, row["storage_path"])
        if row.get("text_path"):
            await repos.storage.remove(BUCKET, row["text_path"])
    except Exception:
        _logger.exception("storage cleanup failed document=%s", document_id)
    await repos.audit.record(action="document.delete", entity="document", entity_id=str(document_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"filename": row["filename"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
