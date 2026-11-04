"""What goes into adam_screening and what comes out. The critics and the reviser know nothing of this: the panel maps
the brief into each agent's own `Input`."""
from __future__ import annotations

from typing import Any, TypedDict


class Brief(TypedDict, total=False):
    scene: dict[str, Any]  # contracts.adam.plan.SceneScript, as data
