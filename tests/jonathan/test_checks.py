"""Phase 1 (plan/2026-11-06b §5, §7): the checks, the craft measures and the mend, on hand-written plans.

The phone call planned the way a good team would passes every check and meets every craft measure; each mutant of it
fails with the right sentence and the right owner (`fix`); the mend never deletes a shot or trims a line, and a split
shot keeps only its own beats (the lab's finding F8).
"""
from __future__ import annotations

from typing import Any

import pytest

from contracts.jonathan import checks, measures, mend
from contracts.jonathan.plan import Problem
from contracts.jonathan.scene import BlockS, SceneS
from contracts.jonathan.wire import JonathanWire
from tests.jonathan import gold


def mutated(**changes: Any) -> JonathanWire:
    return JonathanWire.model_validate({**gold.phone_call().model_dump(), **changes})


def shots(plan: JonathanWire, edit: Any) -> JonathanWire:
    """The plan with every shot (as a dict) passed through `edit(dict) -> dict | None`; None drops the shot."""
    out = []
    for s in plan.shots:
        made = edit(s.model_dump())
        if made is not None:
            out.append(made)
    return JonathanWire.model_validate({**plan.model_dump(), "shots": out})


def found(plan: JonathanWire, scene: SceneS | None = None) -> list[Problem]:
    return checks.problems(scene or gold.scene(), plan)


def only(plan: JonathanWire, code: str, scene: SceneS | None = None) -> list[Problem]:
    return [p for p in found(plan, scene) if p.code == code]


def measured(plan: JonathanWire) -> dict[str, measures.Measure]:
    return {m.key: m for m in measures.measures(gold.scene(), plan, gold.CRAFT)}


def bare(shot_list: list[dict[str, Any]], cast: list[str]) -> JonathanWire:
    """A plan of these shots in one sequence, with the least treatment the checks accept."""
    for s in shot_list:
        s["sequence"] = "A"
    return JonathanWire.model_validate({
        "treatment": {**gold.treatment(), "arc": [{"beat": "all", "blocks": {"first": 0, "last": 9}, "feeling": "x"}],
                      "colour_script": [{"sequence": "A", "palette": "p", "light": "l", "grade": "g"}]},
        "sequences": [{"id": "A", "title": "All", "purpose": "all", "shots": {"first": 1, "last": len(shot_list)}}],
        "shots": shot_list, "added": [], "staging": {"zones": [], "marks": []},
        "end_state": {"people": [{"who": c, "where": "here", "facing": "", "holding": "", "look": ""} for c in cast],
                      "props": [], "time": "", "light": ""}})


def test_the_phone_call_planned_by_hand_passes_every_check_meets_every_measure_and_the_mend_changes_nothing():
    plan = gold.phone_call()
    assert found(plan) == []
    assert measures.missed(measures.measures(gold.scene(), plan, gold.CRAFT)) == []
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
    swapped = shots(gold.phone_call(), lambda s: {**s, "lines": ["L8"]} if s["n"] == 8 else (
        {**s, "lines": ["L6"]} if s["n"] == 12 else s))
    assert any(p.key == "lines:order" for p in only(swapped, "lines"))


def test_a_line_whose_block_the_shot_does_not_show_is_named():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [5]} if s["n"] == 8 else s)
    assert any("does not show its block b6" in p.sentence for p in only(plan, "lines"))


def test_a_block_shown_by_no_shot_and_shots_out_of_order_are_found():
    gone = shots(gold.phone_call(), lambda s: None if s["n"] == 4 else s)
    assert any(p.key == "blocks:missing:2" for p in only(gone, "blocks"))
    swapped = shots(gold.phone_call(), lambda s: {**s, "blocks": [7]} if s["n"] == 4 else (
        {**s, "blocks": [2]} if s["n"] == 10 else s))
    assert any(p.code == "blocks" and "script order" in p.sentence for p in found(swapped))


def test_a_shot_that_shows_blocks_that_do_not_follow_each_other_is_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [5, 7]} if s["n"] == 8 else s)
    assert any(p.key == "blocks:run:8" for p in only(plan, "blocks"))


def test_a_dialogue_block_in_two_shots_is_found():
    plan = shots(gold.phone_call(), lambda s: {**s, "blocks": [0, 1]} if s["n"] == 1 else s)
    assert any(p.key == "blocks:dialogue:1" for p in only(plan, "blocks"))


