"""jonathan_links: `{"scenes": [row], "order"?, "overrides"?}` → `{"links", "chains"}` (plan/2026-11-05e §4.3).

Each scene row needs `id`, `episode_id`, `number`, `location_id`, `time_of_day` (and `episode_number` when known).
`links` maps a scene id to "continuous", "carry" or "" (it does not carry on); `chains` lists scene ids that run one
after
another; separate chains run at once. `overrides`: scene id → "continuous" | "carry" | "none" (a person's choice).
"""
from __future__ import annotations

from typing import Any

from contracts.jonathan import links as rules


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scenes = [dict(s) for s in payload.get("scenes") or []]
    order = str(payload.get("order") or "linked")
    order = order if order in rules.ORDERS else "linked"
    overrides = {str(k): str(v) for k, v in (payload.get("overrides") or {}).items()}
    ranked = sorted(scenes, key=lambda s: (int(s.get("episode_number") or 0), str(s.get("episode_id")),
                                           int(s.get("number") or 0)))
    made: dict[str, str] = {}
    for n, sc in enumerate(ranked):
        prev = ranked[n - 1] if n else None
        made[str(sc["id"])] = rules.link_of(prev, sc, order, overrides.get(str(sc["id"])))
    return {"links": made, "chains": rules.chains(scenes, made)}
