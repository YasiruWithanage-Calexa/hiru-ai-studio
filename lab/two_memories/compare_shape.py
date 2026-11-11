"""Compares the STRUCTURE of two runs' Raphael outputs (`12_raphael/*.json`): every key path and the type of its value,
lists collapsed to `[]` so a different number of clips is not a difference. Values are not compared.

    python lab/two_memories/compare_shape.py <old run>/12_raphael <new run>/12_raphael
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def shape(x: Any, path: str = "", out: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    out = {} if out is None else out
    kind = "null" if x is None else type(x).__name__
    out.setdefault(path or "$", set()).add(kind)
    if isinstance(x, dict):
        for k, v in x.items():
            shape(v, f"{path}.{k}", out)
    elif isinstance(x, list):
        for v in x:
            shape(v, f"{path}[]", out)
    return out


def merged(folder: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(folder.glob("*.json")):
        for k, v in shape(json.loads(f.read_text(encoding="utf-8"))).items():
            out.setdefault(k, set()).update(v)
    return out


def main() -> None:
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    print("files old:", sorted(f.name for f in old.glob("*.json")), "new:", sorted(f.name for f in new.glob("*.json")))
    a, b = merged(old), merged(new)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    retyped = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    print(f"key paths: old {len(a)}, new {len(b)}")
    print("ADDED:", added or "none")
    print("REMOVED:", removed or "none")
    for k in retyped:
        print(f"TYPE {k}: old {sorted(a[k])} new {sorted(b[k])}")
    if not retyped:
        print("TYPES: same everywhere both have the key")


if __name__ == "__main__":
    main()
