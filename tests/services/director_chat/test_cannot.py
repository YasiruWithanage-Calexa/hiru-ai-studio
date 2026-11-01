"""Phase 1 of plan/2026-11-01c: a request the chat cannot meet is said so (lane `cannot`), with the reason and
the route, and a reply never offers to do something later when nothing can be confirmed. Since Phase 4 the
dialogue in another language is the translator's (tests/services/director_chat/test_translate.py); what is left
here is what no agent can do (writing dialogue, canon, rendering), and the translator being unavailable."""
from __future__ import annotations

import pytest
from director_chat.engine import conductor, proposals, turn

from contracts import director_capabilities as caps
from tests.services.director_chat.conftest import DirectorLLM
from tests.services.director_chat.test_turn import plan_answer, run, store0

SINHALA = "i need all dialogues in Sinhala language"
WRITE = "write better dialogue for Kamala in this scene"
CANON = caps.by_id("canon.change")
ROUTE = CANON.route
DOWN = caps.TRANSLATOR_DOWN


def cannot_answer(request: str = WRITE, **kw) -> dict:
    return {**plan_answer("cannot"), "cannot": {"request": request, "reason": "no", "route": "a made-up route", **kw}}


def last_text(store) -> dict:
    return store.message_rows[-1]["blocks"][0]


# ── the conductor ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("message", [
    SINHALA,
    "keep all other settings the same, only change the dialogue to Sinhala, i confirm it",
    "no still dialogues are in english",
    "Translate the lines into Sinhala please",
    "can you translate the dialogue to sinhala?",
])
def test_without_the_translator_a_request_for_another_language_is_cannot_with_the_route_to_script_edit(message: str):
    plan = conductor.by_rules(message, split_points={})
    assert plan.lane == "cannot" and not plan.ops
    assert plan.cannot == {"id": DOWN.id, "request": message.strip(), "reason": DOWN.reason, "route": DOWN.route}
    assert "Script" in DOWN.route


@pytest.mark.parametrize("message", [
    "Why are the lines in English?", "What language is the dialogue in?", "Change Kamala's line to 'sit down and eat'",
    "make shot 2 eight seconds", "Remember: Kamala never cries on screen.", "do it",
])
def test_rules_leave_everything_else_alone(message: str):
    assert conductor.by_rules(message, split_points={}, translator=True).lane not in ("cannot", "translate")


def test_a_model_cannot_with_a_route_keeps_the_models_words_and_drops_any_operations():
    answer = {**cannot_answer(request="paint the sky", reason="I plan shots.", route="Use Production."),
              "ops": [{**{k: None for k in conductor.OP_FIELDS}, "op": "remove", "shot": 1}]}
    plan = conductor.by_model(lambda s, u: answer, plan_text="", message="paint the sky green", history="",
                              memory=[])
    assert plan.lane == "cannot" and not plan.ops
    assert plan.cannot == {"request": "paint the sky", "reason": "I plan shots.", "route": "Use Production."}


def test_a_model_cannot_with_nothing_filled_in_still_gives_the_generic_refusal():
    plan = conductor.by_model(lambda s, u: {**plan_answer("cannot"), "cannot": None}, plan_text="",
                              message="paint the sky green", history="", memory=[])
    assert plan.cannot and plan.cannot["reason"] == caps.GENERIC.reason and plan.cannot["route"] == caps.GENERIC.route


def test_the_conductor_schema_is_strict_and_knows_the_lanes():
    props, required = conductor.SCHEMA["properties"], conductor.SCHEMA["required"]
    assert {"cannot", "translate"} <= set(conductor.LANES) and set(required) == set(props)
    assert props["lane"]["enum"] == list(conductor.LANES)
    shapes = (("cannot", {"request", "reason", "route"}), ("translate", {"language", "code", "style", "shots"}))
    for name, keys in shapes:
        branches = props[name]["anyOf"]
        assert {"type": "null"} in branches
        inner = next(b for b in branches if b.get("type") == "object")
        assert set(inner["required"]) == set(inner["properties"]) == keys


def test_translating_is_no_longer_listed_as_impossible_but_writing_dialogue_still_is():
    ids = {n.id for n in caps.NOT_HERE}
    assert "dialogue.translate" not in ids and "dialogue.write" in ids
    assert "dialogue.translate" in {c.id for c in caps.CAPABILITIES}
    assert "Translate spoken lines" in caps.render_for_prompt("reply")


# ── the turn, with and without a key ───────────────────────────────────────────────────────


def test_without_a_key_the_reply_names_the_reason_and_the_route_and_changes_nothing():
    store = store0()
    events = run(store, SINHALA)
    assert events[-1] == ("done", {"message_id": store.message_rows[-1]["id"], "lane": "cannot"})
    assert not store.saved and store.message_rows[-1]["ops"] == []
    text = last_text(store)
    assert DOWN.reason in text["text"] and DOWN.route in text["text"]
    assert text["advice"] is False and text["route"] == DOWN.route  # a later "do it" has nothing to follow up


def test_with_a_key_the_ledger_ends_with_what_is_not_possible_and_the_prompt_carries_the_registry():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: cannot_answer(route=ROUTE)}, reply="I plan shots, not dialogue.")
    run(store, WRITE, llm)
    reply_call = next(c for c in llm.calls if c["phase"] == "director.reply")
    assert reply_call["system"] == turn.REPLY_SYSTEM and caps.render_for_prompt("reply") in reply_call["system"]
    assert reply_call["user"].rstrip().endswith("The person can: " + ROUTE + "\n</turn>")


@pytest.mark.parametrize("promise", [
    "If you want that, confirm and we'll switch all the dialogue.",
    "Ready to apply when you are.",
    "Say the word and I'll apply it.",
    "I'll apply it as soon as you say so.",
    "Just confirm and we will switch every line.",
])
def test_a_reply_that_only_promises_is_replaced_by_the_plain_reason_and_route(promise: str):
    store = store0()
    run(store, WRITE, DirectorLLM({"turn_plan": lambda s, u: cannot_answer(reason="I can't write dialogue.",
                                                                          route=ROUTE)}, reply=promise))
    text = last_text(store)["text"]
    assert promise not in text and ROUTE in text


def test_the_guard_strips_the_five_phrasings_when_nothing_can_be_confirmed_and_keeps_them_when_a_card_waits():
    phrasings = ["Confirm and we'll switch it.", "Say the word.", "Ready to apply when you are.",
                 "I'll apply it now.", "We'll switch the lines."]
    for phrase in phrasings:
        text = f"S02 runs 6 s. {phrase}"
        assert proposals.guard_reply(text, has_card=False) == "S02 runs 6 s."
        assert proposals.guard_reply(text, has_card=True) == text  # a card is waiting: the offer is true
        assert proposals.guard_reply(text, has_card=False, pending=True) == text  # or a pending action is
    assert proposals.guard_reply("The scene runs 44 s in 4 shots.", has_card=False) == "The scene runs 44 s in 4 shots."


def test_an_ordinary_answer_keeps_its_wording_when_the_guard_has_nothing_to_remove():
    text = "Done. S02 now holds on Nimal.\nIt reads cleaner."
    assert proposals.guard_reply(text, has_card=False) == text


def test_the_reply_no_longer_has_to_open_with_nothing_changed():
    assert "say that nothing changed" in turn.REPLY_SYSTEM and "Lead with the answer" in turn.REPLY_SYSTEM
    assert "Nothing changed this turn" not in turn.REPLY_SYSTEM
