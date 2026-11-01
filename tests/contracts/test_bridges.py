"""Implied steps (plan/2026-11-01b Phase 3): closed list, rules only, removable, remembered."""
from __future__ import annotations

from contracts import bridges, sceneplan
from tests.services import scene2_fixture as scene2


def texts(script):
    return [b["text"] for b in script if b["kind"] != "dialogue"]


def test_scene_2_gets_the_answer_before_the_voice_and_the_lowering_after_it():
    script = bridges.with_bridges(scene2.blocks(), scene2.lines(), 1)
    ring = next(i for i, b in enumerate(script) if "rang" in b["text"])
    voice = next(i for i, b in enumerate(script) if b["kind"] == "dialogue" and b["line_id"] == "l5")
    answer = next(i for i, b in enumerate(script) if b.get("bridge") == bridges.ANSWER_PHONE)
    lower = next(i for i, b in enumerate(script) if b.get("bridge") == bridges.LOWER_PHONE)
    assert ring < answer < voice < lower
    assert script[answer]["text"] == "Anudi answers the phone." and script[lower]["text"] == "Anudi lowers the phone."
    assert script[answer]["implied"] and script[answer]["by"] == "rules" and script[answer]["line_id"] is None
    assert len(script) == len(scene2.blocks()) + 2  # nothing else added, no line, no new person


def test_the_bridge_counts_on_the_picture_clock():
    script = bridges.with_bridges(scene2.blocks(), scene2.lines(), 1)
    items = sceneplan.items_for(script, scene2.lines())
    bridge = next(i for i in items if i.bridge == bridges.ANSWER_PHONE)
    assert bridge.implied and bridge.picture_s == 1.5


def test_a_script_that_already_says_she_answered_gets_no_answer_bridge():
    script = scene2.blocks()
    ring = next(b for b in script if b["text"] == "Suddenly, her phone rang.")
    ring["text"] = "Suddenly, her phone rang. She answered."
    out = bridges.with_bridges(script, scene2.lines(), 1)
    assert not [b for b in out if b.get("bridge") == bridges.ANSWER_PHONE]
    nxt = bridges.with_bridges(scene2.blocks(), scene2.lines(), 1)
    nxt = [dict(b, text=b["text"].replace("It is her father (voice only).", "She picks up.")) for b in nxt]
    assert not [b for b in bridges.with_bridges(nxt, scene2.lines(), 1) if b.get("bridge") == bridges.ANSWER_PHONE]


def test_a_call_that_is_put_down_in_the_script_gets_no_lowering():
    script = scene2.blocks()
    next(b for b in script if b["text"] == "Her smile disappeared.")["text"] = "She lowers the phone, smile gone."
    out = bridges.with_bridges(script, scene2.lines(), 1)
    assert not [b for b in out if b.get("bridge") == bridges.LOWER_PHONE]


def test_removing_a_bridge_is_remembered_and_a_resplit_does_not_bring_it_back():
    script = bridges.with_bridges(scene2.blocks(), scene2.lines(), 1)
    at = next(i for i, b in enumerate(script) if b.get("bridge") == bridges.ANSWER_PHONE)
    after_removal = bridges.skip_bridge(script, at)
    line = next(b for b in after_removal if b.get("line_id") == "l5")
    assert line["skip_bridges"] == [bridges.ANSWER_PHONE]
    again = bridges.with_bridges(after_removal, scene2.lines(), 2)
    assert not [b for b in again if b.get("bridge") == bridges.ANSWER_PHONE]
    assert [b for b in again if b.get("bridge") == bridges.LOWER_PHONE]  # the other one is still wanted


def test_with_bridges_is_idempotent():
    once = bridges.with_bridges(scene2.blocks(), scene2.lines(), 1)
    assert bridges.with_bridges(once, scene2.lines(), 1) == once


def test_a_block_that_is_not_a_bridge_cannot_be_skipped():
    try:
        bridges.skip_bridge(scene2.blocks(), 0)
    except ValueError as e:
        assert "implied" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_the_skip_survives_the_directors_working_copy():
    script = bridges.skip_bridge(bridges.with_bridges(scene2.blocks(), scene2.lines(), 1),
                                 next(i for i, b in enumerate(bridges.with_bridges(
                                     scene2.blocks(), scene2.lines(), 1)) if b.get("bridge") == bridges.ANSWER_PHONE))
    rows = [sceneplan.item_row(i) for i in sceneplan.items_for(script, scene2.lines())]
    assert sceneplan.script_rows(rows)[next(i for i, b in enumerate(script) if b.get("line_id") == "l5")][
        "skip_bridges"] == [bridges.ANSWER_PHONE]
