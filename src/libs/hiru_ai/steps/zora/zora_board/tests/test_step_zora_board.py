"""Tests that live with the zora_board step (ADR 0006). The gate (the planner's checks by id) is tested in
`tests/zora`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.zora.zora_board import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_keeps_one_op_drops_a_resend_and_refuses_the_rest_with_reasons():
    out = step.run(EXAMPLE)
    assert out["kept"] == [{"op": "set", "shot": 2, "field": "lens", "value": "85mm: closer as she decides"}]
    assert out["noops"] == 1
    assert out["refused"] == ["the director's lens change on S03 was refused: you set S03's lens yourself",
                              "the director's size change on S01 was refused: it was outside what this turn asked "
                              "for"]
