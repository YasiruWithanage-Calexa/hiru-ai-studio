"""sable_overview (plan/2026-11-08 Phase 3): the production at a glance, paged, inside its production only."""
from __future__ import annotations

from uuid import uuid4

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import run_example


def test_every_episode_is_counted_and_each_scene_says_who_planned_it():
    out, _ = run_example("sable_overview")
    assert out.production == "Harbour Lights" and out.open_questions == 1
    counts = [(e["episode"], e["scenes"], e["planned"], e["approved"]) for e in out.episodes]
    assert counts == [(1, 3, 1, 1), (2, 1, 0, 0)]
    by = {s["scene"]: s for s in out.scenes}
    assert by["E1S1"]["planner"] == "jonathan" and by["E1S1"]["waiting_for"] == "approval"
    assert by["E1S2"]["planner"] == "classic" and by["E1S2"]["shots"] == 2 and "waiting_for" not in by["E1S2"]
    assert by["E1S3"]["waiting_for"] == "plan"


def test_waiting_keeps_the_scenes_that_are_not_approved_and_the_total_says_so():
    out, _ = run_example("sable_overview", {"waiting": True})
    assert [s["scene"] for s in out.scenes] == ["E1S1", "E1S3", "E2S1"] and out.total == 3


def test_it_pages():
    first, _ = run_example("sable_overview", {"page_size": 3})
    second, _ = run_example("sable_overview", {"page_size": 3, "page": 2})
    assert len(first.scenes) == 3 and first.next_page == 2 and first.total == 4
    assert [s["scene"] for s in second.scenes] == ["E2S1"] and second.next_page is None


def test_an_unknown_episode_lists_the_ones_there_are():
    with pytest.raises(ToolRefused) as refused:
        run_example("sable_overview", {"episode": 9})
    assert "Episodes: 1, 2" in refused.value.how_to_fix


def test_another_production_sees_nothing_of_this_one():
    out, _ = run_example("sable_overview", production_id=uuid4())
    assert out.scenes == [] and out.production == "" and all(e["scenes"] == 0 for e in out.episodes)
