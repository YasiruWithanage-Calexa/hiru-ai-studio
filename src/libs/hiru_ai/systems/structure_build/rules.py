"""The question rows the build writes, and the ids that make them stable. Ported from
`structure_build/engine/pipeline.py`."""
from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from contracts.build import QuestionStatus

# Roles whose text can hold episodes. Only script and outline are read as such unless the text turns out to be prose
# episodes (a bible that carries its own scripts).
PROSE_ROLES = ("script", "outline", "bible", "other")
QUESTION_NS = uuid.UUID("6f1c2b0e-3d7a-4c55-9a51-8f6f0e2a7b10")


def question_id(job_id: UUID, key: str) -> str:
    return str(uuid.uuid5(QUESTION_NS, f"{job_id}:{key}"))


def question_rows(job_id: UUID, production_id: UUID, questions: list[dict[str, Any]], *, status: QuestionStatus,
                  answers: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [{"id": question_id(job_id, q["key"]), "production_id": str(production_id), "job_id": str(job_id),
             "key": q["key"][:300], "agent": q["agent"], "scope": q["scope"][:200], "title": q["title"][:200],
             "body": q["body"][:2000], "options": q["options"], "allow_text": q["allow_text"],
             "status": status.value, "answer": (answers or {}).get(q["key"])} for q in questions]


def answered(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The answers a person gave a job's questions, by question key."""
    return {r["key"]: r["answer"] for r in rows if r["status"] == QuestionStatus.ANSWERED and r.get("answer")}
