"""Intent → technique palette for the job, from `craft_techniques` (PLAN.md §7).

Forked from PromptMotion `nova_producer/engine/producer.py` (`ProducerEngine.techniques`) and
`engine/retrieval.py` (`retrieve_techniques`), 1d748dc. Retrieved ONCE per job, not per shot:
it rides in the frozen production block, and a block that varied per scene would cost the
prompt-cache discount. "Once" is not "one query": each distinct intent is queried on its own
and the results are unioned, because one blended query returns the centroid of the piece.

Absent-safe: no key, no rows or any error → "" and the design runs without it.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_logger = logging.getLogger(__name__)
MAX_QUERIES = 4
MATCHES = 4

Lookup = Callable[[str, list[float] | None], list[dict[str, Any]]]
Embed = Callable[[list[str]], list[list[float]]]

CAVEATS = ("Name rigs that describe how footage MOVES (handheld, steadicam, slider, dolly, locked-off sticks); "
           "complex moves (whip pan, orbit, dolly zoom) render less reliably than simple ones, so use them only "
           "when a moment truly needs them.")


def palette(intents: list[str], context: str, lookup: Lookup, embed: Embed | None) -> str:
    seen: set[str] = set()
    queries: list[str] = []
    for intent in intents:
        key = intent.strip().lower()
        if key and key not in seen:
            seen.add(key)
            queries.append(f"{intent.strip()}. {context}".strip())
    queries = queries[:MAX_QUERIES]
    if not queries:
        return ""
    try:
        vectors: list[list[float] | None] = list(embed(queries)) if embed else [None] * len(queries)
    except Exception:
        _logger.warning("technique embedding failed; keyword lookup only", exc_info=True)
        vectors = [None] * len(queries)
    lines: list[str] = []
    for query, vector in zip(queries, vectors, strict=True):
        try:
            rows = lookup(query, vector)
        except Exception:
            _logger.warning("technique lookup failed", exc_info=True)
            continue
        for row in rows[:MATCHES]:
            name = str(row.get("name") or "")
            abbrev = row.get("abbreviation") or ""
            head = f"{name} ({abbrev})" if abbrev else name
            use = str(row.get("use_case") or "").rstrip(".").lower()
            line = f"- to {use} → {head}: {row.get('definition', '')}"
            if line not in lines and name:
                lines.append(line)
    if not lines:
        return ""
    return "\n".join(["INTENT → TECHNIQUE MATCHES (professional shot vocabulary):", *lines, CAVEATS])
