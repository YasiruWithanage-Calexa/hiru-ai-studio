"""Which documents a search may read. Decided from data the caller trusts, never from model text (CLAUDE.md).

Only documents that are READY are searchable: a document being re-ingested has its chunks replaced mid-flight. A role
filter keeps the documents whose confirmed (else detected) role is wanted; a document with no role matches no filter.
"""
from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from contracts.documents import DocumentRole, DocumentStatus

Row = dict[str, Any]


def role_of(doc: Row) -> str | None:
    return doc.get("confirmed_role") or doc.get("detected_role")


def ready_documents(docs: Iterable[Row], roles: Collection[DocumentRole] | None = None) -> dict[str, Row]:
    """The documents a search may read, by id, in the order given."""
    wanted = set(roles) if roles else None
    out: dict[str, Row] = {}
    for doc in docs:
        if doc["status"] != DocumentStatus.READY:
            continue
        role = role_of(doc)
        if wanted and (role is None or DocumentRole(role) not in wanted):
            continue
        out[str(doc["id"])] = doc
    return out
