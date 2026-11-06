"""prose_writer hooks. Ported from `structure_build/engine/prose.py` (`by_model`).

Spoken lines must come back word for word. Whether the cut can be trusted (`trusted`) is checked in code by the system:
an answer that drops or alters a line is thrown away for that episode and the rules cut it (CLAUDE.md "never
auto-trim").
"""
from __future__ import annotations

from hiru_ai.agents.prose_writer.schema import Input

CANON_NAMES = 80  # the prompt lists this many canon entries at most


def _canon_listing(inp: Input) -> str:
    rows = [f"{c.kind}: {c.name}" for c in inp.canon if c.kind in ("character", "location")]
    return "\n".join(rows[:CANON_NAMES]) or "(none)"


def user_message(inp: Input) -> str:
    target = f"{inp.duration_s} s" if inp.duration_s else "not stated"
    head = f"Episode {inp.number} — {inp.title}" if inp.number is not None else f"Scene — {inp.title}".rstrip(" —")
    return (f"{head}\nTarget length: {target}\n"
            f"<canon>\n{_canon_listing(inp)}\n</canon>\n<episode>\n{inp.body}\n</episode>")
