"""Phase 1 (plan/2026-11-05e §10): the checks and the mend, on hand-written plans.

The phone call planned the way a good director would passes every check; each mutant of it fails with the right sentence
and the right owner (`fix`); the mend never deletes a shot or trims a line.
"""
from __future__ import annotations

from typing import Any

import pytest

from contracts.david import checks, mend
from contracts.david.plan import Problem
from contracts.david.scene import BlockS, SceneS
from contracts.david.wire import DavidWire
from tests.david import gold


def mutated(**changes: Any) -> DavidWire:
    return DavidWire.model_validate({**gold.phone_call().model_dump(), **changes})


def shots(plan: DavidWire, edit: Any) -> DavidWire:
    """The plan with every shot (as a dict) passed through `edit(dict) -> dict | None`; None drops the shot."""
    out = []
    for s in plan.shots:
        made = edit(s.model_dump())
        if made is not None:
            out.append(made)
    return DavidWire.model_validate({**plan.model_dump(), "shots": out})


def found(plan: DavidWire, scene: SceneS | None = None) -> list[Problem]:
    return checks.problems(scene or gold.scene(), plan)


def only(plan: DavidWire, code: str, scene: SceneS | None = None) -> list[Problem]:
    return [p for p in found(plan, scene) if p.code == code]


def test_the_phone_call_planned_by_hand_passes_every_check_and_the_mend_changes_nothing():
    plan = gold.phone_call()
    assert found(plan) == []
    mended, done, dropped = mend.mend(gold.scene(), plan)
    assert mended == plan and done == [] and dropped == []


# ── lines and blocks ─────────────────────────────────────────────────────────────────────────────


def test_a_dropped_line_is_named_with_its_speaker_and_length():
    plan = shots(gold.phone_call(), lambda s: None if s["n"] == 2 else s)
    lines = only(plan, "lines")
    assert any(p.key == "lines:missing:L1" and "Dasun" in p.sentence and "words" in p.sentence for p in lines)
    assert all(p.fix == "repair" for p in lines)
    assert any(p.code == "blocks" and "b1" in p.sentence for p in found(plan))  # and its block is shown by no shot


def test_a_line_used_twice_names_both_shots():
    plan = shots(gold.phone_call(), lambda s: {**s, "lines": ["L1"]} if s["n"] in (2, 4) else s)
    assert any(p.key == "lines:twice:L1" and "S02" in p.sentence and "S04" in p.sentence for p in only(plan, "lines"))


def test_a_line_the_scene_does_not_have_and_lines_out_of_order_are_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "lines": ["L99"]} if s["n"] == 2 else s)
    assert any(p.key == "lines:unknown:L99" for p in only(plan, "lines"))
    swapped = shots(gold.phone_call(), lambda s: {**s, "lines": ["L8"]} if s["n"] == 6 else (
        {**s, "lines": ["L6"]} if s["n"] == 8 else s))
    assert any(p.key == "lines:order" for p in only(swapped, "lines"))


def test_a_line_whose_block_the_shot_does_not_show_is_named():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [5]} if s["n"] == 6 else s)
    assert any("does not show its block b6" in p.sentence for p in only(plan, "lines"))


def test_a_block_shown_by_no_shot_and_shots_out_of_order_are_found():
    gone = shots(gold.phone_call(), lambda s: None if s["n"] == 9 else s)
    assert any(p.key == "blocks:missing:9" for p in only(gone, "blocks"))
    swapped = shots(gold.phone_call(), lambda s: {**s, "blocks": [7]} if s["n"] == 4 else (
        {**s, "blocks": [3]} if s["n"] == 7 else s))
    assert any(p.code == "blocks" and "script order" in p.sentence for p in found(swapped))


def test_a_shot_that_shows_blocks_that_do_not_follow_each_other_is_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [5, 7]} if s["n"] == 6 else s)
    assert any(p.key == "blocks:run:6" for p in only(plan, "blocks"))


def test_a_dialogue_block_in_two_shots_is_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [0, 1]} if s["n"] == 1 else s)
    assert any(p.key == "blocks:dialogue:1" for p in only(plan, "blocks"))


