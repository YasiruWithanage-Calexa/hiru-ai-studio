"""frame_inspector hooks. Ported from `frame_render/engine/inspect.py` (`expectation`) and the vision call in the
function's handler.

A frame is never deleted or repainted by this: a person decides. Its answer becomes advisory chips (the system's
`vision_checks`). No key, or a failed call, gives no vision checks and the frame is still done, so there is no fallback.
"""
from __future__ import annotations

from hiru_ai.agents.frame_inspector.schema import Input


def user_message(inp: Input) -> str:
    seen = "\n".join(f"- {p}" for p in inp.seen) or "- nobody identified (a place or an object)"
    unseen = "\n".join(f"- {p}" for p in inp.unseen)
    return ("<expected>\nMAIN PEOPLE WHO SHOULD BE VISIBLE:\n" + seen
            + (f"\nPEOPLE WHO MUST NOT BE VISIBLE:\n{unseen}" if unseen else "")
            + f"\nTHE FIRST FRAME SHOULD SHOW: {inp.frame or 'as above'}\n</expected>")


def images(inp: Input) -> list[tuple[str, str]]:
    return [(inp.mime, inp.image_b64)]
