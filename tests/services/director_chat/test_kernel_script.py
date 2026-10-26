"""A person's changes to the script, a shot's cast, its ignored checks and its DoP note: applied in
code, person-only, addressed by the numbers at the start of the batch, and exactly undoable."""
from __future__ import annotations

from director_chat.engine.kernel import PERSON_ONLY, ScenePlanKernel
from director_chat.engine.turn import kernel_for

from contracts.producer import PersonEdits, apply_waivers, camera_checks, check_code, default_camera
from tests.services.director_chat.conftest import KAMALA, NIMAL, fixture_scene

SINHALA = "මම ඉක්මනින්ම මගේම අවන්හලක් විවෘත කරනවා"


def canon() -> list[dict]:
    return [{"id": KAMALA, "kind": "character", "code": "C01", "name": "Kamala", "aliases": ["Amma"]},
            {"id": NIMAL, "kind": "character", "code": "C02", "name": "Nimal", "aliases": []},
            {"id": "L01", "kind": "location", "code": "L01", "name": "Harbour kitchen", "aliases": []},
            {"id": "P01", "kind": "prop", "code": "P01", "name": "Brass pan", "aliases": []}]


def kernel(n: int = 0, **kw) -> ScenePlanKernel:
    scene, lines, shots = fixture_scene(n, **kw)
    return kernel_for(scene, lines, shots, None, canon())


def you(k: ScenePlanKernel, *ops: dict):
    return k.apply(list(ops), by="you", respect_locks=False)


def dialogue_block(k: ScenePlanKernel, speaker: str = "Nimal") -> int:
    return next(i for i, b in enumerate(k.items) if b["kind"] == "dialogue" and b["speaker"] == speaker)


# ── the script ─────────────────────────────────────────────────────────────────────────────


def test_a_line_is_changed_verbatim_in_nfc_and_keeps_its_id_and_binding():
    k = kernel()
    b = dialogue_block(k)
    line_id, shot_before = k.items[b]["line_id"], k._shot_of_block(b)
    r = you(k, {"op": "block.set", "block": b, "field": "text", "value": f"  {SINHALA}‍  "})
    assert r.applied and not r.rejected
    assert k.items[b]["text"] == SINHALA + "‍"  # trimmed, ZWJ kept, nothing else touched
    assert k.items[b]["line_id"] == line_id and k._shot_of_block(b) == shot_before
    assert r.applied[0]["was"] and r.applied[0]["shot"] == shot_before + 1
    assert k.script_changed


def test_a_speaker_change_follows_the_canon_and_an_unknown_name_is_unmatched():
    k = kernel()
    b = dialogue_block(k)
    assert you(k, {"op": "block.set", "block": b, "field": "speaker", "value": "amma"}).applied
    assert k.items[b]["speaker_id"] == KAMALA  # an alias, any case
    assert you(k, {"op": "block.set", "block": b, "field": "speaker", "value": "Kasun"}).applied
    assert k.items[b]["speaker_id"] is None


def test_block_set_refuses_what_it_cannot_do():
    k = kernel()
    b = dialogue_block(k)
    action = next(i for i, x in enumerate(k.items) if x["kind"] != "dialogue")
    reasons = [x["reason"] for x in you(
        k, {"op": "block.set", "block": 99, "value": "x"},
        {"op": "block.set", "block": b, "field": "text", "value": " "},
        {"op": "block.set", "block": b, "field": "mood", "value": "x"},
        {"op": "block.set", "block": action, "field": "speaker", "value": "x"},
        {"op": "block.set", "block": b, "field": "text", "value": k.items[b]["text"]},
        {"op": "block.set", "block": b, "field": "text", "value": "x" * 2001}).rejected]
    assert [r.split(";")[0] for r in reasons] == [
        "there is no block 99", "say what the text should be", "a line has text, speaker and delivery",
        "only a line has a speaker or a delivery", f"block {b} already says that",
        "text can be at most 2000 characters"]
    assert not k.script_changed


