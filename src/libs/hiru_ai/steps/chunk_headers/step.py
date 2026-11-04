"""chunk_headers: `{"filename", "role", "chunks": [{ord, heading, content, page_start, page_end}], "answers": [...]}`

`answers` has one entry per batch of 20 chunks, in order: the agent's `headers` list, or null when that call failed.
Returns `{"headers": {"<ord>": "..."}, "batches": n}` (ords are strings in JSON).
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.chunk_headers.logic import add_model_lines, base_header, batches


def run(payload: dict[str, Any]) -> dict[str, Any]:
    chunks, role, filename = list(payload["chunks"]), str(payload["role"]), str(payload["filename"])
    out = {int(c["ord"]): base_header(filename, role, c) for c in chunks}
    answers = list(payload.get("answers") or [])
    groups = batches(chunks)
    for i, batch in enumerate(groups):
        add_model_lines(out, batch, answers[i] if i < len(answers) else None, i)
    return {"headers": {str(k): v for k, v in out.items()}, "batches": len(groups)}
