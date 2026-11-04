from __future__ import annotations

import json

import pytest

from hiru_ai.core.errors import PortMissing, ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.change_propose import tool


def test_a_change_that_would_land_becomes_a_card_and_nothing_else_changes():
    case = example_of("change_propose")
    before = json.dumps([case["fixtures"]["shots"], case["fixtures"]["lines"]], sort_keys=True)
    out, ctx = run_example("change_propose")
    assert out.staged and out.card == "card-1" and out.changes == ["S01 framing → CU"]
    (card,) = ctx.ports.staging.staged()
    assert card["kind"] == "change" and card["scene"] == "E1S2" and card["summary"].startswith("Open on")
    assert card["ops"][0]["op"] == "set" and card["ops"][0]["value"] == "CU" and "by" not in card["ops"][0]
    assert json.dumps([ctx.ports.scenes.shot_rows, ctx.ports.scenes.line_rows], sort_keys=True) == before
    assert "Nothing has changed yet" in out.next


def test_if_any_operation_would_be_refused_nothing_is_staged_and_the_reasons_come_back():
    with pytest.raises(ToolRefused) as refused:
        run_example("change_propose", {"ops": [
            {"op": "set", "shot": 1, "field": "framing", "value": "CU"},
            {"op": "set", "shot": 9, "field": "framing", "value": "CU"}]})
    assert "1 of 2" in str(refused.value) and "Nothing was staged" in str(refused.value)
    assert refused.value.how_to_fix and refused.value.example


def test_the_script_is_never_staged_by_a_model():
    ctx = example_ctx(example_of("change_propose"))
    with pytest.raises(ToolRefused, match="person"):
        tool.run(tool.Args(summary="Rewrite the first line.",
                           ops=[{"op": "block.set", "block": 0, "kind": "action", "value": "Kasun frowns."}]), ctx)
    assert ctx.ports.staging.staged() == []


def test_a_run_with_nowhere_to_stage_says_which_port():
    from dataclasses import replace

    ctx = example_ctx(example_of("change_propose"))
    with pytest.raises(PortMissing, match="staging"):
        tool.run(tool.Args(summary="Open on a close-up.",
                          ops=[{"op": "set", "shot": 1, "field": "framing", "value": "CU"}]),
                 replace(ctx, ports=replace(ctx.ports, staging=None)))