def test_blocks_are_named_by_their_numbers_at_the_start_of_the_batch():
    k = kernel()
    n = len(k.items)
    texts = [x["text"] for x in k.items]
    r = you(k, {"op": "block.insert", "block": 1, "kind": "action", "value": "A bell rings"},
            {"op": "block.set", "block": 1, "field": "text", "value": "edited original block 1"},
            {"op": "block.remove", "block": 0})
    assert len(r.applied) == 3 and not r.rejected
    assert [x["text"] for x in k.items][:2] == ["A bell rings", "edited original block 1"] and len(k.items) == n
    assert texts[0] not in [x["text"] for x in k.items] and k.items[0]["text"] != texts[1]
    # a block removed earlier in the batch cannot be named again
    again = you(k, {"op": "block.remove", "block": 0}, {"op": "block.remove", "block": 0})
    assert len(again.applied) == 1 and "removed earlier" in again.rejected[0]["reason"]


def test_inserting_and_removing_blocks_keeps_every_block_in_exactly_one_shot():
    k = kernel()
    shots = len(k.shots)
    ranges = lambda: [(s["start"], s["end"]) for s in k.shots]  # noqa: E731
    assert you(k, {"op": "block.insert", "block": 0, "kind": "sound", "value": "Waves"}).applied
    assert ranges()[0] == (0, 2) and ranges()[-1][1] == len(k.items) and len(k.shots) == shots
    assert you(k, {"op": "block.insert", "block": len(k.items), "kind": "action", "value": "Fade out"}).applied
    assert ranges()[-1][1] == len(k.items)
    assert all(a[1] == b[0] for a, b in zip(ranges(), ranges()[1:], strict=False))
    assert you(k, {"op": "block.remove", "block": 0}).applied and ranges()[0][0] == 0
    # a shot that held only that block goes with it
    only = next(i for i, s in enumerate(k.shots) if s["end"] - s["start"] == 1)
    before = len(k.shots)
    assert you(k, {"op": "block.remove", "block": k.shots[only]["start"]}).applied
    assert len(k.shots) == before - 1 and ranges()[-1][1] == len(k.items)
    one = kernel(per_block=False)
    while len(one.items) > 1:
        assert you(one, {"op": "block.remove", "block": 0}).applied
    assert "at least one block" in you(one, {"op": "block.remove", "block": 0}).rejected[0]["reason"]


def test_a_new_line_gets_an_id_a_speaker_and_a_delivery():
    k = kernel()
    r = you(k, {"op": "block.insert", "block": 1, "kind": "dialogue", "value": SINHALA, "speaker": "Nimal",
                "delivery": "softly"})
    assert r.applied
    line = k.items[1]
    assert line["kind"] == "dialogue" and line["line_id"] and line["speaker_id"] == NIMAL
    assert line["text"] == SINHALA and line["delivery"] == "softly"
    assert k.touches_dialogue({"op": "block.insert", "block": 1, "kind": "dialogue"})
    assert you(k, {"op": "block.insert", "block": 1, "kind": "dialogue", "value": "x"}).rejected  # no speaker
    assert you(k, {"op": "block.insert", "block": 1, "kind": "action", "value": "x", "speaker": "Nimal"}).rejected
    assert you(k, {"op": "block.insert", "block": 1, "kind": "poem", "value": "x"}).rejected


def test_touches_dialogue_tells_lines_from_the_rest_of_the_script():
    k = kernel()
    b = dialogue_block(k)
    action = next(i for i, x in enumerate(k.items) if x["kind"] != "dialogue")
    assert k.touches_dialogue({"op": "block.set", "block": b})
    assert k.touches_dialogue({"op": "block.remove", "block": b})
    assert not k.touches_dialogue({"op": "block.set", "block": action})
    assert not k.touches_dialogue({"op": "retime", "shot": 1})
    assert not k.touches_dialogue({"op": "block.set", "block": "x"})


def test_script_changes_fit_the_scene_and_report_a_line_that_no_longer_fits():
    k = kernel()
    b = dialogue_block(k)
    before = k.fit()
    assert you(k, {"op": "block.set", "block": b, "field": "text", "value": " ".join(["word"] * 40)}).applied
    after = k.fit()
    assert any(i.code in ("line_overrun", "word_budget", "long_line") for i in after.issues) or \
        after.total_s > before.total_s
    assert k.items[b]["text"] == " ".join(["word"] * 40)  # reported, never trimmed


