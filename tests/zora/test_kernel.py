"""Zora's kernel (plan/2026-11-06e §4.2, Phase 1), on the plans the cinematic lab wrote. Nova's lessons as pinned tests:
addressing from 1 with named ranges (W1), stable addressing within a batch and post-op numbers (finding 3), exact undo,
a bad op never corrupts the plan, removals whole or not at all (W3), locks, and no path that writes a line's words."""
from __future__ import annotations

import json
from typing import Any

import pytest

from contracts.zora.doc import shape_errors
from hiru_ai.steps.zora.zora_kernel import step
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel, settle
from tests.zora.world import SCENES, doc, words


def kernel(name: str = "father_refuses", **kw: Any) -> ZoraKernel:
    return ZoraKernel(doc(name, **kw))


def dump(k: ZoraKernel) -> str:
    return json.dumps({"plan": k.export(), "person": k.person().model_dump()}, sort_keys=True, ensure_ascii=False)


def lines_bound(k: ZoraKernel) -> bool:
    """Every shot's lines are exactly the lines of the blocks it shows, in script order."""
    ids = k.line_ids()
    return all(s["lines"] == [ids[b] for b in sorted(s["blocks"]) if b in ids] for s in k.export()["shots"])


# ── W1: addresses ─────────────────────────────────────────────────────────────────────────────────


def test_an_address_error_names_the_valid_range():
    k = kernel()
    r = k.apply([{"op": "set", "shot": "S40", "field": "lens", "value": "85mm"}])
    assert r.rejected[0]["reason"] == "there is no S40: the scene has S01–S15"
    r = k.apply([{"op": "sequence.set", "id": "Q", "field": "title", "value": "x"}])
    assert "the scene has A, B, C" in r.rejected[0]["reason"]
    r = k.apply([{"op": "arc.set", "n": 9, "beat": "x"}])
    assert "the arc has beats 1–3" in r.rejected[0]["reason"]


def test_two_inserts_after_one_shot_in_one_batch_land_in_order_and_later_numbers_are_the_batchs_start():
    k = kernel()
    ninth = k.export()["shots"][8]["why"]
    r = k.apply([{"op": "insert", "after": 5, "kind": "reaction", "what": "Kasun takes it in", "who": ["Kasun"]},
                 {"op": "insert", "after": 5, "kind": "hands", "what": "his hands on the table", "who": ["Kasun"]},
                 {"op": "set", "shot": 9, "field": "lens", "value": "135mm"}])
    assert not r.rejected
    plan = k.export()
    assert [a["shot"] for a in plan["added"]] == [6, 7] and [a["kind"] for a in plan["added"]] == ["reaction", "hands"]
    assert plan["shots"][10]["why"] == ninth and plan["shots"][10]["lens"] == "135mm"  # S09 at the start is S11 now
    assert len(plan["shots"]) == 17 and [s["n"] for s in plan["shots"]] == list(range(1, 18))


def test_sequences_are_respanned_from_their_shots_after_an_insert():
    k = kernel()
    k.apply([{"op": "insert", "after": 2, "kind": "atmosphere", "what": "the office, empty"}])
    seqs = {q["id"]: q["shots"] for q in k.export()["sequences"]}
    assert seqs["A"] == {"first": 1, "last": 7} and seqs["B"]["first"] == 8


# ── undo, validation, removals ────────────────────────────────────────────────────────────────────

BATCH = [
    {"op": "treatment.set", "field": "approach", "value": "cold, long lenses"},
    {"op": "arc.add", "after": 1, "beat": "a pause", "feeling": "nothing said", "first": 2, "last": 2},
    {"op": "colour.set", "sequence": "B", "field": "grade", "value": "steel blue"},
    {"op": "sequence.set", "id": "A", "field": "title", "value": "Before"},
    {"op": "set", "shot": 3, "field": "size", "value": "ecu"},
    {"op": "retime", "shot": 2, "take_s": 8},
    {"op": "sound.set", "shot": 2, "field": "music", "value": "a low drone"},
    {"op": "ir.set", "shot": 2, "path": "cinematography.movement", "value": "slow push in"},
    {"op": "insert", "after": 1, "kind": "plant", "what": "a detail", "object": ""},
]


@pytest.mark.parametrize("name", SCENES)
def test_undo_restores_the_plan_byte_for_byte(name: str):
    k = kernel(name)
    before = dump(k)
    r = k.apply(BATCH, by="conductor")
    assert r.applied and dump(k) != before
    k.undo(r)
    assert dump(k) == before


