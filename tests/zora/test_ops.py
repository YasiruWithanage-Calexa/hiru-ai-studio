"""Zora's grammar and document (plan/2026-11-06e §4.1, §4.2, Phase 1): the copied vocabulary never drifts from the
planner's, addresses read the way people write them, the conductor's invention guard (Nova W4 and its fix)."""
from __future__ import annotations

import importlib

import pytest

from contracts.zora import ops as O
from contracts.zora.doc import Person, shape_errors
from tests.zora.world import SCENES, doc

PLANNER = "jonathan"  # the planner whose stored plan Zora edits


def test_the_copied_vocabulary_is_the_planners_to_the_letter():
    plan = importlib.import_module(f"contracts.{PLANNER}.plan")
    assert plan.SIZES == O.SIZES
    assert plan.LINKS == O.LINKS
    assert plan.TAKES == O.TAKES
    assert plan.ADDED_KINDS == O.ADDED_KINDS


def test_a_shot_is_named_the_way_people_write_it():
    assert [O.shot_number(v) for v in (3, "3", "S03", "s3", " S10 ")] == [3, 3, 3, 3, 10]
    with pytest.raises(O.OpError):
        O.shot_number("the third one")
    assert O.code(3) == "S03"


def test_a_set_without_its_name_is_read_as_the_set_it_plainly_is_and_nothing_else_is_guessed():
    assert O.infer_op({"shot": 3, "field": "lens", "value": "85mm"})["op"] == "set"
    assert "op" not in O.infer_op({"shot": 3, "value": "85mm"})
    assert "op" not in O.infer_op({"field": "lens", "value": "85mm"})


def test_who_may_write_what():
    author = set(O.ops_for("author"))
    conductor = set(O.ops_for("conductor"))
    person = set(O.ops_for("person"))
    assert "end.set" in conductor and "end.set" not in author  # the end state: only the person's own words
    assert {"mark.add", "mark.set"} <= author and "mark.add" not in conductor  # staging is the author's craft
    for staged in ("block.set", "block.insert", "block.remove", "canon.add", "check.waive", "dop_note.set"):
        assert staged in person and staged not in author and staged not in conductor
    assert set(O.ops_for("translator")) == {"block.translate"}
    assert "lock" in person and "lock" not in author and "lock" not in conductor  # a lock is a person's click


def test_every_op_has_an_address_in_one_namespace():
    assert O.path_of({"op": "set", "shot": "S03", "field": "lens"}) == "S03.lens"
    assert O.path_of({"op": "retime", "shot": 3, "take_s": 8}) == "S03.take_s"
    assert O.path_of({"op": "ir.set", "shot": 2, "path": "cinematography.movement"}) == "S02.ir.cinematography.movement"
    assert O.path_of({"op": "treatment.set", "field": "approach"}) == "treatment.approach"
    assert O.path_of({"op": "colour.set", "sequence": "A", "field": "grade"}) == "colour.A.grade"
    assert O.path_of({"op": "merge", "shots": [3, 4]}) == "S03+S04"
    assert O.path_of({"op": "end.set", "who": "Anudi", "field": "where"}) == "end.Anudi.where"


# ── W4: the conductor transcribes; it never composes craft ─────────────────────────────────────────


def test_quoting_the_person_passes_and_a_composed_line_of_craft_does_not():
    msg = "make the approach cold, long lenses and nobody close to anybody"
    quoted = {"op": "treatment.set", "field": "approach", "value": "cold, long lenses, nobody close to anybody"}
    composed = {"op": "treatment.set", "field": "approach",
                "value": "A glacial telephoto vocabulary isolating each figure against bleached negative space"}
    assert not O.invented(quoted, msg)
    assert O.invented(composed, msg)


def test_trimming_the_text_that_is_there_is_an_edit_not_an_invention():
    current = "Wide and still for the ease, closer and longer lenses as the call lands, a held wide for the exit."
    trimmed = {"op": "treatment.set", "field": "approach",
               "value": "Wide and still for the ease, a held wide for the exit."}
    assert not O.invented(trimmed, "drop the closer lenses bit", current)
    assert O.invented(trimmed, "drop the closer lenses bit")  # judged on the message alone it would look composed


def test_closed_values_and_short_values_are_never_inventions():
    assert not O.invented({"op": "set", "shot": 3, "field": "size", "value": "ECU"}, "hi")
    assert not O.invented({"op": "set", "shot": 3, "field": "lens", "value": "85mm"}, "hi")
    assert not O.invented({"op": "retime", "shot": 3, "take_s": 8}, "hi")


# ── the document ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [*SCENES, "small"])
def test_every_saved_plan_reads(name: str):
    d = doc(name)
    assert shape_errors(d.plan, d.scene) == []


def test_the_shape_check_names_what_is_wrong():
    d = doc("small")
    plan = d.plan
    plan["shots"][0]["size"] = "CLOSE"
    plan["shots"][1]["take_s"] = 5
    plan["shots"][2]["lines"] = ["L9"]
    plan["shots"][2]["sequence"] = "Z"
    found = " | ".join(shape_errors(plan, d.scene))
    assert "S01's size 'CLOSE'" in found and "S02's take 5" in found
    assert "S03 names a line the scene does not have" in found and "sequence 'Z'" in found


def test_a_lock_on_a_shot_covers_its_fields_and_nothing_else():
    p = Person(locked=["S03", "treatment.approach"])
    assert p.is_locked("S03.lens") and p.is_locked("S03") and p.is_locked("treatment.approach")
    assert not p.is_locked("S30.lens") and not p.is_locked("treatment.geography")
