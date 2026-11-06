"""Tests that live with the zora_kernel step (ADR 0006): deleting the folder deletes them. The kernel's properties on
the lab's plans are in `tests/zora`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.zora.zora_kernel import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_lands_and_what_the_person_set_is_locked():
    out = step.run(EXAMPLE)
    assert [a["op"] for a in out["applied"]] == ["set"] and out["rejected"] == []
    assert out["plan"]["shots"][2]["lens"] == "135mm: he is far from her now"
    assert out["person"]["locked"] == ["S03.lens"]


def test_an_op_the_author_may_not_use_is_refused_and_nothing_changes():
    out = step.run({**EXAMPLE, "by": "author", "ops": [{"op": "end.set", "field": "time", "value": "night"}]})
    assert out["applied"] == [] and "may not use end.set" in out["rejected"][0]["reason"]
    assert out["plan"] == EXAMPLE["doc"]["plan"]
