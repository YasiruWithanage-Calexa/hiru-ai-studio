"""adam_distinct: treatments that differ on purpose (plan/2026-11-04b §10 Phase 3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_distinct import logic, step

HERE = Path(__file__).resolve().parents[1]


def t(name: str, **edit: Any) -> dict[str, Any]:
    base = {"name": name, "concept": "c", "pov": "Anudi's throughout", "sound_concept": "the world stays the same",
            "size_arc": ["MWS", "MS", "MWS"]}
    return {**base, **edit}


def codes(out: dict[str, Any]) -> list[str]:
    return [i["code"] for i in out["issues"]]


def test_the_example_runs_alone_and_passes():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["ok"], out["issues"]
    assert len(out["pairs"]) == 3


def test_three_copies_of_one_idea_are_refused_with_the_axes_they_share():
    out = step.run({"treatments": [t("a"), t("b"), t("c")]})
    assert not out["ok"] and codes(out) == ["alike"] * 3
    assert out["pairs"][0]["differs"] == [] and out["pairs"][0]["same"] == ["size_arc", "pov", "sound_concept"]


def test_one_axis_is_not_enough_two_are():
    one = [t("a"), t("b", size_arc=["WS", "CU", "ECU"]), t("c", size_arc=["MS", "ECU", "MS"])]
    assert "alike" in codes(step.run({"treatments": one}))
    two = [t("a"), t("b", size_arc=["WS", "CU", "ECU"], pov="Dasun's"),
           t("c", size_arc=["MS", "ECU", "MS"], sound_concept="music enters at the turn")]
    out = step.run({"treatments": two})
    # b/c differ on arc, pov and sound; a/b on arc and pov; a/c on arc and sound
    assert out["ok"], out["issues"]


def test_an_arc_differs_by_its_peak_or_by_half_its_places():
    assert logic.arcs_differ(["MWS", "CU", "MWS"], ["MWS", "ECU", "MWS"])  # a different peak
    assert not logic.arcs_differ(["MWS", "CU", "MWS"], ["MWS", "CU", "MWS"])
    assert logic.arcs_differ(["MS", "CU", "CU", "MS"], ["WS", "CU", "MCU", "WS"])  # same peak, half the places differ
    assert not logic.arcs_differ(["MS", "CU", "CU", "MS"], ["MS", "CU", "CU", "WS"])  # one place in four
    assert logic.arcs_differ(["MS", "CU"], ["MS", "CU", "ECU", "WS"])  # longer, with a new peak
    assert not logic.arcs_differ([], ["MS"])  # nothing said cannot differ


def test_words_that_mostly_overlap_say_the_same_thing():
    assert not logic.words_differ("Anudi's, all the way through", "Anudi's, all the way through the scene")
    assert logic.words_differ("Anudi's, then Dasun's", "the father's voice")
    assert not logic.words_differ("", "anything")


def test_names_and_stances_must_be_different_and_the_count_is_checked():
    out = step.run({"treatments": [t("same", stance="intimate"), t("same", stance="intimate"), t("c")]})
    assert {"same_name", "same_stance"} <= set(codes(out))
    assert codes(step.run({"treatments": [t("a")]}))[0] == "count"
    assert step.run({"treatments": [t("a")], "expected": 1})["ok"]


def test_a_malformed_treatment_is_reported_not_raised():
    out = step.run({"treatments": [{"nope": 1}]})
    assert not out["ok"] and codes(out) == ["malformed"]


# ── choosing one ─────────────────────────────────────────────────────────────────────────────────


def three(name: str) -> list[dict[str, Any]]:
    from tests.adam import stages

    return [t.model_dump(mode="json", by_alias=True) for t in stages.director_wire(name).all()]


def test_the_choice_is_one_of_the_three_with_a_score_that_explains_itself():
    from tests.adam import stages

    out = step.run({"treatments": three("phone_call"), "analysis": stages.unbound(stages.plan("phone_call"))[0]
                    .model_dump(mode="json", by_alias=True)})
    choice = out["choice"]
    assert out["ok"] and choice["stance"] in ("restrained", "intimate", "heightened")
    assert [s["stance"] for s in choice["scores"]] == ["restrained", "intimate", "heightened"]
    assert all(0 <= s["distinct"] <= 1 and s["fit"] <= 5 for s in choice["scores"])
    assert choice["scores"][choice["index"]]["total"] == max(s["total"] for s in choice["scores"])


def test_a_treatment_that_answers_the_analysis_beats_one_that_does_not_and_a_tie_keeps_the_earlier():
    from tests.adam import stages

    analysis = stages.unbound(stages.plan("phone_call"))[0].model_dump(mode="json", by_alias=True)
    good = three("phone_call")
    bare = {**good[0], "pov": "", "entry": "", "exit": "", "ending_image": "", "rhythm_break": None, "sections": []}
    out = step.run({"treatments": [bare, good[1], good[2]], "analysis": analysis})["choice"]
    assert out["index"] != 0 and out["scores"][0]["fit"] < out["scores"][out["index"]]["fit"]
    assert any("rhythm break" in w for w in out["scores"][0]["why"])
    twins = step.run({"treatments": [good[1], {**good[1], "name": "b", "stance": "x"}], "analysis": analysis})
    assert twins["choice"]["index"] == 0


def test_an_over_directed_treatment_loses_a_point_and_is_named():
    from tests.adam import stages

    analysis = stages.unbound(stages.plan("phone_call"))[0].model_dump(mode="json", by_alias=True)
    good = three("phone_call")
    stuffed = {**good[0], "size_arc": ["ECU"] * 20}
    out = step.run({"treatments": [stuffed, good[1]], "analysis": analysis})["choice"]
    assert out["scores"][0]["sane"] is False and "over-directed" in out["scores"][0]["why"]


def test_a_malformed_analysis_is_reported_not_raised():
    out = step.run({"treatments": [], "expected": 0, "analysis": {"nope": 1}})
    assert out["choice"]["index"] is None and "malformed" in out["choice"]
