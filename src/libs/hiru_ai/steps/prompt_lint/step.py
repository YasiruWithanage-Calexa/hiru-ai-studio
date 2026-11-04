"""prompt_lint: JSON in, JSON out.

    {"prompt": {"sections": [...], "prose": "...", "checks": [...]}, "shot": row, "lines": [rows]}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.prompt_lint.logic import lint


def run(payload: dict[str, Any]) -> dict[str, Any]:
    findings = lint(payload["prompt"], payload["shot"], payload.get("lines") or [])
    return {"ok": not findings, "findings": findings}
