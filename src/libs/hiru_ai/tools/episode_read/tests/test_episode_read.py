from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import run_example


def test_the_episode_of_the_scene_around_which_it_is_asked():
    out, _ = run_example("episode_read")
    assert (out.episode, out.title) == (1, "The Meeting") and out.synopsis.startswith("Anudi meets")
    assert [s["scene"] for s in out.scenes] == ["E1S1", "E1S2", "E1S3"]


def test_the_scenes_either_side_even_across_an_episode():
    out, _ = run_example("episode_read")
    assert out.previous and out.previous["scene"] == "E1S1" and out.next and out.next["scene"] == "E1S3"
    last, _ = run_example("episode_read", {"episode": 1, "around_scene": "E1S3"}, scene_id=None)
    assert last.next and last.next["scene"] == "E2S1" and last.previous["scene"] == "E1S2"


def test_an_episode_by_number_with_no_scene_in_scope():
    out, _ = run_example("episode_read", {"episode": 2, "around_scene": None}, scene_id=None)
    assert out.episode == 2 and out.status == "draft" and out.previous is None and out.next is None


def test_with_nothing_to_go_on_it_says_what_to_pass():
    with pytest.raises(ToolRefused, match="no scene in scope"):
        run_example("episode_read", {"around_scene": None}, scene_id=None)


def test_an_unknown_episode_lists_the_ones_there_are():
    with pytest.raises(ToolRefused) as refused:
        run_example("episode_read", {"episode": 9, "around_scene": None})
    assert "1" in refused.value.how_to_fix
