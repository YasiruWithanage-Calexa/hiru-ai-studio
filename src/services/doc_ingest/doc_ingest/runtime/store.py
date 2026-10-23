"""Supabase access for doc_ingest: jobs, documents, chunks, storage, token usage.

Vendored per service (PLAN.md §4). PostgREST + Storage over HTTP with the service role.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx

from contracts.jobs import JobEventType, JobStatus

Row = dict[str, Any]
_INSERT_BATCH = 100


class Store:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None) -> None:
        base = url.rstrip("/")
        self._rest = f"{base}/rest/v1"
        self._storage = f"{base}/storage/v1"
        self._client = client or httpx.Client(timeout=60.0)
        self._headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}",
                         "Content-Type": "application/json"}

    # ── jobs ─────────────────────────────────────────────────────────────────────────────
    def get_job(self, job_id: UUID) -> Row | None:
        return self._first("jobs", {"id": f"eq.{job_id}", "select": "id,status"})

    def set_job(self, job_id: UUID, status: JobStatus, **fields: Any) -> None:
        self._patch("jobs", {"id": f"eq.{job_id}"}, {"status": status.value, **fields})
        self.event(job_id, JobEventType.STATUS, {"status": status.value})

    def event(self, job_id: UUID, type_: JobEventType, payload: Row, agent: str | None = None) -> None:
        self._post("job_events", [{"job_id": str(job_id), "type": type_.value,
                                   "agent": agent, "payload": payload}])

    # ── documents ────────────────────────────────────────────────────────────────────────
    def get_document(self, document_id: UUID) -> Row | None:
        return self._first("documents", {"id": f"eq.{document_id}", "select": "*"})

    def update_document(self, document_id: UUID, fields: Row) -> None:
        self._patch("documents", {"id": f"eq.{document_id}"}, fields)

    def download(self, bucket: str, path: str) -> bytes:
        r = self._client.get(f"{self._storage}/object/{bucket}/{path}", headers=self._headers)
        r.raise_for_status()
        return r.content

    def upload_text(self, bucket: str, path: str, text: str) -> None:
        """Write (or overwrite, on re-ingest) a UTF-8 text object."""
        headers = {**self._headers, "Content-Type": "text/plain; charset=utf-8", "x-upsert": "true"}
        r = self._client.post(f"{self._storage}/object/{bucket}/{path}", headers=headers,
                              content=text.encode("utf-8"))
        r.raise_for_status()

    # ── chunks ───────────────────────────────────────────────────────────────────────────
    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]:
        """content_hash → (embedding, model) for this document's current chunks, to reuse."""
        r = self._client.get(f"{self._rest}/chunks", headers=self._headers, params={
            "document_id": f"eq.{document_id}", "embedding": "not.is.null",
            "select": "content_hash,embedding,embedding_model"})
        r.raise_for_status()
        out: dict[str, tuple[list[float], str]] = {}
        for row in r.json():
            emb = row["embedding"]
            out[row["content_hash"]] = (json.loads(emb) if isinstance(emb, str) else emb,
                                        row["embedding_model"])
        return out

    def replace_chunks(self, document_id: UUID, rows: list[Row]) -> None:
        r = self._client.delete(f"{self._rest}/chunks", headers=self._headers,
                                params={"document_id": f"eq.{document_id}"})
        r.raise_for_status()
        for i in range(0, len(rows), _INSERT_BATCH):
            self._post("chunks", rows[i: i + _INSERT_BATCH])

    # ── usage ────────────────────────────────────────────────────────────────────────────
    def record_usage(self, row: Row) -> None:
        try:
            self._post("token_usage", [row])
        except httpx.HTTPError:
            pass  # accounting must never fail the work it accounts for

    # ── helpers ──────────────────────────────────────────────────────────────────────────
    def _first(self, table: str, params: dict[str, str]) -> Row | None:
        r = self._client.get(f"{self._rest}/{table}", headers=self._headers, params={**params, "limit": "1"})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None

    def _patch(self, table: str, params: dict[str, str], fields: Row) -> None:
        r = self._client.patch(f"{self._rest}/{table}", headers=self._headers, params=params, json=fields)
        r.raise_for_status()

    def _post(self, table: str, rows: list[Row]) -> None:
        r = self._client.post(f"{self._rest}/{table}", headers=self._headers, json=rows)
        r.raise_for_status()
