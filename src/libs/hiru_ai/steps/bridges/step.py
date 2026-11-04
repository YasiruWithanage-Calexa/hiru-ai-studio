"""bridges: the implied steps a scene's script needs, as removable blocks.

    {"scene": row, "lines": [rows], "cast": ["Kamala"], "version": 1}

Closed list (answers the phone, lowers it), rules only, never a model. `script` is the scene's script with those
blocks added; `planned` says which and where. A step a person removed is remembered on the block it belonged to
(`skip_bridges`) and not added back.
"""
from __future__ import annotations

from typing import Any

from contracts import bridges, sceneplan


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene, lines = payload["scene"], payload.get("lines") or []
    cast = list(payload.get("cast") or [])
    version = int(payload.get("version") or scene.get("script_version") or 1)
    items = sceneplan.items_for(bridges.strip_bridges(scene.get("script") or []), lines)
    return {"script": bridges.with_bridges(scene.get("script") or [], lines, version, cast),
            "planned": [{"before_block": n, "kind": kind, "who": who}
                        for n, kind, who in bridges.plan_bridges(items, cast)]}
