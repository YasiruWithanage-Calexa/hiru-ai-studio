"""The director chat changes what the Script column shows: a spoken line is STAGED for the person to
accept (their own words only, with EDIT_SCRIPT), the rest of the script and a shot's marks are applied,
and every script change is checked against the shots around it."""
from __future__ import annotations

from uuid import UUID, uuid4

from director_chat.engine import choice
from director_chat.engine.turn import SCRIPT_CONFLICT

from contracts.director import ChoicePayload
from contracts.producer import PersonEdits
from tests.services.director_chat.conftest import PAN, PID, DirectorLLM, FakeStore, fixture_scene
from tests.services.director_chat.test_turn import plan_answer, run, store0

ACTOR = uuid4()
NEW_LINE = "One day I will open my own restaurant"
ASK = f"Change the dialogue of S02 to “{NEW_LINE}”"


def options_of(store: FakeStore) -> dict:
    return next(b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options")


def choose(store: FakeStore, ops: list[dict], *, can_edit_script: bool = True) -> choice.ChoiceResult:
    return choice.apply_choice(ChoicePayload(production_id=PID, scene_id=UUID(store.scene_row["id"]),
                                             actor_user_id=ACTOR, can_edit_script=can_edit_script, ops=ops), store)


def edit_by_model(*ops: dict, **responders) -> DirectorLLM:
    return DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=list(ops)), **responders})


# ── a spoken line is staged, then applied on the person's say ──────────────────────────────


def test_a_line_change_is_staged_with_its_checks_and_nothing_is_saved():
    store = store0()
    old = store.line_rows[0]["text"]
    events = run(store, ASK)
    assert not store.saved and "plan" not in [e for e, _ in events]  # nothing applied
    message = store.message_rows[-1]
    assert [b["kind"] for b in message["blocks"]][:2] == ["text", "options"]
    assert "I have not changed the script yet" in message["blocks"][0]["text"]
    block = options_of(store)
    apply, keep = block["options"]
    assert block["question"] == "Change S02?" and apply["label"] == "Apply this change"
    assert apply["detail"] == f"S02: “{old}” → “{NEW_LINE}”"
    assert "words" in apply["impact"] and "room for" in apply["impact"]  # Words: before → after, and what fits
    op = apply["ops"][0]
    assert op["op"] == "block.set" and op["line_id"] == store.line_rows[0]["id"] and op["was"] == old
    assert op["value"] == NEW_LINE and "block" not in op  # named by the line, not by a number
    assert keep["label"] == "Keep it as it is" and not keep["ops"] and not keep["prompt"]
    assert message["ops"] == [] and not any(b["kind"] == "edit-note" for b in message["blocks"])
    assert any("Nimal" in b["text"] for b in message["blocks"] if b["kind"] == "continuity") is False  # no one else
    assert store.audits == []


def test_the_staged_change_is_applied_when_chosen_and_saves_the_script_with_a_new_version():
    store = store0()
    run(store, ASK)
    ops = options_of(store)["options"][0]["ops"]
    ids = [s["id"] for s in store.shots(PID)]
    result = choose(store, ops)
    assert result.applied and result.summary.startswith("Applied: S02 Nimal line → “")
    assert "Checked S01, S02, S03" in result.summary
    saved = store.saved[-1]
    assert [s["id"] for s in saved["shots"]] == ids and not saved["removed"]  # ids kept
    assert saved["scene"]["script_version"] == 2 and not saved["removed_lines"]
    line = next(ln for ln in saved["lines"] if ln["id"] == store.line_rows[0]["id"])
    assert line["text"] == NEW_LINE and line["speaker"] == "Nimal" and line["ord"] == 0
    assert [b["kind"] for b in saved["scene"]["script"]] == ["action", "dialogue", "action", "dialogue"]
    assert saved["scene"]["script"][1] == {"kind": "dialogue", "text": "", "line_id": line["id"]}
    assert saved["shots"][1]["version"] == 2 and saved["shots"][0]["version"] == 1  # only the shot with the words
    assert store.audits[-1]["action"] == "scene.director_choice"


