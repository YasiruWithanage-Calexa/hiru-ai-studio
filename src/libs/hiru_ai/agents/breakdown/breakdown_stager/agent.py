"""breakdown_stager hooks (plan/2026-11-11 §4). The message is built in `contracts.breakdown.run`, so this agent and any
other
caller send the same bytes; the document's words reach the model only as numbered, labelled data. No fallback: a failed
call is absent-safe in the run (a document left out, a scene without a brief that waits)."""

from __future__ import annotations

from hiru_ai.agents.breakdown.breakdown_stager.schema import Input


def user_message(inp: Input) -> str:
    return inp.message
