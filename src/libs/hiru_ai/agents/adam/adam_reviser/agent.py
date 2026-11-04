"""adam_reviser hooks (plan/2026-11-04b §5.2). New for Adam.

One revision, made from the critics' notes, as OPERATIONS on the plan: the cards the notes do not touch are not written
again, so a revision cannot lose what already worked. What an added moment may be is `adam_fidelity`'s decision, made by
the panel after the operations are applied; the better of the two plans is picked by `adam_score` in code. There is no
fallback (plan §5.5): with no answer the first plan stands.
"""
from __future__ import annotations

from contracts.adam.screening import screen_message
from hiru_ai.agents.adam.adam_reviser.schema import Input


def user_message(inp: Input) -> str:
    notes = "\n".join(f"{n}. {line}" for n, line in enumerate(inp.notes, start=1))
    return f"{screen_message(inp)}\n\n<notes>\n{notes}\n</notes>"

