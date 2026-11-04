from __future__ import annotations

from tests.hiru_ai.steps_fixtures import bundle, felt_scene, teleporting_scene

from hiru_ai.steps.stage_check import step


def test_a_scene_whose_people_stay_put_has_no_findings():
    out = step.run(bundle(*felt_scene()))
    assert out["findings"] == [] and out["moves"] == []


def test_a_person_who_changes_spot_with_no_move_between_is_a_teleport():
    out = step.run(bundle(*teleporting_scene()))
    assert [f["code"] for f in out["findings"]] == ["teleport"] and out["findings"][0]["block"] == 5
    assert out["moves"] == [{"before_block": 5, "who": "Anudi", "zone": "stall"}]


def test_a_scene_with_no_map_is_not_checked():
    scene, lines, shots = felt_scene()
    out = step.run(bundle({k: v for k, v in scene.items() if k != "staging"}, lines, shots))
    assert out["findings"] == [] and out["unplaced"] == []