def test_undo_restores_the_script_exactly():
    k = kernel()
    snapshot = ([dict(i) for i in k.items], [dict(s) for s in k.shots])
    r = you(k, {"op": "block.insert", "block": 0, "kind": "action", "value": "x"},
            {"op": "block.remove", "block": 2}, {"op": "canon.add", "shot": 1, "value": "Brass pan"})
    assert len(r.applied) == 3
    k.undo(r)
    assert ([dict(i) for i in k.items], [dict(s) for s in k.shots]) == snapshot and not k.script_changed


# ── only a person ──────────────────────────────────────────────────────────────────────────


def test_an_agent_cannot_use_any_person_only_operation():
    k = kernel()
    b = dialogue_block(k)
    ops = [{"op": "block.set", "block": b, "field": "text", "value": "x"},
           {"op": "block.insert", "block": 0, "kind": "action", "value": "x"}, {"op": "block.remove", "block": 0},
           {"op": "canon.add", "shot": 1, "value": "Brass pan"}, {"op": "canon.remove", "shot": 1, "value": "x"},
           {"op": "check.waive", "shot": 1, "value": "axis"}, {"op": "check.restore", "shot": 1, "value": "axis"},
           {"op": "dop_note.set", "shot": 1, "value": "x"}]
    assert {o["op"] for o in ops} == set(PERSON_ONLY)
    for by in ("conductor", "timing", "continuity", "cinematography"):
        r = k.apply(ops, by=by, respect_locks=False)
        assert not r.applied and len(r.rejected) == len(ops)
        assert all("only a person's own words" in x["reason"] for x in r.rejected)
    legacy = you(k, {"op": "line.edit", "line": 1, "text": "x"})
    assert "name the line" in legacy.rejected[0]["reason"]


# ── canon chips ────────────────────────────────────────────────────────────────────────────


def test_a_shot_names_who_the_script_puts_in_it_and_a_person_can_add_and_take_out():
    k = kernel()
    first = k.shots[0]
    natural = k._present(first)
    assert KAMALA in natural or NIMAL in natural or natural == set()
    assert you(k, {"op": "canon.add", "shot": 1, "value": "Brass pan"}).applied
    assert "P01" in k._present(k.shots[0])
    assert PersonEdits.of(k.shots[0]).cast.add == ["P01"]
    assert "is already in S01" in you(k, {"op": "canon.add", "shot": 1, "value": "p01"}).rejected[0]["reason"]
    assert you(k, {"op": "canon.remove", "shot": 1, "value": "Brass pan"}).applied
    assert PersonEdits.of(k.shots[0]).cast.add == [] and k.shots[0]["person_edits"] == {}
    assert "no canon entry called 'Dragon'" in you(k, {"op": "canon.add", "shot": 1, "value": "Dragon"}).rejected[0][
        "reason"]


def test_a_person_can_take_the_scene_place_or_a_named_person_out_of_one_shot_only():
    k = kernel()
    sid = k.location_id
    k.canon.append({"id": sid, "kind": "location", "code": "L09", "name": "Old jetty", "aliases": []})
    assert sid in k._present(k.shots[0])
    assert you(k, {"op": "canon.remove", "shot": 1, "value": "Old jetty"}).applied
    assert sid not in k._present(k.shots[0]) and sid in k._present(k.shots[1])
    assert you(k, {"op": "canon.add", "shot": 1, "value": "L09"}).applied  # back again: nothing stored
    assert k.shots[0]["person_edits"] == {}
    speaker = next(i for i, s in enumerate(k.shots, start=1) if NIMAL in k._present(s))
    assert you(k, {"op": "canon.remove", "shot": speaker, "value": "Nimal"}).applied
    assert NIMAL not in k._present(k.shots[speaker - 1])
    assert "not in" in you(k, {"op": "canon.remove", "shot": speaker, "value": "Nimal"}).rejected[0]["reason"]


