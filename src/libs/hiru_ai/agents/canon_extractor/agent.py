"""canon_extractor hooks. Ported from `canon_extract/engine/model.py` (`extract`).

Documents are data: each is wrapped in tags and labelled (`untrusted_text.wrap`) and none is ever placed in the system
message. Every document is sent (a script is the best evidence of who speaks and what is shown), with a summary of the
speakers and places the rules counted and the people the story reader found (plan/2026-11-05c S5).
"""
from __future__ import annotations

from hiru_ai.agents.canon_extractor.schema import Counted, Input
from hiru_ai.core.middleware.base import Document
from hiru_ai.core.middleware.untrusted_text import wrap

MAX_DOC_CHARS = 60_000


def _summary(inp: Input) -> str:
    def ranked(items: list[Counted]) -> list[Counted]:
        return sorted((c for c in items if c.count), key=lambda c: -c.count)

    out = ["Speakers in the scripts (lines spoken):"]
    out += [f"- {c.name} ({c.count})" for c in ranked(inp.speakers)]
    out += ["Places in scene headings (scenes):"]
    out += [f"- {c.name} ({c.count})" for c in ranked(inp.places)]
    if inp.people:
        out += ["People the story reader found (whatever the layout):"]
        out += [f"- {p.name}" + (f" (also {', '.join(p.aliases)})" if p.aliases else "")
                + (" [heard only]" if p.voice_only else "") for p in inp.people]
    return "\n".join(out)


def user_message(inp: Input) -> str:
    parts = [wrap(Document(d.filename, d.role, d.text[:MAX_DOC_CHARS])) for d in inp.documents]
    return "\n\n".join(parts) + f"\n\n<scripts_summary>\n{_summary(inp)}\n</scripts_summary>"