@pytest.mark.parametrize("name", SCENES)
def test_whatever_the_batch_the_plan_still_reads_and_every_line_is_bound_and_verbatim(name: str):
    k = kernel(name)
    k.apply([*BATCH, {"op": "split", "shot": 1}, {"op": "merge", "shots": [3, 4]}, {"op": "remove", "shot": 2}],
            by="author")
    d = k.doc()
    assert shape_errors(d.plan, d.scene) == []
    assert lines_bound(k)
    assert words(d) == words(doc(name))  # the script is never touched


def test_a_bad_op_is_rolled_back_alone_and_the_rest_of_the_batch_lands():
    k = kernel()
    r = k.apply([{"op": "set", "shot": 3, "field": "size", "value": "GIANT"},
                 {"op": "set", "shot": 3, "field": "lens", "value": "85mm"},
                 {"op": "retime", "shot": 3, "take_s": 5}])
    assert [x["op"] for x in r.applied] == ["set"]
    assert {x["reason"] for x in r.rejected} == {"size must be one of EWS, WIDE, MWS, MS, MCU, CU, ECU, TWO, OTS, "
                                                 "INSERT, POV", "a take is 4, 6 or 8 seconds (what Veo makes)"}


def test_the_planners_own_validation_rolls_back_what_the_shape_check_lets_through():
    calls = []

    def strict(plan: dict[str, Any]) -> list[str]:
        calls.append(1)
        return ["shots.2.lens: no fisheyes"] if "fisheye" in plan["shots"][2]["lens"] else []

    k = ZoraKernel(doc(), validate=strict)
    before = dump(k)
    r = k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "8mm fisheye"}])
    assert r.rejected and "no fisheyes" in r.rejected[0]["reason"] and dump(k) == before and calls


def test_the_step_checks_with_the_planners_validation_by_id():
    d = doc()
    out = step.run({"doc": d.model_dump(), "ops": [{"op": "set", "shot": 1, "field": "lens", "value": "85mm"}]})
    assert out["applied"] and out["person"]["locked"] == ["S01.lens"]


def test_removals_land_whole_or_not_at_all():
    k = kernel("arrival")  # S06, S07, S09 are added shots with no script block; S01 shows the script
    before = dump(k)
    r = k.apply([{"op": "remove", "shot": 6}, {"op": "remove", "shot": 1}, {"op": "remove", "shot": 7}],
                by="author")
    assert not r.applied and len(r.rejected) == 3 and dump(k) == before
    assert any("whole or not at all" in x["reason"] for x in r.rejected)
    r = k.apply([{"op": "remove", "shot": 6}, {"op": "remove", "shot": 7}], by="author")
    assert len(r.applied) == 2 and len(k.export()["shots"]) == 11
    assert {a["kind"] for a in k.export()["added"]} == {"reaction", "hold"}  # their additions went with them


def test_a_shot_that_shows_the_script_cannot_be_removed_or_moved_only_merged():
    k = kernel()
    r = k.apply([{"op": "remove", "shot": 4}])
    assert "shows b1 (L1) of the script" in r.rejected[0]["reason"] and "merge it" in r.rejected[0]["reason"]
    r = k.apply([{"op": "move", "shot": 4, "after": 9}])
    assert "out of order" in r.rejected[0]["reason"]


# ── locks ─────────────────────────────────────────────────────────────────────────────────────────


def test_a_lock_refuses_the_author_and_lets_the_person_and_their_words_through():
    k = kernel(locked=["S03.lens", "treatment.approach"])
    r = k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "50mm"},
                 {"op": "treatment.set", "field": "approach", "value": "x"}], by="author")
    assert [x["reason"] for x in r.rejected] == ["S03.lens is locked: a person set it",
                                                 "treatment.approach is locked: a person set it"]
    assert not k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "50mm"}], by="conductor").rejected


def test_what_the_person_sets_becomes_locked_and_a_lock_follows_its_shot_when_shots_are_renumbered():
    k = kernel()
    k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "85mm"}], by="conductor")
    k.apply([{"op": "insert", "after": 1, "kind": "atmosphere", "what": "the office"}], by="author")
    assert k.person().locked == ["S04.lens"]
    assert k.apply([{"op": "set", "shot": 4, "field": "lens", "value": "50mm"}], by="author").rejected
    assert not k.apply([{"op": "set", "shot": 3, "field": "lens", "value": "50mm"}], by="author").rejected


def test_a_lock_on_one_of_two_merged_shots_refuses_the_authors_merge():
    k = kernel(locked=["S05"])
    r = k.apply([{"op": "merge", "shots": [4, 5]}], by="author")
    assert r.rejected and "S05 is locked" in r.rejected[0]["reason"]