def test_a_staged_change_for_a_line_someone_else_changed_is_refused():
    store = store0()
    run(store, ASK)
    ops = options_of(store)["options"][0]["ops"]
    store.line_rows[0]["text"] = "Someone else's words"
    result = choose(store, ops)
    assert not result.applied and result.summary == choice.GONE and not store.saved


def test_a_script_saved_meanwhile_is_a_conflict_not_an_overwrite():
    store = store0()
    run(store, ASK)
    ops = options_of(store)["options"][0]["ops"]
    reads = {"n": 0}
    read = store.scene

    def scene(production_id, scene_id):
        reads["n"] += 1
        row = read(production_id, scene_id)
        return {**row, "script_version": 2} if reads["n"] > 1 else row  # saved by someone else before our write

    store.scene = scene  # type: ignore[method-assign]
    result = choose(store, ops)
    assert not result.applied and result.summary == SCRIPT_CONFLICT and not store.saved


def test_only_a_role_that_can_edit_the_script_may_change_a_line():
    store = store0()
    run(store, ASK, can_edit_script=False)
    assert not store.saved and not any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])
    assert "can change shots but not the script's words" in store.message_rows[-1]["blocks"][0]["text"]
    staged = store0()
    run(staged, ASK)
    result = choose(staged, options_of(staged)["options"][0]["ops"], can_edit_script=False)
    assert not result.applied and result.summary == choice.NO_SCRIPT and not staged.saved


# ── only the person's own words ────────────────────────────────────────────────────────────


def line_op(value: str, field: str = "text") -> dict:
    return {"op": "block.set", "block": 1, "field": field, "value": value}


def test_a_line_may_only_use_words_the_person_wrote():
    store = store0()
    run(store, "Make Nimal's line in S02 sound more hopeful", edit_by_model(line_op("I have come home, Amma.")))
    assert not store.saved and not any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])
    llm = edit_by_model(line_op("I have come home, Amma."))
    run(store, "Make Nimal's line in S02 sound more hopeful", llm)
    assert "Refused: a line can only use words you wrote" in llm.streamed[-1][1]["content"]


def test_curly_quotes_dots_and_case_do_not_defeat_the_check():
    store = store0()
    run(store, "S02 line: “One day… I’ll open my own restaurant”",
        edit_by_model(line_op("one day... i'll open my own restaurant")))
    assert any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])


def test_words_from_an_earlier_message_of_the_person_count_but_the_directors_do_not():
    store = store0()
    store.history = [{"id": "u1", "kind": "user", "speaker": "Dee", "text": f"I want S02 to say: {NEW_LINE}",
                      "blocks": []},
                     {"id": "d1", "kind": "director", "speaker": "CT", "text": "",
                      "blocks": [{"kind": "text", "text": "How about: I came back for good."}]}]
    run(store, "yes, do it", edit_by_model(line_op(NEW_LINE)))
    assert any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])
    run(store, "yes, do the director's idea", edit_by_model(line_op("I came back for good.")))
    assert not any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])  # its own words, not the person's


def test_a_model_cannot_slip_an_unwritten_line_in_with_a_new_block():
    store = store0()
    insert = {"op": "block.insert", "block": 2, "kind": "dialogue", "value": "Invented words", "speaker": "Kamala"}
    run(store, "Add a line for Kamala after Nimal's", edit_by_model(insert))
    assert not any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"]) and not store.saved
    run(store, "Add a line for Kamala after Nimal's: “Invented words”", edit_by_model(insert))
    block = options_of(store)
    assert block["options"][0]["ops"][0]["after_line_id"] == store.line_rows[0]["id"]  # after Nimal's line


