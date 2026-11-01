"""Phase 5 of plan/2026-11-01c: the loop breaker. Every reply records the goal it was asked for and whether it
was met; the same unmet goal on the next turn is answered in code ("the card above is waiting", or what cannot be
done and the route), not tried again, and a click on the card ends the run."""
from __future__ import annotations

from director_chat.engine import loop

from tests.services.director_chat.conftest import DirectorLLM, FakeStore
from tests.services.director_chat.test_pending import say
from tests.services.director_chat.test_translate import ASK, SI, TA, conduct, english_store, llm_for
from tests.services.director_chat.test_turn import plan_answer

CANON_ROUTE = "Open Canon, change the character there, then ask me to look at the shots again."
CANON = "make Kamala look ten years older"


def goal_block(store: FakeStore) -> dict:
    return store.message_rows[-1]["blocks"][0]


def cannot_llm() -> DirectorLLM:
    answer = {**plan_answer("cannot"), "cannot": {"request": CANON, "reason": "Characters are kept in the Canon.",
                                                  "route": CANON_ROUTE}}
    return DirectorLLM({"turn_plan": lambda s, u: answer}, reply="Characters are kept in the Canon.")


def calls(llm: DirectorLLM, schema: str) -> int:
    return sum(c["schema"] == schema for c in llm.calls)


# ── the record ──────────────────────────────────────────────────────────────────────────────


def test_a_reply_records_the_goal_it_was_asked_for_and_that_it_is_not_met_yet():
    store = english_store()
    say(store, ASK, llm_for(store))
    assert goal_block(store)["goal"] == "dialogue.si" and goal_block(store)["met"] is False


def test_a_reply_with_no_goal_records_none():
    store = english_store()
    say(store, "make shot 2 eight seconds")
    assert "goal" not in goal_block(store) or goal_block(store)["goal"] == ""


def test_a_request_that_is_already_true_is_recorded_as_met():
    store = FakeStore(*__import__("tests.services.director_chat.conftest", fromlist=["fixture_scene"]).fixture_scene(0))
    say(store, ASK, llm_for(store))  # the fixture script is Sinhala
    assert goal_block(store)["goal"] == "dialogue.si" and goal_block(store)["met"] is True


def test_the_goal_of_a_refusal_is_its_route_so_a_reworded_request_is_the_same_goal():
    a = loop.cannot_goal({"route": CANON_ROUTE})
    b = loop.cannot_goal({"route": CANON_ROUTE.upper()})
    assert a == b and a.startswith("cannot:") and loop.cannot_goal({"route": "Use Production."}) != a


# ── a translation asked for again ───────────────────────────────────────────────────────────


def test_asking_again_while_the_card_waits_gets_the_fixed_reply_and_no_new_card_or_model_call():
    store = english_store()
    say(store, ASK, llm_for(store))
    llm = llm_for(store)
    say(store, ASK, llm)
    assert goal_block(store)["text"] == loop.WAITING and store.message_rows[-1]["ops"] == []
    assert not [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"]
    assert calls(llm, "dialogue_translation") == 0 and calls(llm, "stream") == 0 and calls(llm, "tools") == 0
    assert goal_block(store)["goal"] == "dialogue.si" and goal_block(store)["met"] is False


def test_the_third_and_every_later_repeat_gets_the_same_reply_not_a_new_card():
    store = english_store()
    say(store, ASK, llm_for(store))
    for _ in range(3):
        say(store, ASK, llm_for(store))
        assert goal_block(store)["text"] == loop.WAITING
        assert not [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"]
    assert not store.saved


def test_a_different_language_is_a_new_request_and_gets_its_own_card():
    store = english_store()
    say(store, ASK, llm_for(store))
    say(store, "translate the dialogue to Tamil", llm_for(store, [TA, TA], code="ta", language="Tamil"))
    assert card_options(store) and goal_block(store)["goal"] == "dialogue.ta"


def card_options(store: FakeStore) -> list:
    return [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"]


def test_choosing_keep_ends_the_run_and_asking_again_is_a_new_request():
    store = english_store()
    say(store, ASK, llm_for(store))
    card = next(b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options")
    card["chosen"], card["outcome"] = 1, "Kept as it is."  # the person clicked Keep
    store.close_pending(store.thread, "closed")
    say(store, ASK, llm_for(store))
    assert card_options(store) and goal_block(store)["text"] != loop.WAITING


def test_applying_the_card_ends_the_run_too():
    store = english_store()
    say(store, ASK, llm_for(store))
    say(store, "i confirm it", llm_for(store))
    assert [ln["text"] for ln in store.line_rows] == SI
    say(store, ASK, llm_for(store))  # now true: said so, not looped
    assert goal_block(store)["text"] == "Every spoken line there is already in Sinhala."


# ── something the chat cannot do, asked for again ───────────────────────────────────────────


def test_a_refusal_asked_again_names_the_route_and_does_not_call_a_reply_model():
    store = english_store()
    say(store, CANON, cannot_llm())
    first = goal_block(store)
    assert first["route"] == CANON_ROUTE and first["goal"].startswith("cannot:") and first["met"] is False
    llm = cannot_llm()
    say(store, CANON, llm)
    again = goal_block(store)
    assert again["text"].endswith(loop.AGAIN) and CANON_ROUTE in again["text"]
    assert again["goal"] == first["goal"] and again["route"] == CANON_ROUTE and again["advice"] is False
    assert calls(llm, "stream") == 0 and calls(llm, "tools") == 0
    say(store, CANON, cannot_llm())  # and the third time
    assert goal_block(store)["text"] == again["text"]


def test_something_else_in_between_ends_the_run():
    store = english_store()
    say(store, CANON, cannot_llm())
    say(store, "make shot 2 eight seconds")
    say(store, CANON, cannot_llm())
    assert not goal_block(store)["text"].endswith(loop.AGAIN)


def test_the_unit_repeats_only_over_replies_that_carry_the_same_unmet_goal():
    def reply(goal: str, met: bool = False, *, chosen: bool = False) -> dict:
        blocks: list = [{"kind": "text", "text": "x", "goal": goal, "met": met}]
        if chosen:
            blocks.append({"kind": "options", "options": [], "chosen": 0})
        return {"kind": "director", "blocks": blocks}

    assert loop.repeated([reply("dialogue.si")], "dialogue.si")
    assert not loop.repeated([reply("dialogue.si")], "dialogue.ta")
    assert not loop.repeated([reply("dialogue.si", True)], "dialogue.si")
    assert not loop.repeated([reply("dialogue.si", chosen=True)], "dialogue.si")
    assert loop.repeated([reply("dialogue.si"), reply("dialogue.si")], "dialogue.si")
    assert not loop.repeated([reply("dialogue.si", chosen=True), reply("dialogue.si")], "dialogue.si")
    assert not loop.repeated([reply("dialogue.si"), reply("")], "dialogue.si")
    assert not loop.repeated([], "dialogue.si") and not loop.repeated([reply("dialogue.si")], "")


def test_conduct_helper_matches_the_conductors_translate_shape():
    assert conduct()["translate"] == {"language": "Sinhala", "code": "si", "style": "", "shots": []}
