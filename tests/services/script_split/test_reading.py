"""Shots planned by a director (plan/2026-11-01d, Phases 1-3): the scene reading, a planner that sees it, and breath
that is budgeted instead of treated as a cost."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from script_split.engine import critic, pipeline, planner
from script_split.engine import reading as engine

from contracts import bridges, sceneplan
from contracts import reading as rd
from contracts.shotplan import Item, ProposedShot, fit
from tests.services import scene2_fixture as scene2
from tests.services.fakes import FakeJobs, FakeLLM
from tests.services.script_split.test_pictures import raising, scene2_scene
from tests.services.script_split.test_split import FakeStore, payload

ROOT = Path(__file__).resolve().parents[3]
ENV = 35
CAST = ["Kasun", "Anudi", "Anudi's Father"]
NAMES = {scene2.KASUN: "Kasun", scene2.ANUDI: "Anudi", scene2.FATHER: "Anudi's Father"}


def prepared() -> list[Item]:
    scene, lines = scene2_scene()
    return pipeline.prepare(scene, lines, FakeLLM(enabled=False), CAST)[1]


def at(items: list[Item], text: str) -> int:
    return next(i.index for i in items if text in i.text)


def model_reading(items: list[Item]) -> dict[str, Any]:
    call, look = at(items, "Anudi, where are you"), at(items, "She looked at Kasun")
    watched = at(items, "watched her go")
    note = at(items, "no idea")
    return {
        "about": "A first meeting is cut short by a call.", "value": {"start": "joy", "end": "dread"},
        "tone": "warm, uneasy",
        "units": [{"from_block": 0, "to_block": call, "wants": [{"character": "Anudi", "verb": "to charm"},
                                                                  {"character": "Kasun", "verb": "to impress"}],
                   "turn_block": call},
                  {"from_block": call + 1, "to_block": len(items) - 1, "wants": [{"character": "Anudi",
                                                                                    "verb": "to escape"}],
                   "turn_block": look}],
        "subtext": [{"block": note, "who": "Kasun", "behaviour": "watches her go, still smiling, unaware",
                     "narration_only": False, "reason": ""}],
        "breath": [{"after_block": call, "kind": "reaction", "who": "Anudi", "seconds": 2, "priority": 1,
                    "why": "the call breaks the joy"},
                   {"after_block": watched, "kind": "button", "who": "Kasun", "seconds": 2, "priority": 1,
                    "why": "the last image"},
                   {"after_block": look, "kind": "reaction", "who": "Kasun", "seconds": 1, "priority": 3,
                    "why": "she turns back"}],
        "ending": "Kasun, alone with the pot."}


# ── Phase 1: the scene reading ────────────────────────────────────────────────────────────


def test_the_static_prompt_does_not_depend_on_the_scene_and_the_craft_notes_are_the_studios_own():
    system = engine.READING_SYSTEM
    assert "{" not in system and "Anudi" not in system and "STORY NOTE" in system and "Weston" in system
    craft = " ".join(" ".join(
        (ROOT / "src" / "libs" / "hiru_ai" / "knowledge_bases" / "craft" / "sources" / f)
        .read_text(encoding="utf-8").split())
        for f in ("directing.md", "editing.md"))
    for passage in engine.CRAFT:
        assert " ".join(passage.split()) in craft, passage  # a copy that has drifted from the studio's notes


def test_a_model_reading_is_asked_on_the_high_tier_with_the_whole_scene_around_it():
    scene, lines = scene2_scene(note="Keep it light until the call.")
    items = pipeline.prepare(scene, lines, FakeLLM(enabled=False), CAST)[1]
    llm = FakeLLM({"scene_reading": lambda s, u: model_reading(items)})
    context = engine.SceneContext(
        heading="EXT. STALL - DAY", note="Keep it light until the call.", episode_title="The Meeting",
        synopsis="Two strangers meet over rice.", before="INT. HOUSE - NIGHT — Anudi Packs",
        after="INT. CAR - DAY", characters=(("Anudi", "A young woman, careful with her words."),))
    made, new = engine.reading_for(scene, items, llm.json and (lambda s, u: llm.json(
        tier="high", phase="script_split.reading", system=s, user=u, schema_name="scene_reading", schema={})),
        CAST, context=context, speaker_names=NAMES)
    assert new and made.by == "model" and made.value.end == "dread" and made.for_version == 3
    user = llm.calls[0]["user"]
    for needle in ("Two strangers meet over rice.", "Keep it light until the call.", "INT. CAR - DAY",
                   "A young woman, careful", "STORY NOTE (not filmed): He has no idea", "<script>"):
        assert needle in user, needle
    assert made.written_at and made.basis == rd.basis(items)


def test_without_a_key_a_failed_call_or_an_empty_answer_the_rules_read_the_scene():
    items = prepared()
    for ask in (None, raising, lambda s, u: {}, lambda s, u: {"about": "", "units": [], "breath": []}):
        made = engine.make(ask, items, CAST, version=3)
        assert made.by == "rules" and made.for_version == 3 and any(b.kind == "reaction" for b in made.breath)


def test_a_persons_reading_is_never_replaced_and_a_current_one_is_not_made_again():
    scene, lines = scene2_scene()
    items = pipeline.prepare(scene, lines, FakeLLM(enabled=False), CAST)[1]
    asked: list[int] = []

    def ask(system: str, user: str) -> dict[str, Any]:
        asked.append(1)
        return model_reading(items)

    person = rd.validate(model_reading(items), items, CAST, version=1, by="person")  # an OLD script version
    stale = {**scene, "reading": person.model_dump(mode="json")}
    kept, new = engine.reading_for(stale, items, ask, CAST)
    assert kept.by == "person" and not new and not asked and kept.stale(items, 3)  # stale, still the person's

    made, new = engine.reading_for(scene, items, ask, CAST)
    assert new and len(asked) == 1
    current = {**scene, "reading": made.model_dump(mode="json")}
    again, new = engine.reading_for(current, items, ask, CAST)
    assert not new and len(asked) == 1 and again == made
    moved = {**current, "script_version": 4}  # a script edit: the model's reading is made again
    assert engine.reading_for(moved, items, ask, CAST)[1] and len(asked) == 2


def test_the_split_writes_the_reading_with_the_shots_and_times_the_scene_with_it():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    items = pipeline.prepare(scene, lines, FakeLLM(enabled=False), CAST)[1]
    llm = FakeLLM({"scene_reading": lambda s, u: model_reading(items)})
    pipeline.run(payload(), store, FakeJobs(), llm)
    stored = store.scene_rows[scene["id"]]
    read = rd.SceneReading.of(stored)
    assert read is not None and read.by == "model" and read.about.startswith("A first meeting")
    calls = [c for c in llm.calls if c["schema"] == "scene_reading"]
    assert len(calls) == 1 and calls[0]["tier"] == "high" and calls[0]["phase"] == "script_split.reading"
    shots = store.shots[scene["id"]]
    assert stored["fit_report"]["breath"]["kept_s"] >= 4.0  # the call's reaction and the button, at least
    assert max(s["block_end"] for s in shots) == len(stored["script"])
    # reading the stored scene back times it the same way the split did
    again = sceneplan.scene_items(stored, store.line_rows[scene["id"]])
    assert sum(1 for i in again if i.hold_s) >= 2
    total = fit(again, sceneplan.proposal_for(sceneplan.plan_from_rows(
        [{**s, "block_start": s["block_start"], "block_end": s["block_end"]} for s in shots])),
        envelope_s=ENV).total_s
    assert total == sum(s["duration_s"] for s in shots)


def test_without_a_key_the_rules_reading_is_stored_and_a_second_split_keeps_it():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    first = rd.SceneReading.of(store.scene_rows[scene["id"]])
    assert first is not None and first.by == "rules" and any(b.kind == "button" for b in first.breath)
    store.scene_rows[scene["id"]]["status"] = "draft"
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    second = rd.SceneReading.of(store.scene_rows[scene["id"]])
    assert second is not None and second.written_at == first.written_at  # not made again


def test_a_talking_heads_scene_has_no_breath_and_plans_as_before():
    items = [Item(0, "action", "A kettle boils.", screen="act"),
             Item(1, "dialogue", "Hello there my friend.", "Nimal", "n", "", "l1"),
             Item(2, "dialogue", "Hello to you too.", "Kamala", "k", "", "l2")]
    made = rd.by_rules(items, ["Nimal", "Kamala"], version=1)
    assert made.breath == [] and rd.apply(items, made) == items
    assert planner.plan_by_rules(rd.apply(items, made), envelope_s=60) == planner.plan_by_rules(items, envelope_s=60)


# ── Phase 3: the planner plans by turns; breath is budgeted ────────────────────────────────


def timed_items() -> tuple[list[Item], rd.SceneReading]:
    items = prepared()
    made = rd.by_rules(items, CAST, version=3)
    return rd.apply(items, made), made


def test_the_planner_sees_the_reading_the_context_and_the_marks_in_the_listing():
    items, made = timed_items()
    seen: dict[str, str] = {}

    def plan(system: str, user: str) -> dict[str, Any]:
        seen.update(system=system, user=user)
        return {"shots": [{"start": 0, "end": len(items), "framing": "MS", "title": "all", "sound_mode": "dialogue",
                           "duration": 8, "camera_link": "cut"}]}

    planner.plan_by_model(plan, items, heading="EXT. STALL", envelope_s=ENV, allowed=(4, 6, 8), speaker_names={},
                          context="Episode synopsis: two strangers meet.", reading=made.text())
    user = seen["user"]
    assert "<context>\nEpisode synopsis: two strangers meet.\n</context>" in user and "<reading>" in user
    assert "[HOLD 1.5 s after it: reaction for Anudi, priority 1]" in user and "[FEELING TURNS HERE]" in user
    assert user.index("<reading>") < user.index("<script>")
    system = seen["system"]
    assert "{" not in system and "Envelope:" not in system  # still static
    assert "Silent shots are only for beats the script names" not in system
    assert "add no silent shots" not in system and "Breath comes only from the reading" in system
    assert "reaction SEEN" in system and "never priority 1" in system


def test_the_critic_no_longer_forbids_a_reaction_the_script_does_not_name():
    assert "Do not ask for a reaction or an insert the script does not name" not in critic.CRITIC_SYSTEM
    assert "Breath comes only from the reading" in critic.CRITIC_SYSTEM


def test_the_rules_plan_shows_a_listener_who_reacts_at_the_end_of_a_speakers_shot():
    items = [Item(0, "action", "Anudi walks in.", screen="move"),
             Item(1, "dialogue", "I am leaving.", "Kasun", "k", "", "l1", hold_s=1.5, hold_kind="reaction",
                  hold_priority=1, hold_who="Anudi", turn=True),
             Item(2, "dialogue", "Why?", "Anudi", "a", "", "l2")]
    shots = planner.plan_by_rules(items)
    assert [s.framing for s in shots] == ["TWO", "MCU"]  # her face is in the frame while the hold plays


def over_the_envelope() -> tuple[list[Item], list[ProposedShot]]:
    """Scene 2 with an optional hold of each priority added, and an envelope it cannot meet with them."""
    items, _ = timed_items()
    spots = [at(items, "Kasun slides a plate"), at(items, "Kasun stirs"), at(items, "Anudi walks up")]
    for spot, (priority, kind) in zip(spots, [(3, "atmosphere"), (2, "transition"), (3, "atmosphere")], strict=True):
        items[spot] = replace(items[spot], hold_s=3.0, hold_kind=kind, hold_priority=priority, hold_who="")
    return items, planner._rules_shots(items)


def held_after(kept: list[Item]) -> dict[int, int]:
    return {i.index: i.hold_priority for i in kept if i.hold_s > 0}


def test_over_the_envelope_optional_breath_goes_first_lowest_priority_first_and_priority_one_stays():
    items, shots = over_the_envelope()  # holds: 0 (priority 2), 1 and 7 (priority 3), and four priority-1 moments
    assert fit(items, shots, envelope_s=99).total_s == 76 and held_after(items) == {
        0: 2, 1: 3, 4: 1, 7: 3, 13: 1, 16: 1, 19: 1}
    nothing_given_up, _ = planner.fold_breath(items, shots, envelope_s=76)
    assert held_after(nothing_given_up) == held_after(items)
    one_threes, _ = planner.fold_breath(items, shots, envelope_s=75)  # the later priority-3 hold goes first
    assert held_after(one_threes) == {0: 2, 1: 3, 4: 1, 13: 1, 16: 1, 19: 1}
    both_threes, _ = planner.fold_breath(items, shots, envelope_s=72)
    assert held_after(both_threes) == {0: 2, 4: 1, 13: 1, 16: 1, 19: 1}
    the_two, _ = planner.fold_breath(items, shots, envelope_s=68)  # then priority 2
    assert held_after(the_two) == {4: 1, 13: 1, 16: 1, 19: 1}
    squeezed, folded = planner.fold_breath(items, shots, envelope_s=1)  # nothing fits: priority 1 is still there
    assert held_after(squeezed) == {4: 1, 13: 1, 16: 1, 19: 1}
    assert fit(squeezed, folded, envelope_s=1).over_envelope_s > 0  # ... and the overrun is reported, not squeezed


def test_a_drop_that_would_not_shorten_the_scene_is_not_made():
    items, _ = timed_items()
    spot = at(items, "Kasun stirs")
    items[spot] = replace(items[spot], hold_s=1.0, hold_kind="atmosphere", hold_priority=3)
    shots = planner._rules_shots(items)
    roomy = fit(items, shots, envelope_s=200)
    kept, _ = planner.fold_breath(items, shots, envelope_s=roomy.total_s - 1)  # one second short
    after = fit(kept, shots, envelope_s=roomy.total_s - 1)
    assert after.total_s <= roomy.total_s
    kept_roomy, _ = planner.fold_breath(items, shots, envelope_s=roomy.total_s)
    assert next(i for i in kept_roomy if i.index == spot).hold_s == 1.0  # it fits: nothing is given up


def test_priority_one_is_reported_never_dropped_when_the_envelope_cannot_be_met():
    scene, lines = scene2_scene(envelope_s=10)
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    stored = store.scene_rows[scene["id"]]
    report = stored["fit_report"]
    assert report["need_s"] > 10 and any(i["code"] == "envelope" for i in report["issues"])
    read = rd.SceneReading.of(stored)
    assert read is not None and all(not b.off for b in read.breath if b.priority == 1)
    assert report["breath"]["kept_s"] >= sum(b.seconds for b in read.breath if b.priority == 1)


def test_optional_breath_given_up_for_the_envelope_is_reported_and_remembered_on_the_reading():
    scene, lines = scene2_scene()
    items = pipeline.prepare(scene, lines, FakeLLM(enabled=False), CAST)[1]
    answer = model_reading(items)
    filler = [{"after_block": at(items, "Kasun slides a plate"), "kind": "atmosphere", "who": "", "seconds": 3,
               "priority": 3, "why": "the plate"},
              {"after_block": at(items, "Anudi laughs"), "kind": "transition", "who": "Anudi", "seconds": 3,
               "priority": 2, "why": "the laugh"}]
    # the plate and the laugh need a turn, a unit end or subtext to earn them: give the units an end there
    plate = at(items, "Kasun slides a plate")
    answer["units"] = [{"from_block": 0, "to_block": plate, "wants": [], "turn_block": None},
                       {"from_block": plate + 1, "to_block": len(items) - 1, "wants": [],
                        "turn_block": at(items, "Anudi, where are you")}]
    answer["breath"] = [answer["breath"][0], *filler[:1]]
    for envelope in (200, 20):
        run_scene, run_lines = scene2_scene(envelope_s=envelope)
        store = FakeStore([(run_scene, run_lines)])
        pipeline.run(payload(), store, FakeJobs(), FakeLLM({"scene_reading": lambda s, u: answer}))
        stored = store.scene_rows[run_scene["id"]]
        read = rd.SceneReading.of(stored)
        assert read is not None
        breath = stored["fit_report"]["breath"]
        if envelope == 200:
            assert not any(b.off for b in read.breath) and breath["dropped"] == []
        else:
            assert [b.kind for b in read.breath if b.off] == ["atmosphere"]
            assert [b.off_by for b in read.breath if b.off] == ["envelope"]
            assert breath["dropped"][0]["priority"] == 3 and breath["core_need_s"] <= breath["needs_s"]
            # the API times the stored scene the same way: the dropped hold is not played
            again = sceneplan.scene_items(stored, store.line_rows[run_scene["id"]])
            assert not any(i.hold_priority == 3 for i in again)


# ── the score: code picks the plan, and breath is no longer a cost ─────────────────────────


def test_a_plan_fitted_without_a_priority_one_reaction_loses_to_one_that_keeps_it():
    items, made = timed_items()
    call = at(items, "Anudi, where are you")
    dropped = rd.release(items, call)
    proposal = planner.plan_by_rules(items)
    keeps = fit(items, proposal, envelope_s=60)
    drops = fit(dropped, proposal, envelope_s=60)
    assert critic.breath_missing(keeps, made, items) == 0 and critic.breath_missing(drops, made, items) == 1
    # even though dropping it makes the scene shorter
    assert drops.need_s <= keeps.need_s
    assert critic.kernel_score(keeps, made, items) < critic.kernel_score(drops, made, items)
    assert critic.kernel_score(keeps)[2] == 0  # with no reading to check against, nothing is missing


def test_a_person_who_switches_a_breath_off_is_not_overruled():
    items, made = timed_items()
    call = at(items, "Anudi, where are you")
    off = rd.mark_off(made, items, [call], by="person")
    result = fit(rd.apply(items, off), planner.plan_by_rules(items), envelope_s=60)
    assert critic.breath_missing(result, off, rd.apply(items, off)) == 0


def test_breath_outside_the_band_is_a_cost_and_a_scene_that_asks_for_none_is_exempt():
    items, made = timed_items()
    result = fit(items, planner.plan_by_rules(items), envelope_s=60)
    share = result.breath_s / result.total_s
    assert critic.breath_band_s(result, made) == (0 if 0.15 <= share <= 0.30 else critic.breath_band_s(result, made))
    thin = made.model_copy(update={"breath": made.breath[:1]})
    plain = fit(rd.apply(items, thin), planner.plan_by_rules(items), envelope_s=60)
    assert critic.breath_band_s(plain, thin) > 0 and critic.breath_band_s(plain, rd.SceneReading(by="rules")) == 0
    assert critic.breath_band_s(plain, None) == 0


def test_silence_a_hold_earns_is_not_a_problem_but_silence_nobody_asked_for_still_is():
    speech = Item(0, "dialogue", " ".join(["word"] * 12), "Nimal", "n", "", "l0")
    quiet = Item(1, "action", "A long look at the sea.", screen="act")
    shots = [ProposedShot(0, 1), ProposedShot(1, 2, duration=8, duration_locked=True)]
    bare = fit([speech, quiet], shots, envelope_s=60)
    assert bare.unearned_silent_s == bare.silent_s == 8 and bare.silent_share > critic.SILENT_SHARE_MAX
    assert critic.issue_count(bare) == 1
    held = fit([speech, replace(quiet, hold_s=3.0, hold_kind="atmosphere", hold_priority=2)], shots, envelope_s=60)
    assert held.silent_s == 8 and held.unearned_silent_s == 5  # three of the eight seconds are breath
    assert critic.kernel_score(held)[-1] < critic.kernel_score(bare)[-1]


def test_the_kernel_score_keeps_its_order_issues_then_two_speakers_then_the_rest():
    items, made = timed_items()
    score = critic.kernel_score(fit(items, planner.plan_by_rules(items), envelope_s=60), made, items)
    assert len(score) == 10 and score[:6] == (0, 0, 0, 0, 0, 0)


def test_the_critic_is_told_about_the_breath_a_plan_holds():
    items, _ = timed_items()
    result = fit(items, planner.plan_by_rules(items), envelope_s=60)
    text = critic.describe(result, items)
    assert "Breath held:" in text and "1.5 s reaction after block" in text


def test_scene_2_keeps_a_reaction_at_the_call_and_the_button_through_a_full_split():
    scene, lines = scene2_scene(envelope_s=45)
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    stored = store.scene_rows[scene["id"]]
    script = stored["script"]
    items = sceneplan.scene_items(stored, store.line_rows[scene["id"]])
    held = {(i.hold_kind, i.hold_who) for i in items if i.hold_s}
    assert ("reaction", "Anudi") in held and ("button", "Kasun") in held
    call = next(n for n, b in enumerate(script) if b.get("line_id") and b["line_id"] == "l5")
    shot = next(s for s in store.shots[scene["id"]] if s["block_start"] <= call < s["block_end"])
    assert shot["duration_s"] >= 6  # the call and the face that receives it have the seconds they need
    assert not [b for b in script if b.get("bridge") == bridges.LOWER_PHONE and not b.get("implied")]
    assert re.fullmatch(r"[0-9a-f]{16}", rd.basis(items))