def test_a_new_line_and_a_removed_line_are_staged_and_saved_when_chosen():
    store = store0()
    insert = {"op": "block.insert", "block": 2, "kind": "dialogue", "value": "Eat first", "speaker": "Kamala",
              "delivery": "flat"}
    run(store, "After Nimal's line add Kamala saying “Eat first”, flat", edit_by_model(insert))
    result = choose(store, options_of(store)["options"][0]["ops"])
    assert result.applied
    saved = store.saved[-1]
    assert [b["kind"] for b in saved["scene"]["script"]] == ["action", "dialogue", "dialogue", "action", "dialogue"]
    assert [ln["ord"] for ln in saved["lines"]] == [0, 1, 2] and saved["lines"][1]["text"] == "Eat first"
    assert saved["lines"][1]["character_id"] and saved["lines"][1]["delivery"] == "flat"
    assert all(s["number"] == n for n, s in enumerate(saved["shots"], start=1))
    # now take Kamala's last line out
    last = store.shots(PID)[-1]
    run(store, "Remove the last line", edit_by_model({"op": "block.remove", "block": 4}))
    chosen = choose(store, options_of(store)["options"][0]["ops"])
    assert chosen.applied
    assert store.saved[-1]["removed_lines"] and store.saved[-1]["lines"] and last["id"] not in {
        s["id"] for s in store.saved[-1]["shots"]}  # the shot that held only that line goes with it
    assert store.saved[-1]["scene"]["script_version"] == 3


# ── checks against the shots around it ─────────────────────────────────────────────────────


def test_a_staged_change_names_a_neighbour_that_still_uses_a_word_it_took_out():
    store = store0()
    store.line_rows[0]["text"] = "I am back, Amma. I want dinner, I'll wait"
    store.line_rows[1]["text"] = "Sit and eat your dinner, I'll serve it"
    run(store, 'S02 line: "I am home"')  # rules: no key
    notes = [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "continuity"]
    assert not any("i'll" in b["text"] for b in notes)  # a contraction is not something the story depends on
    assert any(b["text"] == "S04 still says “dinner”, which the change took out of S02." and b["shots"] == ["S04"]
               for b in notes)
    assert "S04" in options_of(store)["options"][0]["impact"]  # and the card says so before anyone applies it


def test_a_continuity_fix_rides_with_the_staged_change_and_is_pinned_to_its_shot():
    store = store0()
    responders = {"continuity_ops": lambda s, u: {"ops": [
        {"op": "beat.set", "shot": 3, "beat": 0, "field": "action", "value": "Kamala hears the plan and stirs on"}],
        "note": "S03 still works."}}
    run(store, ASK, edit_by_model(line_op(NEW_LINE), **responders))
    apply = options_of(store)["options"][0]
    fix = apply["ops"][1]
    assert fix["op"] == "beat.set" and fix["shot_id"] == store.shots(PID)[2]["id"] and "shot" not in fix
    assert "S03 beat 1: action" in apply["change"]
    choose(store, apply["ops"])
    assert store.saved[-1]["shots"][2]["beats"][0]["action"] == "Kamala hears the plan and stirs on"
    assert store.saved[-1]["scene"]["script_version"] == 2


def test_the_continuity_specialist_is_asked_about_the_impact_set_and_cannot_write_dialogue():
    store = store0()
    asked: list[str] = []

    def continuity(system: str, user: str) -> dict:
        asked.append(user)
        return {"ops": [{"op": "block.set", "block": 1, "field": "text", "value": "sneaky"}], "note": "x"}

    run(store, ASK, edit_by_model(line_op(NEW_LINE), continuity_ops=continuity))
    assert len(asked) == 1 and "Your task (S01, S02, S03): The script just changed" in asked[0]
    assert "You cannot change dialogue" in asked[0]
    ops = options_of(store)["options"][0]["ops"]
    assert len(ops) == 1 and ops[0]["value"] == NEW_LINE  # the agent's block.set was refused: person-only


