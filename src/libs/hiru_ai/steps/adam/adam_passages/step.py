"""adam_passages: deterministic, no model, no database.

    {"query": str, "kind": "grammar" | "devices", "k"?: int}
        → {"text": the passages as the agents read them, "sources": [file, ...], "kind": ...}

An Adam agent is one call and cannot search, so the system hands it passages (plan/2026-11-04b §5.2). They come from the
knowledge base's own source files, ranked here, so a scene is planned the same before and after the base is ingested
(`hiru-ai ingest adam_film_grammar` writes to the hosted dev database and waits for a person); `search_kb` over the
ingested chunks can replace this ranker later without changing what an agent receives.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.adam.adam_passages import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "devices")
    if kind not in logic.KINDS:
        return {"text": "", "sources": [], "kind": kind, "error": f"kind is one of {', '.join(logic.KINDS)}"}
    return logic.passages(str(payload.get("query") or ""), kind, int(payload.get("k") or logic.DEFAULT_K[kind]))