def test_a_line_played_over_its_own_speaker_or_over_a_stranger_is_refused():
    own = shots(gold.phone_call(), lambda s: {**s, "over": "Father"} if s["n"] == 7 else s)
    assert any(p.key == "lines:listener:7" for p in only(own, "lines"))
    stranger = shots(gold.phone_call(), lambda s: {**s, "over": "Nimali"} if s["n"] == 7 else s)
    assert any(p.key == "lines:listener:7" for p in only(stranger, "lines"))


# ── the cinematic lab's own hard checks ──────────────────────────────────────────────────────────


def test_nobody_speaks_in_a_shot_with_no_line():
    plan = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(action="She says something to him.")}
                 if s["n"] == 3 else s)
    speaks = only(plan, "speaks")
    assert [p.key for p in speaks] == ["speaks:3"] and speaks[0].fix == "repair" and "Say what they DO" in \
        speaks[0].sentence
    answers = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(action="She answers the phone.")}
                    if s["n"] == 5 else s)
    assert only(answers, "speaks") == []  # answering a phone is an act, not speech


def test_the_seconds_the_edit_keeps_are_two_to_the_take_and_never_less_than_a_line_needs():
    plan = shots(gold.phone_call(), lambda s: {**s, "use_s": 9} if s["n"] == 1 else (
        {**s, "use_s": 2} if s["n"] == 7 else s))
    keys = {p.key for p in only(plan, "use")}
    assert keys == {"use:range:1", "use:line:7"}
    mended, done, _ = mend.mend(gold.scene(), plan)
    assert mended.shots[6].use_s == 5 and any("a line is kept whole" in d for d in done)  # the father's line: 4.x s
    assert mended.shots[0].use_s == 4 and only(mended, "use") == []  # never more than the take


def test_every_shot_is_in_a_sequence_and_the_colour_script_names_every_sequence():
    plan = shots(gold.phone_call(), lambda s: {**s, "sequence": "Z"} if s["n"] == 2 else s)
    assert any(p.key == "sequence:unknown:2" for p in only(plan, "sequence"))
    data = gold.phone_call().model_dump()
    data["treatment"]["colour_script"] = data["treatment"]["colour_script"][:2]
    assert [p.key for p in found(JonathanWire.model_validate(data))] == ["colour:C"]


def test_a_sequence_span_that_does_not_match_its_shots_is_written_again_by_the_mend():
    data = gold.phone_call().model_dump()
    data["sequences"][1]["shots"] = {"first": 4, "last": 9}
    plan = JonathanWire.model_validate(data)
    assert [p.fix for p in only(plan, "sequence")] == ["mend"]
    mended, _, _ = mend.mend(gold.scene(), plan)
    assert mended == gold.phone_call()


# ── the clock ────────────────────────────────────────────────────────────────────────────────────


def long_scene(count: int = 15, screen: str = "info") -> SceneS:
    words = " ".join(f"word{n}" for n in range(count))
    return SceneS(blocks=[BlockS(index=0, kind="action", text="A cell. NIMAL sits.", screen=screen),
                          BlockS(index=1, kind="dialogue", speaker="Nimal", line_id="L1", text=words),
                          BlockS(index=2, kind="action", text="He looks up.")], cast=["Nimal"])


def long_plan(take: int) -> JonathanWire:
    return bare([gold.shot(1, "A", [0, 1], "MS", take, take, "He says it all.", lines=["L1"]),
                 gold.shot(2, "A", [2], "CU", 4, 4, "He looks up.")], ["Nimal"])


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


def crowded() -> tuple[SceneS, JonathanWire]:
    scene = SceneS(blocks=[BlockS(index=0, kind="action", text="Rain. NIMAL sits.", screen="move", events=2),
                           BlockS(index=1, kind="dialogue", speaker="Nimal", line_id="L1", text="one two three four"),
                           BlockS(index=2, kind="action", text="He stands.", screen="move", events=2),
                           BlockS(index=3, kind="dialogue", speaker="Nimal", line_id="L3", text="five six seven")],
                   cast=["Nimal"])
    beats = [{"time": "0-2s", "camera": "wide", "director_line": "Rain.", "action": "He sits in the rain.",
              "performance": "still"},
             {"time": "2-4s", "camera": "medium", "director_line": "He speaks.", "action": "He speaks to himself.",
              "performance": "low"},
             {"time": "4-6s", "camera": "medium", "director_line": "He stands.", "action": "He stands up.",
              "performance": "slow"},
             {"time": "6-8s", "camera": "close", "director_line": "He speaks.", "action": "He speaks again.",
              "performance": "firm"}]
    plan = bare([gold.shot(1, "A", [0, 1, 2, 3], "MS", 8, 8, "One long take.", lines=["L1", "L3"], beats=beats)],
                ["Nimal"])
    return scene, plan


