from __future__ import annotations

from tests.hiru_ai.steps_fixtures import bundle, felt_scene, teleporting_scene

from hiru_ai.steps.kernel_score import step


def test_a_plan_scores_ten_terms_and_says_what_it_is():
    out = step.run(bundle(*felt_scene()))
    assert len(out["score"]) == 10 and all(isinstance(n, int) for n in out["score"])
    assert out["described"].startswith("Envelope: 16 s.") and "S01 MCU" in out["described"]


def test_a_teleport_costs_one_point_in_its_own_term():
    felt = step.run(bundle(*felt_scene()))["score"]
    tele = step.run(bundle(*teleporting_scene()))["score"]
    assert tele[4] == felt[4] + 1 and tele[:4] == felt[:4]


def test_scores_compare_left_to_right_so_a_clipped_line_always_loses():
    assert (1, 0, 0, 0, 0, 0, 0, 0, 0, 0) > (0, 9, 9, 9, 9, 9, 9, 9, 9, 9)
