"""Rule 2: ids, never names. Code assigns every id; a model refers to ids it was given."""
from __future__ import annotations

import re

KINDS = {"C": "person", "L": "place", "P": "thing", "D": "direction rule", "T": "thread"}
_ID = re.compile(r"^(?:[CLPDT]\d{2,}|E\d{2,}(?:-S\d{2,}(?:-B\d{2,}(?:-e\d+)?)?)?)$")


class Registry:
    """Numbers new entities (`C01`, `L01`…). The document's own codes are used when it gives them (`scene(1, 3)`)."""

    def __init__(self) -> None:
        self._n: dict[str, int] = {}

    def new(self, kind: str) -> str:
        if kind not in KINDS:
            raise ValueError(f"unknown id kind {kind!r}")
        self._n[kind] = self._n.get(kind, 0) + 1
        return f"{kind}{self._n[kind]:02d}"


def episode(n: int) -> str:
    return f"E{n:02d}"


def scene(ep: int, n: int) -> str:
    return f"{episode(ep)}-S{n:02d}"


def block(scene_id: str, n: int) -> str:
    return f"{scene_id}-B{n:02d}"


def event(block_id: str, n: int) -> str:
    return f"{block_id}-e{n}"


def valid(x: str) -> bool:
    return bool(_ID.match(x))
