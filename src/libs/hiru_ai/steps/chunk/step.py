"""chunk: `{"kind": "text", "lines": [{"text": "...", "page": 1}], "script_like": true}` → retrieval chunks.

The input is `extract_text`'s output: a system maps one onto the other.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from hiru_ai.steps.chunk.logic import Extracted, Line, chunk


def run(payload: dict[str, Any]) -> dict[str, Any]:
    extracted = Extracted(str(payload.get("kind") or "text"),
                          [Line(str(ln["text"]), ln.get("page")) for ln in payload.get("lines") or []])
    return {"chunks": [{**asdict(c), "content_hash": c.content_hash}
                       for c in chunk(extracted, script_like=bool(payload.get("script_like")))]}
