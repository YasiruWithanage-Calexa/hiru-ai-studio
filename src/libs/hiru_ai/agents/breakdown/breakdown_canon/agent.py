"""breakdown_canon hooks (plan/2026-11-12c). The message is built in `contracts.canon_refine`, so this agent, the canon
refine job and the tests send the same bytes; the documents' words reach the model only as numbered, labelled data. No
fallback: a failed call leaves the canon as extracted (the job says why)."""

from __future__ import annotations

from hiru_ai.agents.breakdown.breakdown_canon.schema import Input


def user_message(inp: Input) -> str:
    return inp.message