def test_a_line_played_over_its_own_speaker_or_over_a_stranger_is_refused():
    own = shots(gold.phone_call(), lambda s: {**s, "over": "Father"} if s["n"] == 5 else s)
    assert any(p.key == "lines:listener:5" for p in only(own, "lines"))
    stranger = shots(gold.phone_call(), lambda s: {**s, "over": "Nimali"} if s["n"] == 5 else s)
    assert any(p.key == "lines:listener:5" for p in only(stranger, "lines"))


# ── the clock ────────────────────────────────────────────────────────────────────────────────────


def long_scene(count: int = 15, screen: str = "info") -> SceneS:
    words = " ".join(f"word{n}" for n in range(count))
    return SceneS(blocks=[BlockS(index=0, kind="action", text="A cell. NIMAL sits.", screen=screen),
                          BlockS(index=1, kind="dialogue", speaker="Nimal", line_id="L1", text=words),
                          BlockS(index=2, kind="action", text="He looks up.")], cast=["Nimal"])


def long_plan(take: int) -> DavidWire:
    return DavidWire.model_validate({
        "notes": "n", "shots": [gold.shot(1, [0, 1], "MS", take, "He says it all.", lines=["L1"]),
                                gold.shot(2, [2], "CU", 4, "He looks up.")],
        "added": [], "staging": {"zones": [], "marks": []},
        "end_state": {"people": [{"who": "Nimal", "where": "cell", "facing": "", "holding": "", "look": ""}],
                      "props": [], "time": "", "light": ""}})


def test_a_15_word_line_in_a_6_second_take_is_mended_to_the_take_that_holds_it():
    scene, plan = long_scene(), long_plan(6)
    clock = [p for p in checks.problems(scene, plan) if p.code == "clock"]
    assert len(clock) == 1 and clock[0].fix == "mend" and "S01 needs" in clock[0].sentence
    mended, done, _ = mend.mend(scene, plan)
    assert mended.shots[0].take_s == 8 and any("8 s take" in d for d in done)
    assert mended.shots[0].lines == ["L1"] and [p for p in checks.problems(scene, mended) if p.code == "clock"] == []


def test_a_19_word_line_cannot_fit_any_take_so_it_is_cut_from_the_action_and_then_reported_never_trimmed():
    scene, plan = long_scene(19, "act"), long_plan(8)  # 8.6 s to say, plus a lead-in and a tail: longer than 8 s
    mended, done, _ = mend.mend(scene, plan)
    line_shot = next(s for s in mended.shots if s.lines == ["L1"])
    assert line_shot.blocks == [1] and any("split into" in d for d in done)
    left = [p for p in checks.problems(scene, mended) if p.code == "clock"]
    assert [p.fix for p in left] == ["report"] and left[0].shots == [line_shot.n]


def test_a_crowded_shot_is_split_at_a_block_boundary_and_no_line_is_cut_or_trimmed():
    scene = SceneS(blocks=[BlockS(index=0, kind="action", text="Rain. NIMAL sits.", screen="move", events=2),
                           BlockS(index=1, kind="dialogue", speaker="Nimal", line_id="L1", text="one two three four"),
                           BlockS(index=2, kind="action", text="He stands.", screen="move", events=2),
                           BlockS(index=3, kind="dialogue", speaker="Nimal", line_id="L3", text="five six seven")],
                   cast=["Nimal"])
    plan = DavidWire.model_validate({
        "notes": "n", "shots": [gold.shot(1, [0, 1, 2, 3], "MS", 8, "One long take.", lines=["L1", "L3"])],
        "added": [], "staging": {"zones": [], "marks": []},
        "end_state": {"people": [{"who": "Nimal", "where": "here", "facing": "", "holding": "", "look": ""}],
                      "props": [], "time": "", "light": ""}})
    assert [p.fix for p in checks.problems(scene, plan) if p.code == "clock"] == ["mend"]
    mended, done, _ = mend.mend(scene, plan)
    assert len(mended.shots) > 1 and any("split into" in d for d in done)
    assert [s.n for s in mended.shots] == list(range(1, len(mended.shots) + 1))
    assert sorted(b for s in mended.shots for b in s.blocks) == [0, 1, 2, 3]  # every block still shown, once
    assert [ln for s in mended.shots for ln in s.lines] == ["L1", "L3"]  # every line kept whole, in order
    assert [p for p in checks.problems(scene, mended) if p.code in ("clock", "lines", "blocks")] == []


