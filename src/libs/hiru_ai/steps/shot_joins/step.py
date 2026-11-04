"""shot_joins: JSON in, JSON out.

    {"scene": row, "lines": [rows], "shots": [rows], "number": 2, "cast": ["Kamala"], "canon": [rows]}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.shot_joins.logic import joins


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return joins(payload["scene"], payload.get("lines") or [], payload["shots"], int(payload["number"]),
                 list(payload.get("cast") or []), payload.get("canon"))
