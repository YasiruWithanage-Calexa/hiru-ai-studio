"""The scene-plan edit algebra: operations applied in code, locks, exact undo, dialogue read-only."""
from __future__ import annotations

from director_chat.engine.kernel import ScenePlanKernel
from director_chat.engine.turn import kernel_for

from tests.services.director_chat.conftest import fixture_scene


def kernel(n: int = 0, fixed: int | None = None, **kw) -> ScenePlanKernel:
    scene, lines, shots = fixture_scene(n, **kw)
    return kernel_for(scene, lines, shots, fixed)


def test_loads_the_stored_plan_with_ids_as_handles():
    scene, lines, shots = fixture_scene(0)
    k = kernel_for(scene, lines, shots, None)
    assert k.handles() == [s["id"] for s in shots]
    assert [(s["start"], s["end"]) for s in k.shots] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert "S02" in k.describe() and "Nimal" in k.describe()


def test_a_person_sets_a_length_and_it_is_locked():
    k = kernel()
    r = k.apply([{"op": "retime", "shot": 2, "seconds": 8}], by="you", respect_locks=False)
    assert r.applied and not r.rejected
    assert k.shots[1]["duration"] == 8 and k.shots[1]["duration_locked"]
    assert k.fit().shots[1].duration_s == 8
    # an agent may not change a length a person set
    r2 = k.apply([{"op": "retime", "shot": 2, "seconds": 4}], by="timing", respect_locks=True)
    assert not r2.applied and "person set" in r2.rejected[0]["reason"]
    # only the person may release it
    assert k.apply([{"op": "unlock_length", "shot": 2}], by="timing").rejected
    assert k.apply([{"op": "unlock_length", "shot": 2}], by="you", respect_locks=False).applied
    assert not k.shots[1]["duration_locked"]


def test_lengths_are_veo_lengths():
    k = kernel()
    assert "4, 6, 8" in k.apply([{"op": "retime", "shot": 1, "seconds": 10}], respect_locks=False).rejected[0]["reason"]
    fixed = kernel(fixed=8)
    assert fixed.apply([{"op": "retime", "shot": 1, "seconds": 6}], respect_locks=False).rejected
    assert all(s.duration_s == 8 for s in fixed.fit().shots)


def test_dialogue_is_changed_only_by_a_person_through_block_set():
    k = kernel()
    r = k.apply([{"op": "line.edit", "line": 1, "text": "x"}, {"op": "set", "shot": 2, "field": "duration_s",
                                                                "value": "8"}])
    reasons = [x["reason"] for x in r.rejected]
    assert "name the line" in reasons[0] and "retime" in reasons[1]
    assert not r.applied
    first = next(i for i, b in enumerate(k.items) if b["kind"] == "dialogue")
    agent = k.apply([{"op": "block.set", "block": first, "field": "text", "value": "x"}], by="timing")
    assert "only a person's own words" in agent.rejected[0]["reason"]  # the full set is in test_kernel_script.py


def test_split_merge_regroup_keep_every_block_once():
    k = kernel(per_block=False)  # one shot over the whole scene
    assert len(k.shots) == 1
    r = k.apply([{"op": "split", "shot": 1, "at_block": 2, "framing": "CU"}])
    assert r.applied and [(s["start"], s["end"]) for s in k.shots] == [(0, 2), (2, 4)]
    assert k.shots[1]["framing"] == "CU" and k.shots[1]["id"] is None
    assert k.apply([{"op": "regroup", "shot": 1, "end_block": 3}]).applied
    assert [(s["start"], s["end"]) for s in k.shots] == [(0, 3), (3, 4)]
    assert k.apply([{"op": "regroup", "shot": 1, "end_block": 4}]).rejected  # would empty shot 2
    assert k.apply([{"op": "merge", "shot": 1}]).applied and len(k.shots) == 1
    assert k.apply([{"op": "merge", "shot": 1}]).rejected  # nothing after it


def test_numbers_in_one_batch_refer_to_the_plan_before_the_batch():
    k = kernel()
    r = k.apply([{"op": "insert", "after_shot": 1, "description": "Kamala's hands on the pan"},
                 {"op": "set", "shot": 2, "field": "framing", "value": "CU"}])
    assert len(r.applied) == 2
    # "shot 2" was Nimal's line before the insert; it is shot 3 now and got the framing
    assert k.items[1]["kind"] == "beat" and k.shots[1]["start"] == 1
    assert k.shots[2]["framing"] == "CU" and k.items[k.shots[2]["start"]]["speaker"] == "Nimal"


