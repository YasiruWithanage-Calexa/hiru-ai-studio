"""sable_scene_find (plan/2026-11-08 Phase 3): scenes by who, where, when and words; inside its production only."""
from __future__ import annotations

from uuid import uuid4

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import run_example


def test_a_person_is_found_where_they_speak():
    out, _ = run_example("sable_scene_find")
    assert [(s["scene"], s["character"]) for s in out.scenes] == [("E1S2", "speaks")]
    assert out.matched == {"character": "C01 Kasun"}


def test_a_person_named_in_the_action_is_found_too():
    out, _ = run_example("sable_scene_find", {"character": "Anudi"})
    found = {s["scene"]: s["character"] for s in out.scenes}
    assert found["E1S1"] == "named in the action" and found["E1S2"] == "named in the action"


def test_every_filter_must_hold():
    out, _ = run_example("sable_scene_find", {"character": None, "place": "house", "time_of_day": "night"})
    assert [s["scene"] for s in out.scenes] == ["E1S3"]
    none, _ = run_example("sable_scene_find", {"character": None, "place": "house", "time_of_day": "day"})
    assert none.scenes == [] and none.total == 0


def test_a_canon_place_matches_by_its_location_and_its_code():
    out, _ = run_example("sable_scene_find", {"character": None, "place": "L01"})
    assert [s["scene"] for s in out.scenes] == ["E1S2"] and out.matched["place"].startswith("L01")


def test_an_unknown_person_gets_the_closest_names():
    with pytest.raises(ToolRefused) as refused:
        run_example("sable_scene_find", {"character": "Kasunn"})
    assert "Kasun" in refused.value.how_to_fix


def test_no_filter_says_what_to_pass():
    with pytest.raises(ToolRefused, match="at least one filter"):
        run_example("sable_scene_find", {"character": None})


def test_it_pages():
    out, _ = run_example("sable_scene_find", {"character": None, "text": "", "episode": 1, "page_size": 2})
    assert len(out.scenes) == 2 and out.next_page == 2 and out.total == 3


def test_another_production_sees_nothing_of_this_one():
    with pytest.raises(ToolRefused):
        run_example("sable_scene_find", {"character": None, "episode": 1}, production_id=uuid4())
