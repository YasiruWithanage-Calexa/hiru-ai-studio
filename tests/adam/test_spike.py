"""plan/2026-11-05 Phase 1: the spike script, offline.

It is a person's to start (it spends model calls), so these tests run it against a scripted model: that it refuses
without `--yes`, writes what it says it writes, measures variant A without the facts and B with them, and counts the
fixer's accepted
fixes per kind and rung from the plan's own report."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tests.adam import stages
from tests.adam.test_take_system import (
    HOLE_CARD,
    NAME,
    hole_world,
    insert_back,
    per_tier,
    route,
    routes_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import adam_take_spike as spike

from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel


@pytest.fixture(autouse=True)
def into_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spike, "SPIKE", tmp_path)


def test_it_refuses_to_start_without_yes_and_spends_nothing(capsys: pytest.CaptureFixture[str]):
    assert spike.main([]) == 2
    assert "--yes" in capsys.readouterr().out


def test_the_default_scenes_are_three_and_never_the_one_the_prompt_shows():
    from tests.adam import gold

    chosen = spike.pick(gold.names())
    assert len(chosen) == 3 and chosen[0] == "phone_call" and stages.EXAMPLE_SCENE not in chosen


def test_variant_a_is_given_no_facts_and_b_is_and_both_leave_their_plan_and_their_calls(tmp_path: Path):
    model = RoutedChatModel(routes=routes_for(), choose=route, model_name="gpt-5")
    with llm.use_models(per_tier(model)):
        a = spike.run_variant("A", NAME)
    assert "<facts>" not in str(model.calls[0][1].content) and a["variant"] == "A" and a["calls"] == 3
    model = RoutedChatModel(routes=routes_for(), choose=route, model_name="gpt-5")
    with llm.use_models(per_tier(model)):
        b = spike.run_variant("B", NAME)
    assert "<facts>" in str(model.calls[0][1].content) and b["variant"] == "B"
    assert (tmp_path / "A" / f"{NAME}.json").exists() and (tmp_path / "B" / f"{NAME}.usage.json").exists()
    assert a["percent"] == 100.0 and a["breaks"] == 0 and a["tries"] == [] and a["cost"] >= 0


def test_the_small_models_accepted_fixes_are_counted_per_kind_and_rung_from_the_plans_own_report():
    _, given = hole_world()
    model = RoutedChatModel(routes=routes_for(given["take"], sound=given["sound"], fixers=[
        {"operations": [], "dispositions": [{"note_id": "p1", "done": [], "declined": "no"}]},
        insert_back(HOLE_CARD - 1)]), choose=route, model_name="gpt-5")
    with llm.use_models(per_tier(model)):
        row = spike.run_variant("B", NAME)
    assert row["tries"] == [{"kind": "local", "rung": 1, "name": "small", "tier": "medium", "stood": False,
                                       "why": row["tries"][0]["why"]},
                                      {"kind": "local", "rung": 2, "name": "big", "tier": "fixer", "stood": True,
                                       "why": []}]
    assert spike.accept_rates([row]) == {"local": {"small": (0, 1), "big": (1, 1)}}
    assert row["fixed"] == [("local", 2)] and row["reported"] == []


def test_the_summary_is_a_table_for_implemented_md_and_leaves_a_cell_empty_rather_than_inventing_it():
    rows = [{"variant": "A", "scene": "x", "percent": 96.0, "coverage": 1.0, "breaks": 0, "overruns": 0,
             "thought": 15000, "cost": 0.3, "tries": [{"kind": "local", "name": "small", "stood": True}]},
            {"variant": "A", "scene": "y", "percent": 90.0, "coverage": 0.8, "breaks": 0, "overruns": 1,
             "thought": 19000, "cost": 0.4, "tries": [{"kind": "local", "name": "small", "stood": False},
                                    {"kind": "local", "name": "big", "stood": True}]},
            {"variant": "B", "scene": "x", "error": "Failed: nope"}]
    text = spike.summary(rows, [])
    assert "| A | 2 | 93 | 0.9 | 0 | 1 | 17000 | 0.35 |" in text
    assert "| B | 0 |" in text and "| local | small | 1 | 2 |" in text and "| local | big | 1 | 1 |" in text


def test_a_scene_the_take_cannot_plan_is_a_result_not_a_crash(capsys: pytest.CaptureFixture[str],
                                                              monkeypatch: pytest.MonkeyPatch):
    def boom(variant: str, name: str) -> dict:
        raise RuntimeError("the take could not be made")

    monkeypatch.setattr(spike, "run_variant", boom)
    assert spike.main(["--yes", "--scene", NAME, "--variant", "A"]) == 0
    assert "the take could not be made" in capsys.readouterr().out
