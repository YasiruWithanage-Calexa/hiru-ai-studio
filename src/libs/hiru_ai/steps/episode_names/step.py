"""episode_names: `{"episode": {...}, "synopsis": "...", "scenes": [{"number": 1, "title": "..."}]}` → the episode
named."""
from __future__ import annotations

import copy
from typing import Any

from hiru_ai.steps.episode_names import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    episode = copy.deepcopy(payload["episode"])
    logic.apply(episode, str(payload.get("synopsis") or ""), list(payload.get("scenes") or []))
    return {"episode": episode}