def test_a_crowded_shot_is_split_at_a_block_boundary_and_no_line_is_cut_or_trimmed():
    scene, plan = crowded()
    assert [p.fix for p in checks.problems(scene, plan) if p.code == "clock"] == ["mend"]
    mended, done, _ = mend.mend(scene, plan)
    assert len(mended.shots) > 1 and any("split into" in d for d in done)
    assert [s.n for s in mended.shots] == list(range(1, len(mended.shots) + 1))
    assert sorted(b for s in mended.shots for b in s.blocks) == [0, 1, 2, 3]  # every block still shown, once
    assert [ln for s in mended.shots for ln in s.lines] == ["L1", "L3"]  # every line kept whole, in order
    assert [p for p in checks.problems(scene, mended) if p.code in ("clock", "lines", "blocks", "sequence")] == []


def test_a_split_shot_keeps_only_its_own_beats_retimed_and_a_part_with_no_line_is_silent():
    scene, plan = crowded()
    mended, _, _ = mend.mend(scene, plan)
    actions = [[b["action"] for b in s.ir["beats"]] for s in mended.shots]
    flat = [a for part in actions for a in part]
    assert len(flat) == len(set(flat)) == 4  # every beat once: none copied into two parts (finding F8)
    for s in mended.shots:
        assert s.ir["beats"][0]["time"].startswith("0-")  # each part is re-timed from 0
        assert s.ir["beats"][-1]["time"].endswith(f"-{s.take_s}s")
        if not s.lines:
            assert s.sound.silence and all("speaks" not in a for a in actions[s.n - 1])
        assert 2 <= s.use_s <= s.take_s


def test_a_line_longer_than_the_longest_take_is_reported_never_trimmed_or_split():
    words = " ".join(f"w{n}" for n in range(40))
    scene = SceneS(blocks=[BlockS(index=0, kind="dialogue", speaker="Nimal", line_id="L0", text=words)], cast=["Nimal"])
    plan = bare([gold.shot(1, "A", [0], "MS", 8, 8, "He says it.", lines=["L0"])], ["Nimal"])
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


def with_added(plan: JonathanWire, **fields: Any) -> JonathanWire:
    """The plan with its last addition (Dasun's reaction to the goodbye, shot 13) replaced by this one."""
    base = {"shot": 13, "kind": "reaction", "what": "a stranger looks on", "who": ["Dasun"], "object": ""}
    kept = [a.model_dump() for a in plan.added if a.shot != 13]
    return JonathanWire.model_validate({**plan.model_dump(), "added": [*kept, {**base, **fields}]})


def test_an_addition_that_shows_someone_not_in_the_scene_is_dropped_by_code_with_its_shot():
    plan = with_added(gold.phone_call(), who=["Waiter"])
    drops = only(plan, "added")
    assert len(drops) == 1 and drops[0].fix == "drop" and "Waiter" in drops[0].sentence
    mended, _, dropped = mend.mend(gold.scene(), plan)
    assert len(dropped) == 1 and len(mended.shots) == 14 and [a.shot for a in mended.added] == [3, 9]
    assert [ln for s in mended.shots for ln in s.lines] == ["L1", "L4", "L6", "L8"]  # the script is untouched
    assert mended.sequences[2].shots.last == 14  # the sequences follow


def test_an_insert_must_show_an_object_the_script_or_the_place_has():
    base = with_added(gold.phone_call(), kind="insert_detail", who=[], object="a gun")
    assert any("a gun" in p.sentence and p.fix == "drop" for p in only(base, "added"))
    fine = with_added(gold.phone_call(), kind="insert_detail", who=[], object="bench")
    assert only(fine, "added") == []


def test_a_shot_that_shows_no_script_and_is_not_listed_as_an_addition_is_sent_back():
    plan = mutated(added=[])
    keys = {p.key for p in only(plan, "added") if p.fix == "repair"}
    assert keys == {"added:unlisted:3", "added:unlisted:9", "added:unlisted:13"}


