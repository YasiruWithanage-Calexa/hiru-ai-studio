"""canon_extractor hooks. Ported from `canon_extract/engine/model.py` (`extract`).

Documents are data: each is wrapped in tags and labelled (`untrusted_text.wrap`) and none is ever placed in the system
message. Only the roles that describe the cast are sent; scripts reach the model as the speaker and place summary.
"""
from __future__ import annotations

from hiru_ai.agents.canon_extractor.schema import Counted, Input
from hiru_ai.core.middleware.base import Document
from hiru_ai.core.middleware.untrusted_text import wrap

MAX_DOC_CHARS = 60_000
ROLES = ("bible", "canon_index", "notes", "outline")


def _summary(inp: Input) -> str:
    def ranked(items: list[Counted]) -> list[Counted]:
        return sorted((c for c in items if c.count), key=lambda c: -c.count)

    out = ["Speakers in the scripts (lines spoken):"]
    out += [f"- {c.name} ({c.count})" for c in ranked(inp.speakers)]
    out += ["Places in scene headings (scenes):"]
    out += [f"- {c.name} ({c.count})" for c in ranked(inp.places)]
    return "\n".join(out)


def user_message(inp: Input) -> str:
    parts = [wrap(Document(d.filename, d.role, d.text[:MAX_DOC_CHARS])) for d in inp.documents if d.role in ROLES]
    return "\n\n".join(parts) + f"\n\n<scripts_summary>\n{_summary(inp)}\n</scripts_summary>"