# ── the rest of the script is applied now ──────────────────────────────────────────────────


def test_an_action_line_is_applied_checked_and_saved_with_the_script():
    store = store0()
    llm = edit_by_model({"op": "block.set", "block": 2, "field": "text", "value": "Kamala turns and looks at Nimal."},
                        continuity_ops=lambda s, u: {"ops": [], "note": "The beat still works."})
    run(store, "Make Kamala turn and look at Nimal in S03", llm)
    saved = store.saved[-1]
    assert saved["scene"]["script"][2] == {"kind": "action", "text": "Kamala turns and looks at Nimal.",
                                           "line_id": None}
    assert saved["scene"]["script_version"] == 2 and not saved["removed_lines"]
    message = store.message_rows[-1]
    assert message["ops"][0]["op"] == "block.set" and message["ops"][0]["kind"] == "action"
    assert any(c["phase"] == "director.continuity" for c in llm.calls)  # the impact set was reviewed
    assert any(b["kind"] == "edit-note" for b in message["blocks"])


def test_changing_who_is_in_a_shot_by_action_text_tells_the_person_what_goes_stale():
    store = store0()
    run(store, "Make S03 name Nimal", edit_by_model(
        {"op": "block.set", "block": 2, "field": "text", "value": "Nimal watches Kamala stir the pan."}))
    flags = [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "continuity"]
    assert any("Nimal is now in it" in b["text"] and "out of date" in b["text"] and b["shots"] == ["S03"]
               for b in flags)


def test_the_reaction_shot_the_director_inserts_now_saves_its_script_block():
    store = store0()
    run(store, "Add a reaction of Kamala after shot 2")  # rules: an insert op
    saved = store.saved[-1]
    assert len(saved["scene"]["script"]) == 5 and saved["scene"]["script_version"] == 2
    assert saved["scene"]["script"][2]["kind"] == "beat"
    assert [(s["block_start"], s["block_end"]) for s in saved["shots"]][2] == (2, 3)


def test_a_rule_based_line_change_needs_a_quoted_line_and_one_line_in_the_shot():
    store = store0()
    run(store, f'Change the line of S02 to "{NEW_LINE}"')  # no key: the rules path
    assert options_of(store)["options"][0]["ops"][0]["value"] == NEW_LINE
    again = store0()
    run(again, "Change the line of S02 to something warmer")
    assert not any(b["kind"] == "options" for b in again.message_rows[-1]["blocks"])


# ── a shot's marks ─────────────────────────────────────────────────────────────────────────


def test_canon_chips_ignored_checks_and_the_dop_note_are_applied_and_saved_on_the_shot():
    store = store0()
    run(store, "Put the brass pan in S01, ignore the axis check on S02 and note for S01 that the light is warm",
        edit_by_model({"op": "canon.add", "shot": 1, "value": "Brass pan"},
                      {"op": "check.waive", "shot": 2, "value": "axis"},
                      {"op": "dop_note.set", "shot": 1, "value": "the light is warm"}))
    shots = store.saved[-1]["shots"]
    assert PersonEdits.of(shots[0]).cast.add == [PAN] and PersonEdits.of(shots[0]).dop_note == "the light is warm"
    assert PersonEdits.of(shots[1]).waived_checks == ["axis"]
    assert "scene" in store.saved[-1] and "script" not in store.saved[-1]["scene"]  # the script was not touched
    assert shots[0]["version"] == 1  # marks are not material for a prompt's version
    text = store.message_rows[-1]["ops"]
    assert {o["op"] for o in text} == {"canon.add", "check.waive", "dop_note.set"}
    # they come back on the next read of the scene
    assert PersonEdits.of(store.shots(PID)[0]).dop_note == "the light is warm"


