"""canon_deduper hooks. Ported from `canon_extract/engine/model.py` (`dedupe`).
Merges are applied by code, never here."""
from __future__ import annotations

from hiru_ai.agents.canon_deduper.schema import Input


def user_message(inp: Input) -> str:
    listing = "\n".join(
        f"- [{c.kind}] {c.name}" + (f" ({c.code})" if c.code else "")
        + (f" aka {', '.join(c.aliases)}" if c.aliases else "")
        + (f": {c.summary}" if c.summary else "")
        for c in inp.candidates)
    return f"<canon>\n{listing}\n</canon>"