def test_a_line_longer_than_the_longest_take_is_reported_never_trimmed_or_split():
    words = " ".join(f"w{n}" for n in range(40))
    scene = SceneS(blocks=[BlockS(index=0, kind="dialogue", speaker="Nimal", line_id="L0", text=words)], cast=["Nimal"])
    plan = DavidWire.model_validate({
        "notes": "n", "shots": [gold.shot(1, [0], "MS", 8, "He says it.", lines=["L0"])], "added": [],
        "staging": {"zones": [], "marks": []},
        "end_state": {"people": [{"who": "Nimal", "where": "here", "facing": "", "holding": "", "look": ""}],
                      "props": [], "time": "", "light": ""}})
    assert [p.fix for p in checks.problems(scene, plan) if p.code == "clock"] == ["report"]
    mended, _, _ = mend.mend(scene, plan)
    assert mended.shots == plan.shots


def test_a_scene_over_its_envelope_is_not_squeezed():
    # the envelope is the episode's room for the scene; code reports and never trims (CLAUDE.md)
    scene = gold.scene().model_copy(update={"envelope_s": 20})
    plan = gold.phone_call()
    mended, _, _ = mend.mend(scene, plan)
    assert mended == plan and sum(s.take_s for s in plan.shots) > 20


# ── additions ────────────────────────────────────────────────────────────────────────────────────


def with_added(plan: DavidWire, **fields: Any) -> DavidWire:
    base = {"shot": 10, "kind": "reaction", "what": "a stranger looks on", "who": ["Dasun"], "object": ""}
    return DavidWire.model_validate({**plan.model_dump(), "added": [{**base, **fields}]})


def test_an_addition_that_shows_someone_not_in_the_scene_is_dropped_by_code_with_its_shot():
    plan = with_added(gold.phone_call(), who=["Waiter"])
    drops = only(plan, "added")
    assert len(drops) == 1 and drops[0].fix == "drop" and "Waiter" in drops[0].sentence
    mended, _, dropped = mend.mend(gold.scene(), plan)
    assert len(dropped) == 1 and len(mended.shots) == 9 and mended.added == []  # an added shot has no script: it goes
    assert [ln for s in mended.shots for ln in s.lines] == ["L1", "L4", "L6", "L8"]  # the script is untouched


def test_an_insert_must_show_an_object_the_script_or_the_place_has():
    base = with_added(gold.phone_call(), kind="insert_detail", who=[], object="a gun")
    assert any("a gun" in p.sentence and p.fix == "drop" for p in only(base, "added"))
    fine = with_added(gold.phone_call(), kind="insert_detail", who=[], object="bench")
    assert only(fine, "added") == []


def test_a_shot_that_shows_no_script_and_is_not_listed_as_an_addition_is_sent_back():
    plan = mutated(added=[])
    assert any(p.key == "added:unlisted:10" and p.fix == "repair" for p in only(plan, "added"))


def test_an_addition_a_person_removed_before_never_comes_back():
    plan, scene = gold.phone_call(), gold.scene()
    removed = [("reaction", 9)]  # the reaction after block 9
    assert checks.problems(scene, plan) == []
    assert [p.fix for p in checks.problems(scene, plan, removed)] == ["drop"]
    mended, _, dropped = mend.mend(scene, plan, removed)
    assert len(mended.shots) == 9 and len(dropped) == 1


# ── names, speech, heard-not-seen, feasibility ───────────────────────────────────────────────────


def test_an_invented_person_in_free_text_is_named():
    plan = shots(gold.phone_call(), lambda s: {**s, "why": "Kasun walks in behind them."} if s["n"] == 1 else s)
    names = only(plan, "names")
    assert len(names) == 1 and names[0].shots == [1] and "Kasun" in names[0].sentence and names[0].fix == "repair"


def test_speech_in_free_text_is_removed_by_the_mend_and_the_words_never_reach_a_shot_description():
    said = "ඉතින් මම කිව්වා, ඕක බොරු!"
    plan = shots(gold.phone_call(), lambda s: {**s, "why": f"Dasun says \"{said}\" and laughs"} if s["n"] == 2 else s)
    assert [p.fix for p in only(plan, "speech")] == ["mend"]
    mended, done, _ = mend.mend(gold.scene(), plan)
    why = mended.shots[1].why
    assert said not in why and "laughs" in why and any("speech removed" in d for d in done)
    assert only(mended, "speech") == []


