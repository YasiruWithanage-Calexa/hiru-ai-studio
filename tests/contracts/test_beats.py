"""Reading action blocks as pictures by rules (plan/2026-11-01b Phase 2)."""
from __future__ import annotations

import pytest

from contracts import beats, sceneplan
from contracts.shotplan import Item
from tests.services import scene2_fixture as scene2


def test_scene_2_reads_as_the_plan_says():
    items = sceneplan.items_for(scene2.blocks(), scene2.lines())  # nobody classified it: the free rules do
    screens = {i.index: i.screen for i in items if i.kind == "action"}
    assert screens[18] == "inner"  # "He has no idea that this meeting is about to change his life."
    assert screens[11] == "info"  # "It is her father (voice only)."
    assert screens[1] == "move" and screens[16] == "move"
    assert screens[9] == "act" and screens[10] == "act"
    assert screens[14] == "with_line" and screens[4] == "with_line"  # right before the same person's line
    assert screens[13] == "act" and screens[17] == "act"


def test_a_reaction_before_someone_elses_line_is_an_act():
    items = [Item(0, "action", "Anudi smiles."), Item(1, "dialogue", "Hello.", "Kasun", "k", "", "l1")]
    assert beats.read_by_rules(items)[0].screen == "act"
    items = [Item(0, "action", "Kasun smiles."), Item(1, "dialogue", "Hello.", "Kasun", "k", "", "l1")]
    assert beats.read_by_rules(items)[0].screen == "with_line"


@pytest.mark.parametrize(("text", "events"), [
    ("Anudi smiled back.", 1),
    ("Anudi smiled back. Suddenly, her phone rang.", 2),
    ("Kasun picks it up and then runs after her.", 2),
    ("Kasun slides the cheque back. Rs. 5,000 lies on the counter.", 2),  # "Rs." is not a sentence end
    ("", 1),
])
def test_events_are_counted_by_sentence(text, events):
    assert beats.events_in(text) == events


def test_a_stored_reading_wins_and_a_persons_mark_is_never_replaced():
    items = sceneplan.items_for([{"kind": "action", "text": "She walks away.", "line_id": None,
                                  "screen": "act", "events": 1, "by": "person", "for_version": 3}], [])
    assert items[0].screen == "act" and beats.read_by_rules(items) == {}  # a person said so
    assert not beats.is_stale(items, 7)


def test_staleness_follows_the_script_version():
    read = scene2.items()  # read for version 1
    assert not beats.is_stale(read, 1) and beats.is_stale(read, 2)
    assert beats.is_stale(sceneplan.items_for(scene2.blocks(), scene2.lines()), 1)  # never read


def test_annotate_writes_readings_without_touching_the_text_or_the_lines():
    lines = scene2.lines()
    script = scene2.blocks()
    script.insert(3, {"kind": "dialogue", "text": "", "line_id": "gone"})  # a dangling reference stays as it is
    items = sceneplan.items_for(script, lines)
    out = beats.annotate(script, lines, beats.read_by_rules(items), 4, "rules")
    assert [b["text"] for b in out] == [b["text"] for b in script] and len(out) == len(script)
    moved = next(b for b in out if b["text"] == "Anudi walks up to the stall.")
    assert (moved["screen"], moved["events"], moved["by"], moved["for_version"]) == ("move", 1, "rules", 4)
    assert all("screen" not in b for b in out if b["kind"] == "dialogue")