def test_an_addition_a_person_removed_before_never_comes_back():
    plan, scene = gold.phone_call(), gold.scene()
    removed = [("reaction", 8)]  # the reaction after block 8 (Dasun takes the goodbye)
    assert checks.problems(scene, plan) == []
    assert [p.fix for p in checks.problems(scene, plan, removed)] == ["drop"]
    mended, _, dropped = mend.mend(scene, plan, removed)
    assert len(mended.shots) == 14 and len(dropped) == 1


# ── names, speech, heard-not-seen, feasibility ───────────────────────────────────────────────────


def test_an_invented_person_in_free_text_is_named():
    plan = shots(gold.phone_call(), lambda s: {**s, "why": "Kasun walks in behind them."} if s["n"] == 1 else s)
    names = only(plan, "names")
    assert len(names) == 1 and names[0].shots == [1] and "Kasun" in names[0].sentence and names[0].fix == "repair"


def test_a_stranger_named_in_the_treatment_is_found():
    data = gold.phone_call().model_dump()
    data["treatment"]["key_image"] = "Kasun watching from the path."
    names = only(JonathanWire.model_validate(data), "names")
    assert len(names) == 1 and names[0].shots == [] and "The treatment names Kasun" in names[0].sentence


def test_speech_in_free_text_is_removed_by_the_mend_and_the_words_never_reach_a_shot_description():
    said = "ඉතින් මම කිව්වා, ඕක බොරු!"
    plan = shots(gold.phone_call(), lambda s: {**s, "why": f"Dasun says \"{said}\" and laughs"} if s["n"] == 2 else s)
    assert [p.fix for p in only(plan, "speech")] == ["mend"]
    mended, done, _ = mend.mend(gold.scene(), plan)
    why = mended.shots[1].why
    assert said not in why and "laughs" in why and any("speech removed" in d for d in done)
    assert only(mended, "speech") == []


def test_speech_in_the_treatment_is_removed_too():
    data = gold.phone_call().model_dump()
    data["treatment"]["logline"] = "He jokes: ඉතින් මම කිව්වා, ඕක බොරු!"
    mended, done, _ = mend.mend(gold.scene(), JonathanWire.model_validate(data))
    assert "ඉතින්" not in mended.treatment.logline and "the treatment: speech removed" in done


def test_the_caller_in_frame_is_found_once():
    plan = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(subjects=[
        {"id": "", "description": "Father in a grey shirt", "action": "listens", "position": ""}])}
        if s["n"] == 7 else s)
    heard = only(plan, "heard")
    assert len(heard) == 1 and heard[0].shots == [7] and "Father" in heard[0].sentence


def test_what_veo_does_badly_is_reported_with_the_known_way_round():
    plan = shots(gold.phone_call(), lambda s: {**s, "why": "The screen shows the message: a long text."}
                 if s["n"] == 4 else s)
    report = only(plan, "feasibility")
    assert len(report) == 1 and report[0].fix == "report" and "glow" in report[0].sentence


def test_rain_on_a_road_is_not_a_mirror_but_a_mirror_is():
    wet = shots(gold.phone_call(), lambda s: {**s, "why": "Reflections of the lights on the wet road."}
                if s["n"] == 1 else s)
    assert only(wet, "feasibility") == []
    glass = shots(gold.phone_call(), lambda s: {**s, "why": "She checks her reflection in the mirror."}
                  if s["n"] == 1 else s)
    assert [p.fix for p in only(glass, "feasibility")] == ["report"]


# ── staging and the end state ────────────────────────────────────────────────────────────────────


def test_a_teleport_is_found_with_a_sentence_that_names_the_blocks():
    plan = gold.phone_call()
    marks = [m.model_dump() for m in plan.staging.marks]
    marks[-1] = {**marks[-1], "zone": "path"}  # she is on the bench at block 7 and on the path at block 9
    moved = JonathanWire.model_validate({**plan.model_dump(), "staging": {"zones": plan.staging.zones, "marks": marks}})
    found_ = only(moved, "staging")
    assert len(found_) == 1 and found_[0].fix == "repair" and "block 9" in found_[0].sentence


def test_a_staging_the_scene_cannot_check_is_reported_not_failed():
    plan = JonathanWire.model_validate({**gold.phone_call().model_dump(), "staging": {"zones": [], "marks": []}})
    assert [p.fix for p in only(plan, "staging")] == ["report"]


