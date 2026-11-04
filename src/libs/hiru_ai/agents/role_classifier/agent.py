"""role_classifier hooks. Ported from `doc_ingest/engine/roles.py` (`sample`, the user message, the answer's clamping).

The rules run first and are free; the system asks this agent only when they are unsure, and keeps the rules' guess when
it fails, so there is no fallback here.
"""
from __future__ import annotations

from hiru_ai.agents.role_classifier.schema import Input, Output
from hiru_ai.core.middleware.untrusted_text import defuse


def sample(text: str, budget: int = 6000) -> str:
    """Head and middle of the text: openings are often title pages, middles show the body."""
    if len(text) <= budget:
        return text
    half = budget // 2
    mid = len(text) // 2
    return text[:half] + "\n…\n" + text[mid: mid + half]


def user_message(inp: Input) -> str:
    return f"File name: {inp.filename}\n\n<document>\n{defuse(sample(inp.text))}\n</document>"


def finish(inp: Input, out: Output) -> Output:
    """A confidence the engine could show: 0 to 0.95 (a model is never certain), two places; the reason is short."""
    confidence = max(0.0, min(0.95, float(out.confidence)))
    return Output(role=out.role, confidence=round(confidence, 2), reason=out.reason[:300])
