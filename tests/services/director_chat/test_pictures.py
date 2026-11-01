"""Pictures in the director's kernel (plan/2026-11-01b Phase 5): a change that crowds a shot is named, a
block that is re-written is read again, and a person's removal of an implied step is remembered."""
from __future__ import annotations

from director_chat.engine import options
from director_chat.engine.kernel import ScenePlanKernel
from director_chat.engine.turn import kernel_for

from contracts import bridges, sceneplan
from contracts.shotplan import ProposedShot, fit
from tests.services import scene2_fixture as scene2


def scene2_kernel(*, with_bridges: bool = False, locked: bool = False) -> ScenePlanKernel:
    lines = scene2.lines()
    script = scene2.blocks(screens=True)
    if with_bridges:
        script = bridges.with_bridges(script, lines, 1)
    scene = {**scene2.scene_row(), "script": script, "production_id": "p"}
    items = sceneplan.items_for(script, lines)
    call = next(i.index for i in items if i.line_id == "l5")
    start = next(i.index for i in items if i.text == "Anudi smiled back.")
    ring = ProposedShot(start, call - 1, "MS", "Anudi's phone rings")
    voice = ProposedShot(call - 1, call + 1, "MCU", "Anudi takes the call", "voiceover", 4 if locked else None, locked)
    after = ProposedShot(call + 1, len(items), "MCU", "She leaves")
    plan = [ProposedShot(0, start, "MS", "At the stall"), ring, voice, after]
    result = fit(items, plan, envelope_s=60)
    shots, _, _ = sceneplan.rows_after_fit(scene, [{"start": p.start, "duration_locked": p.duration_locked}
                                                   for p in plan], result, lines)
    return kernel_for(scene, lines, shots, None)


def test_merging_the_ring_and_the_voice_names_what_it_would_need():
    k = scene2_kernel()
    ring = next(n for n, s in enumerate(k.shots, start=1) if s["title"] == "Anudi's phone rings")
    r = k.apply([{"op": "merge", "shot": ring}], by="you", respect_locks=False)
    assert r.applied
    assert any("would need" in n and "the longest shot is 8 s" in n for n in k.notes), k.notes
    assert not k.fit().crowded  # the kernel cut it again rather than squeeze it


def test_an_option_that_merges_names_the_crowding_in_its_impact_line():
    k = scene2_kernel()
    before = k.fit()
    ring = next(n for n, s in enumerate(k.shots, start=1) if s["title"] == "Anudi's phone rings")
    import copy
    trial = copy.deepcopy(k)
    seen = len(trial.notes)
    trial.apply([{"op": "merge", "shot": ring}], by="you", respect_locks=False)
    assert "would need" in options.impact(before, trial, trial.notes[seen:])


def test_a_locked_short_shot_is_crowded_and_the_scene_reports_it():
    k = scene2_kernel(locked=True)
    after = k.fit()
    assert after.crowded and after.need_s >= after.total_s
    row = sceneplan.fit_report(after, "director")
    assert row["crowded"] == after.crowded and row["need_s"] == after.need_s


def test_rewriting_an_action_reads_it_again_and_drops_the_stored_reading():
    k = scene2_kernel()
    index = next(n for n, i in enumerate(k.items) if i.get("text") == "Anudi walks up to the stall.")
    assert k.items[index]["screen"] == "move" and k.items[index]["for_version"] == 1
    r = k.apply([{"op": "block.set", "block": index, "field": "text", "value": "Anudi inspects the menu board."}],
                by="you", respect_locks=False)
    assert r.applied
    item = k.items[index]
    assert "for_version" not in item and "by" not in item and item["screen"] == "act"  # read again by the rules


def test_removing_an_implied_step_is_remembered_on_the_phone_line():
    k = scene2_kernel(with_bridges=True)
    answer = next(n for n, i in enumerate(k.items) if i.get("bridge") == bridges.ANSWER_PHONE)
    r = k.apply([{"op": "block.remove", "block": answer}], by="you", respect_locks=False)
    assert r.applied
    saved = sceneplan.script_rows(k.items)
    line = next(b for b in saved if b.get("line_id") == "l5")
    assert line["skip_bridges"] == [bridges.ANSWER_PHONE]
    assert not [b for b in bridges.with_bridges(saved, scene2.lines(), 2) if b.get("bridge") == bridges.ANSWER_PHONE]
    # and what the kernel holds survives a round trip: readings and the implied mark
    lower = next(b for b in saved if b.get("bridge") == bridges.LOWER_PHONE)
    assert lower["implied"] and lower["screen"] == "act" and lower["for_version"] == 1


def test_a_plain_message_can_name_the_block_a_shot_is_split_at():
    """The interface's "Split here" sends this when the intent agent says a shot cannot be one take."""
    from director_chat.engine import conductor

    plan = conductor.by_rules("Split S05 at block 12.", split_points={5: 11})
    assert plan.ops == [{"op": "split", "shot": 5, "at_block": 12}]
    assert conductor.by_rules("Split S05.", split_points={5: 11}).ops == [{"op": "split", "shot": 5, "at_block": 11}]
    # the button's exact command is read in code even with a model key; anything wordier goes to the model
    assert conductor.is_exact_command("Split S05 at block 12.") and conductor.is_exact_command(" split s5 at block 3 ")
    assert not conductor.is_exact_command("Split S05 at block 12 and make it a wide.")
    k = scene2_kernel()
    ring = next(n for n, s in enumerate(k.shots, start=1) if s["title"] == "Anudi's phone rings")
    cut = k.shots[ring - 1]["start"] + 1
    r = k.apply([{"op": "split", "shot": ring, "at_block": cut}], by="you", respect_locks=False)
    assert r.applied and k.shots[ring]["start"] == cut
