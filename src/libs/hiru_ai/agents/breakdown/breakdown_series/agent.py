"""breakdown_series hooks (plan/2026-11-12b). The message is built in `contracts.breakdown.series`, so this agent and
any other caller send the same bytes; the document's words reach the model only as numbered, labelled data. No
fallback: a failed call leaves the series block empty and every prompt with its general wording
(`contracts.breakdown.run.read_series`)."""

from __future__ import annotations

from hiru_ai.agents.breakdown.breakdown_series.schema import Input


def user_message(inp: Input) -> str:
    return inp.message