def test_insert_and_remove_a_reaction_shot():
    k = kernel()
    before = len(k.items)
    assert k.apply([{"op": "insert", "after_shot": 0, "description": "Close on the wood fire", "framing": "INSERT"}],
                   ).applied
    assert len(k.items) == before + 1 and k.shots[0]["framing"] == "INSERT" and k.shots[0]["start"] == 0
    assert k.apply([{"op": "remove", "shot": 1}]).applied
    assert len(k.items) == before and [(s["start"], s["end"]) for s in k.shots] == [(0, 1), (1, 2), (2, 3), (3, 4)]


def test_removing_a_script_shot_never_removes_script():
    k = kernel()
    assert k.apply([{"op": "remove", "shot": 3}]).applied  # the action between the two lines
    assert len(k.items) == 4 and [(s["start"], s["end"]) for s in k.shots] == [(0, 1), (1, 3), (3, 4)]
    one = kernel(per_block=False)
    assert "at least one shot" in one.apply([{"op": "remove", "shot": 1}]).rejected[0]["reason"]


def test_undo_is_exact():
    k = kernel()
    snapshot = ([dict(s) for s in k.shots], list(k.items))
    r = k.apply([{"op": "split", "shot": 1, "at_block": 0}, {"op": "merge", "shot": 2},
                 {"op": "set_envelope", "seconds": 30}], respect_locks=False)
    assert r.applied and r.rejected  # the split falls outside shot 1
    k.undo(r)
    assert ([dict(s) for s in k.shots], list(k.items)) == snapshot and k.envelope_s == 60


def test_join_rules_and_beats():
    k = kernel()
    assert "first shot" in k.apply([{"op": "set_join", "shot": 1, "link": "continuous"}]).rejected[0]["reason"]
    assert k.apply([{"op": "set_join", "shot": 2, "link": "continuous"}]).applied
    assert k.fit().shots[1].frame_strategy.value == "carry_last_frame"
    assert k.apply([{"op": "beat.set", "shot": 2, "beat": 0, "field": "camera", "value": "slow push in"}]).applied
    assert k.shots[1]["beat_notes"][0]["camera"] == "slow push in"
    assert k.apply([{"op": "beat.set", "shot": 2, "beat": 3, "field": "camera", "value": "x"}]).rejected


def test_allowed_ops_limit_a_specialist():
    k = kernel()
    r = k.apply([{"op": "merge", "shot": 1}], by="sound", allowed_ops=("set",))
    assert "sound may not use merge" in r.rejected[0]["reason"]


def test_a_shot_the_kernel_must_split_is_taken_in_so_numbers_match():
    scene, lines, shots = fixture_scene(0)
    # one person-unlocked shot holding both lines and the action between them, with lines long
    # enough that 8 s cannot hold them: the fit splits it, and the kernel adopts the split
    for ln in lines:
        ln["text"] = " ".join([ln["text"]] * 6)
    k = kernel_for(scene, lines, [{**shots[0], "block_start": 0, "block_end": 4, "number": 1}], None)
    fitted = k.fit()
    assert len(k.shots) == len(fitted.shots) >= 2
    assert k.shots[0]["id"] == shots[0]["id"] and k.shots[1]["id"] is None
    assert k.shots[1]["camera_link"] == "continuous"
    for n, f in enumerate(fitted.shots, start=1):
        assert f"S{n:02d}" in k.describe() and (k.shots[n - 1]["start"], k.shots[n - 1]["end"]) == (f.start, f.end)


def test_common_names_for_framing_and_sound_are_understood():
    k = kernel()
    r = k.apply([{"op": "set", "shot": 1, "field": "framing", "value": "Close-up "},
                 {"op": "set", "shot": 2, "field": "framing", "value": "over the shoulder"},
                 {"op": "set", "shot": 3, "field": "sound_mode", "value": "Silence"},
                 {"op": "set", "shot": 1, "field": "sound_mode", "value": "music"}])
    assert not r.rejected
    assert [s["framing"] for s in k.shots[:2]] == ["CU", "OTS"]
    assert k.shots[2]["sound_mode"] == "silent" and k.shots[0]["sound_mode"] == "music_only"
    bad = k.apply([{"op": "set", "shot": 3, "field": "sound_mode", "value": "The radio only, no music"}])
    assert "sound_mode must be one of" in bad.rejected[0]["reason"]
