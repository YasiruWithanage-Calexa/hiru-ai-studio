"""The address space (Nova W1) and the effects table (W4/W7): the header names every op a model may use, `only`
compresses without omitting, and every effect has an owner that can reach it, read from the diff by handle."""
from __future__ import annotations

import re

from contracts.zora import effects as E
from contracts.zora import ops as O
from contracts.zora.render import HEADER, addressable, consumer
from hiru_ai.steps.zora.zora_board.logic import op_effects
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from tests.zora.world import doc


def test_the_header_names_every_operation_a_model_may_use_and_says_there_is_no_other():
    for name in {*O.ops_for("author"), *O.ops_for("conductor")}:
        assert re.search(rf"(?<![\w.]){re.escape(name)} \{{", HEADER), name
    assert "there is no other field and no other operation" in HEADER
    assert "READ-ONLY" in HEADER


def test_the_addressable_plan_numbers_from_one_and_prints_every_shot_with_its_address():
    d = doc()
    text = addressable(d)
    assert "SHOTS (S01–S15)" in text and "S00" not in text
    assert all(f"S{n:02d}  " in text for n in range(1, 16))
    assert "arc 1 (" in text and "colour A:" in text and "Sequence A (S01–S06)" in text


def test_only_prints_the_named_shots_in_full_and_the_rest_one_line_each():
    d = doc()
    full, scoped = addressable(d), addressable(d, only={3})
    assert len(scoped) < len(full)
    assert scoped.count("ir.setting") == 1 and all(f"S{n:02d}  " in scoped for n in range(1, 16))


def test_the_script_is_printed_read_only_with_its_ids_and_a_lock_is_marked():
    d = doc("small", locked=["S03.lens"])
    text = addressable(d)
    assert "b1 line [L1] Anudi, quietly: \"මම යන්න ඕනේ.\"" in text
    assert "lens 85mm: his hurt, close [locked]" in text
    plain = consumer(d, only={3})
    assert "[locked]" in plain and "ir." not in plain


def test_every_effect_has_an_owner_whose_operations_can_produce_it():
    for effect, spec in E.WRITES.items():
        assert spec.owner in ("author", "conductor"), effect
        assert E.can_produce(spec.owner, effect), effect
        for op in spec.ops:
            assert op in O.OPS, (effect, op)


def test_every_op_a_model_writes_maps_to_effects_the_table_knows():
    sample = {"set": {"field": "lens"}, "sound.set": {"field": "music"}, "ir.set": {"path": "lighting"},
              "treatment.set": {"field": "approach"}, "sequence.set": {"field": "title"}}
    for name in {*O.ops_for("author"), *O.ops_for("conductor")}:
        for effect in op_effects({"op": name, **sample.get(name, {})}):
            assert effect in E.WRITES, (name, effect)


def test_declared_effects_are_normalised_and_unknown_ones_dropped():
    assert E.normalize_effect("approach") == "treatment.approach"
    assert E.normalize_effect("lens") == "shot.lens"
    assert E.normalize_effect("shot.ir.cinematography.movement") == "shot.ir.cinematography"
    assert E.normalize_effect("vibes") == ""


def test_the_diff_pairs_shots_by_handle_so_an_insert_does_not_make_every_later_shot_look_changed():
    k = ZoraKernel(doc())
    before = k.export(handles=True)
    k.apply([{"op": "insert", "after": 1, "kind": "atmosphere", "what": "the office"}], by="conductor")
    after = k.export(handles=True)
    old = {s["_h"] for s in before["shots"]}
    assert E.changed_effects(before, after, scope=old) == {"shot.order", "shot.added"}
    k.apply([{"op": "set", "shot": 9, "field": "lens", "value": "135mm"}], by="author")
    later = k.export(handles=True)
    nine = later["shots"][8]["_h"]
    assert "shot.lens" in E.changed_effects(after, later, scope={nine})
    assert "shot.lens" not in E.changed_effects(after, later, scope={later["shots"][2]["_h"]})
