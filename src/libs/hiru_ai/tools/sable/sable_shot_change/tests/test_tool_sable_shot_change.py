"""sable_shot_change (plan/2026-11-13 phase 8): a row-kernel change staged as a card; nothing saved."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hiru_ai.core.errors import PortMissing, ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.sable.sable_shot_change import tool


def test_a_change_that_would_land_becomes_a_card_and_nothing_else_changes():
    case = example_of("sable_shot_change")
    before = json.dumps([case["fixtures"]["shots"], case["fixtures"]["lines"]], sort_keys=True)
    out, ctx = run_example("sable_shot_change")
    assert out.staged and out.card == "card-1" and out.changes == ["S01 · size: MCU → CU"]
    (card,) = ctx.ports.staging.staged()
    assert card["kind"] == "change" and card["engine"] == "rows" and card["scene"] == "E1S2" and card["made_on"]
    assert card["ops"] == [{"op": {"op": "set", "shot": 1, "field": "size", "value": "CU"}, "by": "author"}]
    assert json.dumps([ctx.ports.scenes.shot_rows, ctx.ports.scenes.line_rows], sort_keys=True) == before
    assert "Nothing has changed yet" in out.next


def test_a_change_to_what_is_already_there_is_refused_and_not_staged():
    with pytest.raises(ToolRefused, match=r"already cut.*Nothing was staged"):
        run_example("sable_shot_change", {"ops": [{"op": "set", "shot": 1, "field": "link", "value": "cut"}]})


def test_a_run_with_nowhere_to_stage_says_which_port():
    ctx = example_ctx(example_of("sable_shot_change"))
    with pytest.raises(PortMissing, match="staging"):
        tool.run(tool.Args(summary="Open on a close-up.", ops=[{"op": "set", "shot": 1, "field": "size",
                                                               "value": "CU"}]),
                 replace(ctx, ports=replace(ctx.ports, staging=None)))