def test_the_caller_in_frame_is_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(subjects=[
        {"id": "", "description": "Father in a grey shirt", "action": "speaks", "position": ""}])}
        if s["n"] == 5 else s)
    heard = only(plan, "heard")
    assert len(heard) == 1 and heard[0].shots == [5] and "Father" in heard[0].sentence


def test_what_veo_does_badly_is_reported_with_the_known_way_round():
    plan = shots(gold.phone_call(), lambda s: {**s, "why": "The screen shows the message: a long text."}
                 if s["n"] == 3 else s)
    report = only(plan, "feasibility")
    assert len(report) == 1 and report[0].fix == "report" and "glow" in report[0].sentence


# ── staging and the end state ────────────────────────────────────────────────────────────────────


def test_a_teleport_is_found_with_a_sentence_that_names_the_blocks():
    plan = gold.phone_call()
    marks = [m.model_dump() for m in plan.staging.marks]
    marks[-1] = {**marks[-1], "zone": "path"}  # she is on the bench at block 7 and on the path at block 9
    moved = DavidWire.model_validate({**plan.model_dump(), "staging": {"zones": plan.staging.zones, "marks": marks}})
    found_ = only(moved, "staging")
    assert len(found_) == 1 and found_[0].fix == "repair" and "block 9" in found_[0].sentence


def test_a_staging_the_scene_cannot_check_is_reported_not_failed():
    plan = DavidWire.model_validate({**gold.phone_call().model_dump(), "staging": {"zones": [], "marks": []}})
    assert [p.fix for p in only(plan, "staging")] == ["report"]


def test_an_end_state_that_names_a_stranger_or_loses_a_prop_is_sent_back():
    plan = gold.phone_call()
    ends = plan.end_state.model_dump()
    ends["people"][0]["holding"] = ""  # Anudi holds her bag at the last mark; the end state loses it
    ends["people"].append({"who": "Waiter", "where": "door", "facing": "", "holding": "", "look": ""})
    del ends["people"][2]  # and Father is not accounted for
    bad = DavidWire.model_validate({**plan.model_dump(), "end_state": ends})
    sentences = " ".join(p.sentence for p in only(bad, "end_state"))
    assert "Waiter" in sentences and "her bag" in sentences and "Father" in sentences


def test_the_end_state_must_agree_with_where_the_staging_leaves_a_person():
    plan = gold.phone_call()
    ends = plan.end_state.model_dump()
    ends["people"][1]["where"] = "the kitchen"  # Dasun's last mark is the right end of the bench
    bad = DavidWire.model_validate({**plan.model_dump(), "end_state": ends})
    assert any("Dasun" in p.sentence and "kitchen" in p.sentence for p in only(bad, "end_state"))


# ── the mend never deletes ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["phone_call", "arrival", "father_refuses", "refuses_money", "silent_morning"])
def test_whatever_the_mend_does_a_gold_scene_keeps_every_block_and_every_line(name: str):
    scene = gold.scene(name, others=())
    items = scene.items()
    blocks = [b.index for b in scene.blocks]
    lines = [b.line_id for b in sorted(scene.lines, key=lambda b: b.index)]
    one_take = DavidWire.model_validate({
        "notes": "n", "shots": [gold.shot(1, blocks, "WIDE", 8, "all of it", lines=[x for x in lines if x])],
        "added": [], "staging": {"zones": [], "marks": []},
        "end_state": {"people": [{"who": c, "where": "here", "facing": "", "holding": "", "look": ""}
                                 for c in scene.cast], "props": [], "time": "", "light": ""}})
    mended, _, _ = mend.mend(scene, one_take)
    assert sorted(b for s in mended.shots for b in s.blocks) == blocks and len(items) == len(blocks)
    assert [ln for s in mended.shots for ln in s.lines] == lines
    assert [p for p in checks.problems(scene, mended) if p.code in ("lines", "blocks", "clock")
            and p.fix != "report"] == []