def test_locks_are_a_persons_click_and_settled_choices_are_kept():
    k = kernel()
    assert k.apply([{"op": "lock", "path": "S02.size"}], by="author").rejected
    assert not k.apply([{"op": "lock", "path": "S02.size"}], by="person").rejected
    settle(k, "S02.lens")
    assert k.person().locked == ["S02.size"] and k.person().settled == ["S02.lens"]
    assert not k.apply([{"op": "unlock", "path": "S02.size"}], by="person").rejected and k.person().locked == []


# ── lines are the script's ────────────────────────────────────────────────────────────────────────


def test_no_operation_writes_a_lines_words_and_script_ops_are_staged_never_applied():
    k = kernel()
    before = dump(k)
    r = k.apply([{"op": "set", "shot": 4, "field": "lines", "value": "x"},
                 {"op": "block.set", "block": 1, "text": "new words"}], by="author")
    assert len(r.rejected) == 2 and "a person's own change, staged as a card" in r.rejected[1]["reason"]
    r = k.apply([{"op": "block.set", "block": 1, "text": "new words"}], by="person")
    assert r.staged and not r.applied and dump(k) == before


def test_a_split_divides_at_a_block_boundary_and_each_part_carries_only_its_own_lines():
    d = doc("episode1")
    shot = next(s for s in d.shots if len(s["blocks"]) >= 2 and s["lines"])
    k = ZoraKernel(d)
    at = sorted(shot["blocks"])[1]
    r = k.apply([{"op": "split", "shot": shot["n"], "at_block": at}], by="conductor")
    assert not r.rejected
    a, b = k.export()["shots"][shot["n"] - 1:shot["n"] + 1]
    assert a["blocks"] == [x for x in sorted(shot["blocks"]) if x < at] and b["blocks"][0] == at
    assert lines_bound(k) and a["why"] == "" and b["why"] == "" and b["link"] == "cut"
    r = k.apply([{"op": "split", "shot": 1, "at_block": 0}])
    assert "can be divided before" in r.rejected[0]["reason"] or "nothing to divide" in r.rejected[0]["reason"]


def test_a_merge_joins_two_neighbours_and_their_lines_follow():
    k = kernel()
    r = k.apply([{"op": "merge", "shots": [4, 5]}])
    assert not r.rejected
    merged = k.export()["shots"][3]
    assert merged["blocks"] == [1, 2] and merged["lines"] == ["L1", "L2"] and merged["why"] == ""
    assert k.apply([{"op": "merge", "shots": [1, 3]}]).rejected  # not neighbours


# ── the treatment, sequences, staging, end state ──────────────────────────────────────────────────


def test_sequence_bounds_move_shots_between_sequences_and_keep_each_one_run():
    k = kernel()  # A S01–S06, B S07–S11, C S12–S15
    r = k.apply([{"op": "sequence.bounds", "id": "B", "first": 5, "last": 11}])
    assert not r.rejected
    seqs = {q["id"]: q["shots"] for q in k.export()["sequences"]}
    assert seqs == {"A": {"first": 1, "last": 4}, "B": {"first": 5, "last": 11}, "C": {"first": 12, "last": 15}}
    r = k.apply([{"op": "regroup", "shot": 8, "sequence": "C"}])
    assert "one run of shots" in r.rejected[0]["reason"]


def test_a_new_sequence_gets_a_colour_entry_with_the_scenes_light_and_an_empty_palette():
    k = kernel()
    r = k.apply([{"op": "sequence.add", "title": "The turn", "purpose": "he decides", "first": 10, "last": 11}])
    assert not r.rejected
    plan = k.export()
    assert [q["id"] for q in plan["sequences"]] == ["A", "B", "D", "C"]
    colour = next(c for c in plan["treatment"]["colour_script"] if c["sequence"] == "D")
    assert colour["palette"] == "" and colour["light"]


def test_staging_marks_and_the_end_state_are_checked_against_the_cast_and_the_zones():
    k = kernel("small")
    assert k.apply([{"op": "mark.add", "block": 2, "who": "Kasun", "zone": "bench left"}], by="author").rejected
    assert k.apply([{"op": "mark.add", "block": 2, "who": "Dasun", "zone": "the moon"}], by="author").rejected
    assert not k.apply([{"op": "zone.add", "zone": "the path"},
                        {"op": "mark.add", "block": 2, "who": "Dasun", "zone": "the path", "facing": "left"}],
                       by="author").rejected
    assert k.apply([{"op": "end.set", "who": "Dasun", "field": "where", "value": "the path"}], by="author").rejected
    assert not k.apply([{"op": "end.set", "who": "Dasun", "field": "where", "value": "the path"}],
                       by="conductor").rejected
