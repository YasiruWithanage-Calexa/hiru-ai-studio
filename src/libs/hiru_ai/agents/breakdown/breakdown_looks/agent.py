"""breakdown_looks hooks (plan/2026-11-12c). The message is built in `contracts.scene_looks`, so this agent, the canon
refine job and the tests send the same bytes. No fallback: a failed call leaves the looks as they are."""

from __future__ import annotations

from hiru_ai.agents.breakdown.breakdown_looks.schema import Input


def user_message(inp: Input) -> str:
    return inp.message