def test_a_split_shot_keeps_who_is_in_it_but_not_the_note_or_ignored_checks():
    k = kernel(per_block=False)
    assert you(k, {"op": "canon.add", "shot": 1, "value": "Brass pan"}, {"op": "dop_note.set", "shot": 1,
                                                                         "value": "warm"},
               {"op": "check.waive", "shot": 1, "value": "axis"}).applied
    assert you(k, {"op": "split", "shot": 1, "at_block": 2}).applied
    second = PersonEdits.of(k.shots[1])
    assert second.cast.add == ["P01"] and second.dop_note == "" and second.waived_checks == []
    assert PersonEdits.of(k.shots[0]).dop_note == "warm"


# ── checks and the DoP note ────────────────────────────────────────────────────────────────


def test_checks_are_ignored_by_topic_and_shown_again():
    k = kernel()
    assert you(k, {"op": "check.waive", "shot": 2, "value": "the axis warning"}).applied
    assert PersonEdits.of(k.shots[1]).waived_checks == ["axis"]
    assert "already ignored" in you(k, {"op": "check.waive", "shot": 2, "value": "axis"}).rejected[0]["reason"]
    unknown = you(k, {"op": "check.waive", "shot": 2, "value": "the weather"})
    assert "named by its topic" in unknown.rejected[0]["reason"]
    assert you(k, {"op": "check.waive", "shot": 2, "value": "speaker is hard to see"}).applied
    assert PersonEdits.of(k.shots[1]).waived_checks == ["axis", "speaker_size"]
    assert you(k, {"op": "check.restore", "shot": 2, "value": "axis"}).applied
    assert "not ignored" in you(k, {"op": "check.restore", "shot": 2, "value": "axis"}).rejected[0]["reason"]
    assert you(k, {"op": "check.restore", "shot": 2, "value": "all"}).applied and k.shots[1]["person_edits"] == {}


def test_check_topics_and_waivers():
    assert check_code("The 180 rule") == "axis" and check_code("wardrobe_anchor") == "wardrobe"
    assert check_code("voice pin") == "voice_pin" and check_code("speaker_size") == "speaker_size"
    assert check_code("lunch") is None
    cams = [default_camera("WIDE"), default_camera("CU")]
    cams[1] = cams[1].model_copy(update={"axis": "Side B · right to left"})
    checks = camera_checks(index=1, cameras=cams, framing="WIDE", sound_mode="dialogue", cast=[], speaker_ids=[],
                           frame_strategy="generate")
    shown = apply_waivers(checks, ["axis", "speaker_size"])
    assert [(c.code, c.tone, c.waived) for c in shown] == [("axis", "advisory", True),
                                                          ("speaker_size", "advisory", True)]
    passing = camera_checks(index=0, cameras=cams, framing="MS", sound_mode="dialogue", cast=[], speaker_ids=[],
                            frame_strategy="generate")
    assert not any(c.waived for c in apply_waivers(passing, ["axis"]))  # a passing check has nothing to ignore


def test_the_dop_note_is_set_cleared_and_capped():
    k = kernel()
    assert you(k, {"op": "dop_note.set", "shot": 1, "value": "  Hold on the pan,\n warm light "}).applied
    assert PersonEdits.of(k.shots[0]).dop_note == "Hold on the pan, warm light"
    assert "already has that DoP note" in you(k, {"op": "dop_note.set", "shot": 1,
                                                  "value": "Hold on the pan, warm light"}).rejected[0]["reason"]
    assert you(k, {"op": "dop_note.set", "shot": 1, "value": "x" * 900}).applied
    assert len(PersonEdits.of(k.shots[0]).dop_note) == 600
    assert you(k, {"op": "dop_note.set", "shot": 1}).applied and k.shots[0]["person_edits"] == {}
    assert "no DoP note to clear" in you(k, {"op": "dop_note.set", "shot": 1}).rejected[0]["reason"]
    assert "there is no shot 9" in you(k, {"op": "dop_note.set", "shot": 9, "value": "x"}).rejected[0]["reason"]


def test_the_model_reads_blocks_by_number_and_what_a_person_set():
    k = kernel()
    you(k, {"op": "dop_note.set", "shot": 1, "value": "Hold the wide"},
        {"op": "check.waive", "shot": 1, "value": "axis"})
    text = k.describe()
    assert "[0]" in text and f"[{len(k.items) - 1}]" in text
    assert "DoP note: Hold the wide" in text and "ignored checks: axis" in text
