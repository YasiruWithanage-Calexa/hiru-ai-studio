"""Typed seams of the raphael_breakdown agent (plan/2026-11-10 §2).

The Input is the message stage 1 gets (production rules and people, synopsis, the scenes around, the place card, the
numbered script with its state ledger, the person's reading, `<voice_only>`, `<length>`), built by
`contracts.raphael.pack`, and, on the one retry, the faults the first answer had. The Output is the wire shape
`BreakdownW`: English only, lines by id.
"""

from __future__ import annotations

from pydantic import BaseModel

from contracts.raphael.wire import BreakdownW as Output  # noqa: F401  (the manifest names `schema:Output`)


class Input(BaseModel):
    opening: str  # <production>, <scene>, <script>, <voice_only>, <length>
    faults: list[str] = []  # the retry: what was wrong with the first breakdown