def test_an_end_state_that_names_a_stranger_or_loses_a_prop_is_sent_back():
    plan = gold.phone_call()
    ends = plan.end_state.model_dump()
    ends["people"][0]["holding"] = ""  # Anudi holds her bag at the last mark; the end state loses it
    ends["people"].append({"who": "Waiter", "where": "door", "facing": "", "holding": "", "look": ""})
    del ends["people"][2]  # and Father is not accounted for
    bad = JonathanWire.model_validate({**plan.model_dump(), "end_state": ends})
    sentences = " ".join(p.sentence for p in only(bad, "end_state"))
    assert "Waiter" in sentences and "her bag" in sentences and "Father" in sentences


def test_where_the_staging_leaves_a_person_is_written_into_the_end_state_by_the_mend():
    plan = gold.phone_call()
    ends = plan.end_state.model_dump()
    ends["people"][1]["where"] = "the kitchen"  # Dasun's last mark is the right end of the bench
    bad = JonathanWire.model_validate({**plan.model_dump(), "end_state": ends})
    assert any("Dasun" in p.sentence and "kitchen" in p.sentence for p in only(bad, "end_state"))
    mended, done, _ = mend.mend(gold.scene(), bad)
    assert mended.end_state.people[1].where == "right end of the bench" and only(mended, "end_state") == []
    assert any("Dasun" in d and "the kitchen" in d for d in done)


# ── the craft measures ───────────────────────────────────────────────────────────────────────────


def test_the_measures_are_reported_never_a_problem():
    plan = shots(gold.phone_call(), lambda s: {**s, "size": "MS"})  # one size everywhere: flat
    assert found(plan) == [] or all(p.code != "craft" for p in found(plan))
    got = measured(plan)
    assert got["opens"].status == "missed" and got["variety"].status == "missed" and got["objects"].status == "missed"


def test_a_falling_thing_shot_locked_off_is_a_motion_gap_and_a_follow_meets_it():
    beats = [{"time": "0-4s", "camera": "insert", "director_line": "It falls.", "action": "The phone drops into a "
              "puddle.", "performance": "-"}]
    locked = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(beats=beats, movement="locked-off")}
                   if s["n"] == 6 else s)
    assert measured(locked)["motion"].status == "missed"
    follow = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(beats=beats, movement="tilt down with it")}
                   if s["n"] == 6 else s)
    assert measured(follow)["motion"].status == "met"
    gaze = [{**beats[0], "action": "Her gaze drops to her lap."}]
    small = shots(gold.phone_call(), lambda s: {**s, "ir": gold.ir(beats=gaze)} if s["n"] == 6 else s)
    assert measured(small)["motion"].status == "info"  # a gaze that drops is not a fall


def test_a_line_with_no_listener_and_a_compound_action_in_one_shot_are_craft_gaps():
    no_reaction = JonathanWire.model_validate({**gold.phone_call().model_dump()}).without({13})
    assert measured(no_reaction)["reactions"].status == "missed" and "L8" in measured(no_reaction)["reactions"].detail
    one_shot = shots(gold.phone_call(), lambda s: None if s["n"] == 14 else s)
    assert measured(one_shot)["compound"].status == "missed" and "b9: 1 shot" in measured(one_shot)["compound"].detail


def test_a_flat_grade_and_a_sequence_that_ends_on_a_line_are_craft_gaps():
    data = gold.phone_call().model_dump()
    for c in data["treatment"]["colour_script"]:
        c["grade"] = "warm"
    assert measured(JonathanWire.model_validate(data))["grade"].status == "missed"
    ends_on_line = gold.phone_call().without({3})  # sequence A now ends on Dasun's line
    assert measured(ends_on_line)["endings"].status == "missed"


# ── the mend never deletes ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["phone_call", "arrival", "father_refuses"])
def test_whatever_the_mend_does_a_gold_scene_keeps_every_block_and_every_line(name: str):
    scene = gold.scene(name, others=())
    items = scene.items()
    blocks = [b.index for b in scene.blocks]
    lines = [b.line_id for b in sorted(scene.lines, key=lambda b: b.index)]
    one_take = bare([gold.shot(1, "A", blocks, "WIDE", 8, 8, "all of it", lines=[x for x in lines if x])], scene.cast)
    mended, _, _ = mend.mend(scene, one_take)
    assert sorted(b for s in mended.shots for b in s.blocks) == blocks and len(items) == len(blocks)
    assert [ln for s in mended.shots for ln in s.lines] == lines
    assert [p for p in checks.problems(scene, mended) if p.code in ("lines", "blocks", "clock", "use", "sequence")
            and p.fix != "report"] == []
