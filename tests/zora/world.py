"""Zora's offline world: three scenes the cinematic lab planned, with the lab's mended plans (tests/eval/zora/fixtures,
written by lab/zora/build_fixtures.py from saved runs: no model call), and the small scene of the steps' examples."""
from __future__ import annotations

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

from contracts.zora.doc import Person, ZoraDoc

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "eval" / "zora" / "fixtures"
SCENES = ("episode1", "arrival", "father_refuses")
EXAMPLE = ROOT / "src" / "libs" / "hiru_ai" / "steps" / "zora" / "zora_kernel" / "examples" / "basic.json"


@cache
def _raw(name: str) -> dict[str, Any]:
    if name == "small":
        return dict(json.loads(EXAMPLE.read_text(encoding="utf-8"))["doc"])
    return dict(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def doc(name: str = "father_refuses", *, locked: list[str] | None = None) -> ZoraDoc:
    raw = copy.deepcopy(_raw(name))
    return ZoraDoc(plan=raw["plan"], scene=raw["scene"], person=Person(locked=list(locked or [])))


def words(d: ZoraDoc) -> list[str]:
    """Every line's words, in script order."""
    return [str(b["text"]) for b in d.blocks if b.get("line_id")]
