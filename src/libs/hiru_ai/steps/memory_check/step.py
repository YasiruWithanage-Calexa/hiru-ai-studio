"""memory_check: the memory reader's answer against the document, JSON in, JSON out.

    {"entries": [...reader entries...], "text": "...the document..."}
        → {"entries": [...], "dropped": n, "warnings": [...]}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.memory_check import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return logic.check(payload["entries"], payload["text"])
