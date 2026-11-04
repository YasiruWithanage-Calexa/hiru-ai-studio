"""architect hooks. Ported from `structure_build/engine/architect.py`. Text only: it never changes a scene, a line
or the structure; the system decides which of its words are used (a synopsis only when the outline has none)."""
from __future__ import annotations

from hiru_ai.agents.architect.schema import Input

ACTION_CHARS = 300


def user_message(inp: Input) -> str:
    rows = []
    for s in inp.scenes:
        action = " ".join(b.text for b in s.blocks if b.kind == "action")[:ACTION_CHARS]
        speakers = sorted({b.speaker for b in s.blocks if b.kind == "dialogue"})
        rows.append(f"Scene {s.number} | {s.heading} | speakers: {', '.join(speakers) or 'none'}\n  {action}")
    head = f"Episode {inp.number}" + (f" — {inp.title}" if inp.title else "")
    return f"{head}\n<scenes>\n" + "\n".join(rows) + "\n</scenes>"
