"""What a planner reads from a scene's stored packet without staging it (plan/2026-11-12c Track B).

`breakdown_build.packet_for` stages a scene before planning; this only reads what is stored. A scene with no packet, a
packet made before the map existed, or no breakdown store gives None: the planner falls back to matching names.
"""

from __future__ import annotations

import logging
from typing import Any

from hiru_ai.core.context import RunContext

_log = logging.getLogger(__name__)


def canon_things(ctx: RunContext, scene: dict[str, Any]) -> list[str] | None:
    """The canon ids of the things the scene's brief gives a role a camera sees, or None to match names."""
    store = ctx.ports.breakdown
    if store is None:
        return None
    try:
        row = store.packet(str(scene["id"]))
    except Exception:  # schema v21 not applied, or a read that failed: names as before
        _log.warning("the scene packet could not be read", exc_info=True)
        return None
    if not row or int(row.get("script_version") or 0) != int(scene.get("script_version") or 1):
        return None
    canon = (row.get("packet") or {}).get("canon")
    return list(canon["things"]) if isinstance(canon, dict) and isinstance(canon.get("things"), list) else None
