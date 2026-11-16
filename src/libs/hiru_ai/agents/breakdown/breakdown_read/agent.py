"""breakdown_read hooks (plan/2026-11-15). The message is built in `contracts.breakdown.reading`; the document's words
reach the model only as numbered, labelled data. Code checks the answer (`reading.check`) and may send it back once.
No fallback (decision D4): a failed call stops the build."""

from __future__ import annotations

from hiru_ai.agents.breakdown.breakdown_read.schema import Input


def user_message(inp: Input) -> str:
    return inp.message
