"""extract_text: a file in, numbered lines out.

    {"filename": "script.pdf", "mime_type": "application/pdf", "data_b64": "..."}   or   {..., "path": "local file"}

A file the engine refuses (a scan, an oversize or unreadable file) is a result, `{"rejected": "why"}`, written for
the uploader; it is never an exception.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from hiru_ai.steps.extract_text.logic import Rejected, extract


def run(payload: dict[str, Any]) -> dict[str, Any]:
    data = base64.b64decode(payload["data_b64"]) if payload.get("data_b64") else Path(payload["path"]).read_bytes()
    try:
        out = extract(data, str(payload["filename"]), str(payload.get("mime_type") or ""))
    except Rejected as exc:
        return {"rejected": str(exc)}
    return {"kind": out.kind, "lines": [{"text": ln.text, "page": ln.page} for ln in out.lines],
            "page_count": out.page_count, "warnings": out.warnings, "char_count": out.char_count,
            "has_sinhala": out.has_sinhala}
