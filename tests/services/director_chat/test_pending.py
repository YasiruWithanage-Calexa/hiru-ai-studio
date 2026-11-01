"""Phase 2 of plan/2026-11-01c: "i confirm", "do it" and "apply it" are answered in code. With a pending action
open they apply it (the card's own edit, through the same code as the button); with none they say so."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from director_chat.engine import pending, proposals, turn

from tests.services.director_chat.conftest import DirectorLLM, FakeStore
from tests.services.director_chat.test_turn import payload, plan_answer, run, store0
from tests.services.director_chat.test_turn_script import ASK, NEW_LINE, options_of

NOTHING = "There is nothing waiting to apply."


def say(store: FakeStore, text: str, llm: DirectorLLM | None = None, **kw) -> list:
    """A turn in the store's one thread (so a pending action from an earlier turn is this thread's)."""
    if not hasattr(store, "thread"):
        store.thread = uuid4()
    req = payload(store, text, **kw).model_copy(update={"thread_id": store.thread})
    events = list(turn.run(req, store, llm or DirectorLLM(enabled=False)))
    # the API would now hold this turn's messages: the person's and the director's
    store.history += [{"id": str(req.user_message_id), "kind": "user", "speaker": "Dee", "text": text, "blocks": []},
                      store.message_rows[-1]]
    return events


def staged(store: FakeStore) -> dict:
    """A script change staged as a card → the stored director message."""
    say(store, ASK)
    return store.message_rows[-1]


confirm = say


@pytest.fixture
def waiting() -> FakeStore:
    store = store0()
    staged(store)
    return store


def last_reply(store: FakeStore) -> dict:
    return store.message_rows[-1]["blocks"][0]


# ── a card that offers one edit leaves a pending action ────────────────────────────────────


def test_a_staged_card_leaves_one_open_pending_action_pinned_to_its_card_and_option(waiting: FakeStore):
    (row,) = waiting.pending_rows
    message = waiting.message_rows[0]
    assert row["status"] == "open" and row["message_id"] == message["id"]
    card = options_of(waiting)
    assert row["block"] == message["blocks"].index(card) and row["option"] == 0
    assert row["ops"] == card["options"][0]["ops"] and row["label"] == "Apply this change"
    expires = datetime.fromisoformat(row["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)


def test_a_card_of_several_edits_or_none_leaves_nothing_to_confirm():
    block = {"kind": "options", "options": [{"label": "A", "ops": [{"op": "retime"}]},
                                            {"label": "B", "ops": [{"op": "merge"}]}]}
    none = {"kind": "options", "options": [{"label": "Keep", "ops": [], "prompt": "ask"}]}
    for blocks in ([block], [none], []):
        assert pending.for_card({"id": "m", "blocks": blocks}, production_id=1, thread_id=2, scene_id=3,
                                user_id=4) is None


# ── confirming ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["i confirm it", "do it", "apply it", "do it right now",
                                  "keep all other settings the same, i confirm it", "go ahead and do it", "yes"])
def test_a_confirmation_applies_the_pending_edit_as_the_button_would(text: str, waiting: FakeStore):
    events = confirm(waiting, text)
    names = [e for e, _ in events]
    assert "plan" in names and names[-2:] == ["message", "done"] and events[-1][1]["lane"] == "edit"
    assert waiting.saved and waiting.line_rows[0]["text"] == NEW_LINE
    reply = last_reply(waiting)
    assert reply["text"].startswith("Applied: S02 Nimal line → “") and reply["advice"] is False
    # the card records the choice and its effect; the pending action is closed
    card = waiting.message_rows[0]["blocks"][1]
    assert card["chosen"] == 0 and card["outcome"].startswith("Applied:")
    assert "Changed dialogue on 1 line." in card["outcome"]
    assert waiting.pending_rows[0]["status"] == "applied"
    assert waiting.message_rows[-1]["ops"][0]["op"] == "block.set"
    assert waiting.audits[-1]["action"] == "scene.director_choice"


def test_the_confirmation_is_read_in_code_whatever_the_model_says(waiting: FakeStore):
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, reply="I will think about it.")
    confirm(waiting, "do it", llm)
    assert waiting.line_rows[0]["text"] == NEW_LINE and "director.reply" not in [c["phase"] for c in llm.calls]


def test_confirming_twice_applies_once_and_then_says_nothing_is_waiting(waiting: FakeStore):
    confirm(waiting, "i confirm it")
    before = len(waiting.saved)
    confirm(waiting, "i confirm it")
    assert len(waiting.saved) == before and last_reply(waiting)["text"].startswith(NOTHING)


def test_a_role_without_edit_script_is_refused_and_nothing_is_applied(waiting: FakeStore):
    confirm(waiting, "i confirm it", can_edit=True, can_edit_script=False)
    assert not len(waiting.saved) and waiting.line_rows[0]["text"] != NEW_LINE
    assert "writer" in last_reply(waiting)["text"] and waiting.pending_rows[0]["status"] == "open"
    assert waiting.message_rows[0]["blocks"][1].get("chosen") is None  # the card still waits for someone who may


def test_a_writer_cannot_confirm_a_card_that_also_changes_shots(waiting: FakeStore):
    """As the button: each shot-list operation needs DIRECT, even next to a script one EDIT_SCRIPT allows."""
    shot = sorted(waiting.shot_rows, key=lambda s: s["number"])[1]
    waiting.pending_rows[0]["ops"] = [*waiting.pending_rows[0]["ops"],
                                      {"op": "retime", "shot_id": shot["id"], "seconds": 8}]
    confirm(waiting, "i confirm it", can_edit=False, can_edit_script=True)
    assert not waiting.saved and waiting.line_rows[0]["text"] != NEW_LINE
    assert "comment but not make this change" in last_reply(waiting)["text"]
    assert waiting.pending_rows[0]["status"] == "open"


def test_a_viewer_is_refused_too(waiting: FakeStore):
    confirm(waiting, "i confirm it", can_edit=False, can_edit_script=False)
    assert not waiting.saved and "comment but not make this change" in last_reply(waiting)["text"]


# ── nothing waiting ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["i confirm it", "do it", "apply it", "do it right now",
                                  "keep all other settings the same, i confirm it"])
def test_a_confirmation_with_nothing_waiting_gets_the_fixed_reply_and_no_model_call(text: str):
    store, llm = store0(), DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")})
    say(store, text, llm)
    reply = last_reply(store)
    assert reply["text"] == NOTHING and reply["advice"] is False and not store.saved
    assert [c["phase"] for c in llm.calls] == ["director.conduct"]  # only the reading of the message, no reply model


def test_the_fixed_reply_repeats_the_route_of_the_last_unmet_request():
    store = store0()
    say(store, "i need all dialogues in Sinhala language")
    refusal = store.message_rows[-1]
    say(store, "i confirm it")
    again = last_reply(store)
    route = refusal["blocks"][0]["route"]
    assert again["text"] == f"{NOTHING} {route}" and again["route"] == route


def test_a_refusal_is_not_advice_for_a_later_do_it():
    store = store0()
    say(store, "i need all dialogues in Sinhala language")
    assert proposals.latest_advice(store.history) is None
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")})
    say(store, "do it", llm)
    assert last_reply(store)["text"].startswith(NOTHING) and not store.saved


def test_an_expired_pending_action_is_closed_and_not_applied(waiting: FakeStore):
    waiting.pending_rows[0]["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    confirm(waiting, "i confirm it")
    # typing a confirmation no longer applies it; the card itself still waits for a click
    assert not waiting.saved and last_reply(waiting)["text"] == turn.WAITING_ON_CARD
    assert waiting.pending_rows[0]["status"] == "expired"


def test_a_pending_action_whose_card_was_chosen_meanwhile_is_not_applied(waiting: FakeStore):
    waiting.message_rows[0]["blocks"][1]["chosen"] = 1  # "Keep it as it is", clicked in the browser
    confirm(waiting, "i confirm it")
    assert not waiting.saved and last_reply(waiting)["text"].startswith(NOTHING)
    assert waiting.pending_rows[0]["status"] == "closed"


def test_a_newer_card_supersedes_the_older_pending_action():
    store = store0()
    staged(store)
    first = store.pending_rows[0]
    say(store, "Change the dialogue of S04 to “Eat first”")
    assert first["status"] == "superseded"
    assert [p["status"] for p in store.pending_rows] == ["superseded", "open"]
    assert len([p for p in store.pending_rows if p["status"] == "open"]) == 1


def test_a_store_without_the_table_means_nothing_waits(waiting: FakeStore):
    def broken(thread_id):
        raise RuntimeError("relation public.pending_actions does not exist")

    waiting.open_pending = broken  # type: ignore[method-assign]
    confirm(waiting, "i confirm it")
    assert not waiting.saved and last_reply(waiting)["text"] == turn.WAITING_ON_CARD  # the button still works


def test_a_bare_yes_with_nothing_waiting_is_not_answered_with_the_fixed_reply():
    store = store0()
    run(store, "ok")
    assert last_reply(store)["text"] != NOTHING


def test_a_confirmation_that_names_an_edit_is_that_edit_not_a_confirmation():
    store = store0()
    run(store, "make shot 2 eight seconds, i confirm it")
    assert store.saved and store.message_rows[-1]["ops"][0]["op"] == "retime"


def test_the_replies_of_a_turn_that_applied_nothing_cannot_promise_a_pending_action_that_is_not_there():
    store = store0()
    reply = "It runs 44 s. Say the word and I'll apply it."
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, reply=reply)
    run(store, "How long does the scene run?", llm)
    assert "Say the word" not in last_reply(store)["text"]
