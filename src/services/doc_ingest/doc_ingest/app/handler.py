"""HTTP entry: payload → pipeline. Same contract as the echo template:
400 for a malformed payload; a crash marks the job and document failed and answers 200, so
Cloud Tasks does not retry something a retry will not fix; 500 only for transient storage or
network errors, which a retry can fix."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from contracts.documents import DocumentStatus
from contracts.jobs import DispatchPayload, JobStatus
from doc_ingest.engine import pipeline
from doc_ingest.runtime.config import get_config
from doc_ingest.runtime.llm import LLM
from doc_ingest.runtime.store import Store

_logger = logging.getLogger(__name__)


def build(payload: DispatchPayload) -> tuple[Store, LLM]:
    config = get_config()
    store = Store(config.supabase_url, config.service_role_key)

    def on_usage(row: dict[str, Any]) -> None:
        store.record_usage({**row, "job_id": str(payload.job_id),
                            "production_id": str(payload.production_id) if payload.production_id else None,
                            "actor_user_id": str(payload.actor_user_id)})

    return store, LLM(config, on_usage)


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        UUID(str(payload.state["document_id"]))
    except (ValidationError, KeyError, ValueError):
        return {"error": "bad payload"}, 400

    store, llm = build(payload)
    try:
        return pipeline.run(payload, store, llm), 200
    except httpx.TransportError:
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("doc_ingest failed job=%s", payload.job_id)
        document_id = UUID(str(payload.state["document_id"]))
        try:
            store.update_document(document_id, {"status": DocumentStatus.FAILED.value,
                                                "error": "Reading this document failed. Try re-ingesting it."})
            store.set_job(payload.job_id, JobStatus.FAILED, error="Document ingestion failed.")
        except Exception:
            _logger.exception("could not record the failure job=%s", payload.job_id)
        return {"error": "failed"}, 200
