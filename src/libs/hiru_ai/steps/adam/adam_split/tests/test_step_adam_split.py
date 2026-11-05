"""adam_split: a crowded card is repaired in code, so deleting a moment is never the cheap way (plan/2026-11-04c F4)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tests.adam import gold

from hiru_ai.core import parts
from hiru_ai.steps.adam.adam_split import step

HERE = Path(__file__).resolve().parents[1]
SCENE = gold.scene("phone_call")


def crowded() -> dict[str, Any]:
    """The master with its cards 7 and 8 in one card of 8 s: three moments, one line, 10 s of picture (the shape of the
    third live run's crowded card)."""
    plan = copy.deepcopy(gold.master("phone_call"))
    cards = plan["cards"]
    merged = {**cards[6], "moments": cards[6]["moments"] + cards[7]["moments"], "take_s": 8}
    plan["cards"] = [{**c, "number": i} for i, c in enumerate([*cards[:6], merged, *cards[8:]], start=1)]
    return plan


def fit(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", "adam_fit", "step").run({"scene": SCENE, "plan": plan}))


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["changed"] and out["splits"][0]["how"] in ("split", "lengthened")


def test_a_plan_that_fits_is_left_exactly_as_it_is():
    plan = gold.master("phone_call")
    out = step.run({"scene": SCENE, "plan": plan})
    assert not out["changed"] and out["splits"] == [] and out["cards"] == [
        {**c, "number": i} for i, c in enumerate(step.run({"scene": SCENE, "plan": plan})["cards"], start=1)]
    assert [c["moments"] for c in out["cards"]] == [c["moments"] for c in plan["cards"]]
    assert out["renumbered"] == {i: i for i in range(1, 14)}


def test_the_crowded_card_is_split_at_a_moment_boundary_and_every_part_fits():
    plan = crowded()
    assert fit(plan)["overruns"] >= 1  # it is a card the clock refuses
    out = step.run({"scene": SCENE, "plan": plan})
    assert out["changed"] and out["unsplit"] == []
    assert out["splits"][0]["card"] == 7 and out["splits"][0]["how"] == "split" and len(out["splits"][0]["into"]) == 2
    repaired = {**plan, "cards": out["cards"]}
    assert fit(repaired)["overruns"] == 0
    assert all(c["take_s"] in (4, 6, 8) for c in out["cards"])


def test_no_moment_and_no_line_is_lost_or_cut_in_two():
    plan = crowded()
    out = step.run({"scene": SCENE, "plan": plan})
    assert [m for c in out["cards"] for m in c["moments"]] == [m for c in plan["cards"] for m in c["moments"]]
    assert [cl["line_id"] for c in out["cards"] for cl in c.get("lines", [])] == [
        cl["line_id"] for c in plan["cards"] for cl in c.get("lines", [])]


def test_a_later_part_cuts_in_on_a_look_or_an_action_and_copies_the_camera():
    plan = crowded()
    out = step.run({"scene": SCENE, "plan": plan})
    first, second = out["cards"][6], out["cards"][7]
    assert second["cut_in"]["motive"] in ("look", "action") and second["cut_in"]["link"] == "cut"
    assert (first["size"], first["angle"], first["lens_feel"]) == (second["size"], second["angle"], second["lens_feel"])
    assert second["beats"] == []  # the windows were for the whole take


def test_cards_after_the_split_are_numbered_again_and_the_old_numbers_map_to_the_new():
    out = step.run({"scene": SCENE, "plan": crowded()})
    assert [c["number"] for c in out["cards"]] == list(range(1, 14))
    assert out["renumbered"][7] == 7 and out["renumbered"][8] == 9  # what was card 8 is card 9 now


def test_a_longer_take_is_enough_when_it_holds_the_card_and_nothing_is_cut():
    plan = gold.master("phone_call")
    plan["cards"][6]["take_s"] = 4  # card 7 needs 8: a longer take holds it
    out = step.run({"scene": SCENE, "plan": plan})
    assert out["splits"] == [{"card": 7, "into": [7], "at": [], "takes": [8], "how": "lengthened"}]
    assert [c["moments"] for c in out["cards"]] == [c["moments"] for c in plan["cards"]]


def test_one_moment_that_alone_overruns_stays_and_is_reported_never_squeezed():
    plan = gold.master("phone_call")
    plan["moments"][8]["seconds_need"] = 9.0  # m9, the father's line, asks for 9 s of picture
    out = step.run({"scene": SCENE, "plan": plan})
    assert out["unsplit"] and "no way to cut" in out["unsplit"][0]["why"]
    assert fit({**plan, "cards": out["cards"]})["overruns"] >= 1


def test_the_card_that_holds_the_rhythm_break_keeps_the_flag_and_only_it():
    plan = crowded()
    plan["cards"][6]["rhythm_break"] = True
    out = step.run({"scene": SCENE, "plan": plan})
    flagged = [c for c in out["cards"] if c["rhythm_break"]]
    assert len(flagged) == 1 and plan["treatment"]["rhythm_break"]["moment"] in flagged[0]["moments"]


def test_nothing_that_was_handed_in_is_changed():
    plan = crowded()
    before = copy.deepcopy(plan)
    step.run({"scene": SCENE, "plan": plan})
    assert plan == before


def test_a_plan_that_cannot_be_read_is_reported_not_raised():
    out = step.run({"scene": SCENE, "plan": {"moments": [{"id": 1}]}})
    assert out["malformed"] and out["cards"] == []
