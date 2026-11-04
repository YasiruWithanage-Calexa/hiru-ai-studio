"""structure_draft's jobs and results."""
from __future__ import annotations

from typing import Any, TypedDict


class Job(TypedDict):
    member: str  # prose | architect | looks
    input: dict[str, Any]  # that agent's own Input
    key: str  # what the caller calls this job (an episode number, a character id)


class Result(TypedDict):
    member: str
    key: str
    ok: bool  # False: no such member on the panel, or the agent could not answer: the caller uses its rules
    output: Any  # the agent's Output, or None