def test_a_role_that_cannot_edit_the_script_can_still_set_a_shots_marks():
    store = store0()
    run(store, "note for S01: warm", edit_by_model({"op": "dop_note.set", "shot": 1, "value": "warm"}),
        can_edit_script=False)
    assert PersonEdits.of(store.saved[-1]["shots"][0]).dop_note == "warm"
    saved = len(store.saved)
    llm = edit_by_model({"op": "block.set", "block": 0, "field": "text", "value": "x"})
    run(store, "edit the action", llm, can_edit_script=False)
    assert len(store.saved) == saved
    assert "Refused: your role can change shots but not the script's words" in llm.streamed[-1][1]["content"]


def test_time_and_words_are_edited_through_the_length_and_the_line():
    store = store0()
    run(store, "Make S02 eight seconds")  # Time is the shot's length
    assert store.saved[-1]["shots"][1]["duration_s"] == 8 and store.saved[-1]["shots"][1]["duration_locked"]
    assert [s["start_s"] for s in store.saved[-1]["shots"][1:3]] == [6, 14]  # the shots after it moved on


def test_options_cannot_carry_a_script_or_mark_change():
    from director_chat.engine import options

    llm = DirectorLLM({"chat_options": lambda s, u: {"question": "How?", "options": [
        {"label": "Rewrite it", "detail": "x", "ops": [{**{k: None for k in conductor_fields()}, "op": "block.set",
                                                         "block": 1, "field": "text", "value": "x"}], "prompt": ""},
        {"label": "Ask", "detail": "y", "ops": [], "prompt": "ask the board"},
        {"label": "Ask again", "detail": "z", "ops": [], "prompt": "ask again"}]}})
    from director_chat.engine.turn import kernel_for

    scene, lines, shots = fixture_scene(0)
    block = options.propose(lambda system, user: llm.json(tier="high", phase="p", system=system, user=user,
                                                         schema_name="chat_options", schema={}),
                            kernel=kernel_for(scene, lines, shots, None), message="m", history="", lead_charter="",
                            memory=[])
    assert block is not None and [o["label"] for o in block["options"]] == ["Ask", "Ask again"]


def conductor_fields() -> tuple[str, ...]:
    from director_chat.engine import conductor

    return conductor.OP_FIELDS


def test_the_reply_to_a_staged_change_is_exact_even_when_the_chat_says_lines_are_locked():
    store = store0()
    store.history = [{"id": "d1", "kind": "director", "speaker": "CT", "text": "",
                      "blocks": [{"kind": "text", "text": "Refused: the dialogue is locked to the approved script."}]},
                     {"id": "u1", "kind": "user", "speaker": "Dee", "text": f"S02 should say: {NEW_LINE}",
                      "blocks": []}]
    llm = edit_by_model(line_op(NEW_LINE))
    run(store, "do that change", llm)
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert text.startswith("I have not changed the script yet: S02 Nimal line → “") and "locked" not in text
    assert not llm.streamed  # no model wrote it
    conduct = next(c for c in llm.calls if c["phase"] == "director.conduct")
    person_messages = conduct["user"].split("<person_messages>")[1].split("</person_messages>")[0]
    assert f"- S02 should say: {NEW_LINE}" in person_messages
    assert "out of date" in conduct["system"] and "<person_messages>" in conduct["system"]


def test_ellipsis_spacing_and_a_typo_fixed_by_the_model_are_still_the_persons_words():
    typed = "@S01 i need to change dialogs to One day ... i definitely open my own restarunt"
    for value in ("One day ... i definitely open my own restarunt",  # as typed
                  "One day... I definitely open my own restaurant"):  # spacing and the typo fixed
        store = store0()
        run(store, typed, edit_by_model(line_op(value)))
        assert any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"]), value
    store = store0()
    run(store, typed, edit_by_model(line_op("One day I will open a grand restaurant by the sea")))  # new words
    assert not any(b["kind"] == "options" for b in store.message_rows[-1]["blocks"])
