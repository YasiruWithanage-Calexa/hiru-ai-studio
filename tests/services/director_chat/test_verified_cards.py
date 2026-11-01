"""Phase 3 of plan/2026-11-01c: a card is what its edit does. An option whose label promises a goal its
operations cannot reach is not shown; one that lost operations is relabelled from what is left; a chosen
card records its EFFECT; and a reply says a change was made only when a receipt or the scene shows it."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from director_chat.engine import choice, options, proposals, turn
from director_chat.engine.turn import kernel_for

from contracts import director_capabilities as caps
from contracts.director import ChoicePayload
from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore
from tests.services.director_chat.test_turn import plan_answer, run, store0

SI = "අම්මේ, මම ආපහු ආවා."
EN = "Mother, I am back."


def english_store() -> FakeStore:
    store = store0()
    store.line_rows[0]["text"], store.line_rows[1]["text"] = EN, "Sit down and eat."
    return store


def kernel_of(store: FakeStore):
    return kernel_for(store.scene_row, store.line_rows, store.shot_rows, None, store.canon(PID))


def frame(shot: int, value: str) -> dict:
    return {"op": "set", "shot": shot, "field": "framing", "value": value}


def note(shot: int, text: str = "Speak in Sinhala.") -> dict:
    return {"op": "beat.set", "shot": shot, "beat": 0, "field": "director_line", "value": text}


def propose(store: FakeStore, *raw: dict) -> dict | None:
    answer = {"question": "How should it play?",
              "options": [{"label": "x", "detail": "d", "ops": [], "prompt": "", "intent": "", **r} for r in raw]}
    return options.propose(lambda s, u: answer, kernel=kernel_of(store), message="options", history="",
                           lead_charter="", memory=[], at_least=1)


# ── the options writer: a label may not promise what the edit does not do ───────────────────


def test_a_label_that_promises_sinhala_dialogue_is_dropped_when_only_director_notes_make_it():
    store = english_store()
    card = propose(store,
                   {"label": "Switch all dialogue to Sinhala", "ops": [note(2), note(4)]},  # the Scene 2 card
                   {"label": "Push in to a tight CU", "ops": [frame(2, "CU")]})
    assert card and [o["label"] for o in card["options"]] == ["Push in to a tight CU"]


def test_the_model_naming_the_goal_is_held_to_it_too():
    store = english_store()
    card = propose(store, {"label": "Let the lines land in her language", "intent": "dialogue.si", "ops": [note(2)]})
    assert card is None


def test_a_goal_only_an_edit_can_reach_cannot_be_promised_by_a_message():
    store = english_store()
    ask = "Please translate every line into Sinhala."
    assert propose(store, {"label": "Translate the lines", "prompt": ask}) is None


def test_an_option_that_only_looks_like_the_claim_is_not_mistaken_for_it():
    store = english_store()
    card = propose(store, {"label": "Slow the pace of Sinhala lines", "ops": [note(2, "Hold the pause.")]})
    (opt,) = card["options"]
    assert opt["label"] == "Slow the pace of Sinhala lines" and opt["intent"] == ""


def test_an_option_that_lost_an_operation_is_relabelled_from_what_is_left():
    store = english_store()
    # a person's own words: an option may not carry them
    line = {"op": "block.set", "block": 1, "field": "text", "value": "Sit down.", "kind": "dialogue"}
    card = propose(store, {"label": "Tighten S02 and rewrite its line", "detail": "Shorter line, closer frame.",
                           "ops": [frame(2, "CU"), line]})
    (opt,) = card["options"]
    assert opt["label"] == "S02 framing → CU" and opt["detail"] == "" and opt["change"] == "S02 framing → CU"
    assert [o["op"] for o in opt["ops"]] == ["set"]


def test_an_option_that_keeps_all_its_operations_keeps_its_label():
    store = english_store()
    card = propose(store, {"label": "Close on Nimal", "detail": "Tight and warm.",
                           "ops": [frame(2, "CU")]})
    assert card["options"][0]["label"] == "Close on Nimal" and card["options"][0]["detail"] == "Tight and warm."


def test_a_framing_goal_needs_a_framing_operation():
    store = english_store()
    framed = propose(store, {"label": "Go tight", "intent": "shot.framing",
                             "ops": [frame(2, "CU")]})
    assert framed["options"][0]["intent"] == "shot.framing"
    assert propose(store, {"label": "Go tight", "intent": "shot.framing", "ops": [note(2, "Push in slowly.")]}) is None


def test_the_options_schema_asks_for_the_goal_and_its_prompt_explains_it():
    item = options.SCHEMA["properties"]["options"]["items"]
    assert "intent" in item["required"]
    assert item["properties"]["intent"]["enum"] == ["", *(i.id for i in caps.INTENTS)]
    assert {"dialogue.si", "dialogue.ta", "dialogue.en", "shot.framing"} <= set(item["properties"]["intent"]["enum"])
    assert "dialogue.si" in options.SYSTEM and "<<" not in options.SYSTEM


def test_the_goal_checks_read_the_script_not_the_label():
    items = kernel_of(english_store()).items
    assert caps.met("dialogue.si", items=items)[0] is False
    assert caps.met("dialogue.si", items=items)[1] == "0 of 2 spoken lines are in Sinhala."
    assert caps.met("dialogue.si", items=kernel_of(store0()).items)[0] is True  # the fixture script is Sinhala
    assert caps.met("dialogue.si", items=[])[0] is False  # no lines, nothing reached
    assert caps.met("nothing.we.know", items=items) == (True, "")
    assert (caps.script_of(SI), caps.script_of(EN), caps.script_of("Amma මම")) == ("si", "en", "mixed")


# ── a chosen card records its effect ────────────────────────────────────────────────────────


def choose(store: FakeStore, ops: list[dict], intent: str = "") -> choice.ChoiceResult:
    scene_id = UUID(store.scene_row["id"])
    payload = ChoicePayload(production_id=PID, scene_id=scene_id, actor_user_id=uuid4(), can_edit_script=True, ops=ops,
                            intent=intent)
    return choice.apply_choice(payload, store)


def pinned_notes(store: FakeStore, *shots: int) -> list[dict]:
    handles = kernel_of(store).handles()
    return [{"op": "beat.set", "shot_id": handles[n - 1], "beat": 0, "field": "director_line",
             "value": "Speak in Sinhala."} for n in shots]


def test_a_card_of_director_notes_says_so_and_that_the_words_are_unchanged():
    store = english_store()
    result = choose(store, pinned_notes(store, 2, 4))
    assert result.applied and "Changed director notes on 2 shots. Dialogue words unchanged." in result.summary
    assert "Dialogue words unchanged" in result.summary and "Changed dialogue" not in result.summary
    assert store.line_rows[0]["text"] == EN


def test_a_goal_the_saved_scene_does_not_reach_is_said_not_implied():
    store = english_store()
    result = choose(store, pinned_notes(store, 2, 4), intent="dialogue.si")
    goal = "Goal NOT reached (every spoken line is in Sinhala): 0 of 2 spoken lines are in Sinhala."
    assert result.applied and goal in result.summary


def line_ops(store: FakeStore, texts: list[str]) -> list[dict]:
    return [{"op": "block.set", "line_id": ln["id"], "field": "text", "value": t, "was": ln["text"], "kind": "dialogue"}
            for ln, t in zip(store.line_rows, texts, strict=True)]


def test_a_card_that_changes_the_words_says_how_many_lines_and_reaches_its_goal():
    store = english_store()
    sinhala = [SI, "කෑම කන්න වාඩි වෙන්න."]
    result = choose(store, line_ops(store, sinhala), intent="dialogue.si")
    assert result.applied and "Changed dialogue on 2 lines." in result.summary
    assert "Goal reached: every spoken line is in Sinhala." in result.summary
    assert [ln["text"] for ln in store.line_rows] == sinhala


def test_a_card_that_changes_one_of_two_lines_does_not_reach_the_goal():
    store = english_store()
    result = choose(store, line_ops(store, [SI, "Sit down and eat."])[:1], intent="dialogue.si")
    assert "Changed dialogue on 1 line." in result.summary and "Goal NOT reached" in result.summary
    assert "1 of 2 spoken lines are in Sinhala" in result.summary


def test_a_card_that_changes_only_a_framing_has_no_effect_sentence_to_add():
    assert choice.effect([{"op": "set", "field": "framing", "shot_id": "x"}]) == ""


def test_history_shows_a_chosen_cards_effect_and_says_when_none_was_recorded():
    def message(outcome: str) -> dict:
        return {"kind": "director", "blocks": [{"kind": "options", "question": "Q?", "chosen": 0, "outcome": outcome,
                                                "options": [{"label": "Switch all dialogue to Sinhala"}]}]}

    shown = turn._blocks_text(message("Applied: S02 beat 1: director line. Changed director notes on 1 shot. "
                                      "Dialogue words unchanged."))
    assert 'The person chose "Switch all dialogue to Sinhala". Applied: S02 beat 1' in shown
    assert "Dialogue words unchanged." in shown
    assert "Its effect was not recorded." in turn._blocks_text(message(""))


# ── what the reply may say about the scene ──────────────────────────────────────────────────


def chosen_card(label: str, outcome: str) -> list[dict]:
    """A director message in the thread whose card the person chose, with the effect recorded on it."""
    return [{"kind": "director", "id": "h", "speaker": "CT", "blocks": [
        {"kind": "options", "question": "Q", "chosen": 0, "options": [{"label": label}], "outcome": outcome}]}]


def asked_with_reply(store: FakeStore, reply: str, history: list[dict] | None = None):
    store.history = history or []
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, reply=reply)
    run(store, "so are the lines in Sinhala now?", llm)
    return llm, store.message_rows[-1]["blocks"][0]["text"]


def test_the_reply_is_given_the_scene_as_it_stands_computed_without_a_model():
    llm, _ = asked_with_reply(english_store(), "They are in English.")
    ledger = llm.tool_rounds[-1][1]["content"].split("<turn>")[1]
    assert "Scene now: Right now 2 spoken lines: 2 in English." in ledger and "Runs " in ledger


def test_a_claim_with_no_receipt_is_replaced_by_the_state_of_the_scene():
    _, text = asked_with_reply(english_store(), "Your earlier Sinhala switch is already applied. S02 runs 6 s.")
    assert "already applied" not in text and "Right now 2 spoken lines: 2 in English." in text
    assert "S02 runs 6 s." in text  # the rest of the answer stands


def test_a_claim_about_dialogue_is_not_backed_by_a_card_that_only_changed_notes():
    history = chosen_card("Switch all dialogue to Sinhala", "Applied: S02 beat 1: director line. "
                          "Changed director notes on 1 shot. Dialogue words unchanged.")
    _, text = asked_with_reply(english_store(), "The switch to Sinhala has been applied.", history)
    assert "has been applied" not in text and "2 in English" in text


def test_a_claim_is_kept_when_the_chosen_cards_effect_says_it():
    history = chosen_card("Apply this change", "Applied: S02 line. Changed dialogue on 1 line.")
    _, text = asked_with_reply(english_store(), "That change to the line has been applied.", history)
    assert text == "That change to the line has been applied."


def test_a_claim_is_kept_when_the_scene_itself_is_in_sinhala():
    _, text = asked_with_reply(store0(), "Yes, the lines are now in Sinhala.")  # the fixture script is Sinhala
    assert text == "Yes, the lines are now in Sinhala."


def test_a_claim_is_kept_when_this_turn_applied_the_change():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 8}])},
                      reply="Done. S02 is now 8 s.")
    run(store, "make shot 2 eight seconds", llm)
    assert store.message_rows[-1]["blocks"][0]["text"] == "Done. S02 is now 8 s."


def test_a_bare_done_with_nothing_applied_is_not_left_standing():
    _, text = asked_with_reply(store0(), "Done.")
    assert text and text != "Done."


@pytest.mark.parametrize("claim, dialogue, kept", [
    ("The lines are now in Tamil.", "ta", True),
    ("The lines are now in Tamil.", "si", False),
    ("Everything has been switched from English to Tamil.", "ta", True),
    ("Everything has been switched from English to Tamil.", "en", False),
])
def test_a_claim_about_any_known_language_is_checked_against_the_scene(claim: str, dialogue: str, kept: bool):
    out = proposals.guard_reply(claim, has_card=False, receipts=proposals.Receipts(dialogue=dialogue),
                                state_fact="Right now 2 spoken lines.")
    assert (out == claim) is kept


def test_the_claim_wording_does_not_catch_a_statement_of_state():
    r = proposals.Receipts()
    for fine in ("S02 is now 8 s long.", "The scene runs 44 s.", "Nothing is waiting to apply."):
        assert proposals.guard_reply(fine, has_card=False, receipts=r) == fine


@pytest.mark.parametrize("claim", ["It's already applied.", "That has been switched.", "I've changed S02.",
                                   "Everything is now in Sinhala.", "All the lines are now in Tamil.",
                                   "The dialogue is already in Hindi."])
def test_claims_without_receipts_are_caught(claim: str):
    out = proposals.guard_reply(claim, has_card=False, receipts=proposals.Receipts(dialogue="en"),
                                state_fact="Right now 2 spoken lines: 2 in English.")
    assert out == "Right now 2 spoken lines: 2 in English."
