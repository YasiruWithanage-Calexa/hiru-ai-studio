"""The sable_chat system (plan/2026-11-08 Phase 5): read → loop → guard → save, streamed, on fake models."""
from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from contracts.sable.events import EVENTS, NO_MODEL, SableTurnPayload
from hiru_ai.core import llm
from hiru_ai.core.fakes import FakeChat
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.systems.sable.sable_chat import graph, guard
from tests.sable.fakes import answer, context, tool, two_models, world

THREAD = UUID("5ab1e000-0000-4000-8000-000000000001")
USER_MESSAGE = UUID("5ab1e000-0000-4000-8000-000000000002")


def payload(message: str, *, can_stage: bool = True, scene: bool = True, **over: Any) -> SableTurnPayload:
    case = world()
    fields: dict[str, Any] = {
        "production_id": case["production_id"], "thread_id": THREAD, "actor_user_id": uuid4(), "actor_name": "Dee",
        "role": "director", "can_stage": can_stage, "message": message, "user_message_id": USER_MESSAGE,
        "scene_id": case["scene_id"] if scene else None}
    return SableTurnPayload(**{**fields, **over})


def ctx_with(messages: list[dict[str, Any]] | None = None, thread: dict[str, Any] | None = None) -> Any:
    ctx = context()
    chat = FakeChat([{"id": str(THREAD), "chat": "sable", "summary": "", "summarised": 0, **(thread or {})}],
                    messages or [])
    return replace(ctx, ports=replace(ctx.ports, chat=chat))


def turn(req: SableTurnPayload, ctx: Any, stop: threading.Event | None = None) -> list[tuple[str, dict[str, Any]]]:
    return list(graph.run(req, ctx, stop))


def saved(ctx: Any) -> dict[str, Any]:
    return dict(ctx.ports.chat.message_rows[-1])


def test_a_turn_streams_status_words_then_the_reply_and_saves_it_with_its_record():
    ctx = ctx_with()
    with two_models([tool("sable_overview", episode=1), answer("Episode 1 has three scenes.")], []):
        events = turn(payload("How far along is episode 1?"), ctx)
    names = [e for e, _ in events]
    assert set(names) <= set(EVENTS) and names[-2:] == ["message", "done"]
    statuses = [d["text"] for e, d in events if e == "status"]
    assert statuses == ["Reading your message", "Looking over the production"]  # words, never a tool id
    assert "".join(d["text"] for e, d in events if e == "delta") == "Episode 1 has three scenes."
    row = saved(ctx)
    assert row["speaker"] == "Sable" and row["blocks"][0] == {"kind": "text", "text": "Episode 1 has three scenes.",
                                                              "stopped": False}
    assert row["meta"]["tools"] == ["sable_overview"] and row["meta"]["tier_start"] == "sable"
    message = next(d for e, d in events if e == "message")
    assert "meta" not in message  # the record never reaches the browser


def test_nothing_names_a_tier_a_model_or_a_tool_in_what_the_browser_gets():
    ctx = ctx_with()
    with two_models([tool("sable_think_harder", reason="Hard one.")], [answer("Considered.")]):
        events = turn(payload("Is the coverage enough?"), ctx)
    shown = repr([d for e, d in events])
    for word in ("sable_deep", "deep-model", "base-model", "sable_think_harder", "gpt"):
        assert word not in shown, word
    assert "Thinking this through" in shown and saved(ctx)["meta"]["escalated_by"] == "model"


def test_a_pre_routed_turn_is_recorded_with_its_rule():
    ctx = ctx_with()
    with two_models([], [answer("Compared.")]):
        turn(payload("Compare E1S2 with E1S3"), ctx)
    meta = saved(ctx)["meta"]
    assert (meta["route_rule"], meta["escalated_by"], meta["tier_end"]) == ("asked_for_depth", "route", "sable_deep")


def test_an_edit_request_becomes_a_handoff_card_and_nothing_is_changed():
    ctx = ctx_with()
    with two_models([answer("Open E1S2 to make it.", "E1S2", "Make the opening shot a close-up")], []):
        events = turn(payload("Make the opening shot of E1S2 a close-up"), ctx)
    cards = [d["block"] for e, d in events if e == "card"]
    assert cards == [{"kind": "handoff", "scene_id": world()["scene_id"],
                      "episode_id": "418d7cef-8c58-410b-ae93-f2698fc23aea", "scene": "E1S2",
                      "request": "Make the opening shot a close-up", "target": ""}]
    assert saved(ctx)["blocks"][1]["kind"] == "handoff"


def test_a_handoff_to_a_scene_that_is_not_in_the_production_is_no_card():
    ctx = ctx_with()
    with two_models([answer("Open it.", "E9S9", "re-plan it")], []):
        events = turn(payload("re-plan E9S9"), ctx)
    assert not [e for e, _ in events if e == "card"]


def test_a_rule_is_a_card_for_a_director_and_no_card_for_a_viewer():
    staged = [tool("memory_propose", rule="Anudi never shouts.", scope="production")]
    deep = [tool("memory_propose", rule="Anudi never raises her voice.", scope="production"), answer("A card.")]
    ctx = ctx_with()
    with two_models(list(staged), list(deep)):
        turn(payload("Remember: Anudi never raises her voice."), ctx)
    assert [b["kind"] for b in saved(ctx)["blocks"]][:2] == ["text", "sable_memory"]
    viewer = ctx_with()
    with two_models(list(staged), list(deep)):
        turn(payload("Remember: Anudi never raises her voice.", can_stage=False), viewer)
    blocks = saved(viewer)["blocks"]
    assert [b["kind"] for b in blocks] == ["text"] and "cannot accept cards" in blocks[0]["text"]


def test_a_line_no_tool_returned_is_taken_out_and_noted():
    ctx = ctx_with()
    made_up = "Kasun says “I will always love the harbour lights” and smiles. The scene runs 16 s."
    with two_models([answer(made_up)], []):
        turn(payload("What does Kasun say?"), ctx)
    row = saved(ctx)
    assert "harbour lights" not in row["blocks"][0]["text"] and "16 s" in row["blocks"][0]["text"]
    assert row["meta"]["guard"] and row["meta"]["guard"][0].startswith("removed a quote")


def test_a_line_a_tool_returned_stands():
    sources = ['{"lines":[{"speaker":"Kasun","text":"අද රෑට එන්න පුළුවන්ද?"}]}']
    text, removed = guard.check("Kasun asks “අද රෑට එන්න පුළුවන්ද?” before the call.", sources)
    assert removed == [] and "අද රෑට" in text
    tidied, removed = guard.check("Kasun asks “අද රෑට එන්න පුලුවන්ද?”.", sources)  # one letter changed
    assert removed and "අද රෑට" not in tidied


def test_short_quotes_that_are_not_lines_are_left_alone():
    assert guard.check('The bible calls it "the stall".', []) == ('The bible calls it "the stall".', [])


def test_document_facts_carry_their_citations():
    case = world()
    ctx = ctx_with()
    ctx = replace(ctx, corpora=tuple(case.get("corpora") or ("production_docs",)))
    with two_models([tool("search_kb", query="the boat"), answer("The bible says the boat is her father's.")], []):
        events = turn(payload("What does the bible say about the boat?"), ctx)
    cited = [d for e, d in events if e == "citations"]
    assert saved(ctx)["citations"] == (cited[0]["citations"] if cited else [])


def test_no_model_says_so_in_one_plain_sentence_and_saves_it():
    ctx = ctx_with()
    events = turn(payload("Who is Anudi?"), ctx)  # no key, no fake: models are off
    assert "".join(d["text"] for e, d in events if e == "delta") == NO_MODEL
    assert saved(ctx)["meta"]["failed"] is True and not [e for e, _ in events if e == "error"]


def test_a_model_that_fails_is_a_sentence_never_an_exception():
    ctx = ctx_with()
    with llm.use_models(ScriptedChatModel(replies=[RuntimeError("boom")])):
        events = turn(payload("Who is Anudi?"), ctx)
    text = "".join(d["text"] for e, d in events if e == "delta")
    assert "boom" not in text and "went wrong" in text


def test_a_stopped_turn_is_saved_and_says_so():
    ctx = ctx_with()
    stop = threading.Event()
    stop.set()
    with two_models([answer("Three scenes.")], []):
        events = turn(payload("How far along is episode 1?"), ctx, stop)
    assert not [e for e, _ in events if e == "delta"]
    row = saved(ctx)
    assert row["blocks"][0]["stopped"] is True and row["meta"]["stopped"] is True


def test_the_recent_chat_is_read_without_this_message_and_without_replaced_ones():
    history = [
        {"id": "m1", "thread_id": str(THREAD), "kind": "user", "speaker": "Dee", "text": "Which scene has the call?"},
        {"id": "m2", "thread_id": str(THREAD), "kind": "director", "speaker": "Sable", "text": "",
         "blocks": [{"kind": "text", "text": "E1S2."}]},
        {"id": str(USER_MESSAGE), "thread_id": str(THREAD), "kind": "user", "speaker": "Dee", "text": "So E1S2?"}]
    ctx = ctx_with(history)
    with two_models([answer("Yes.")], []) as (b, _):
        turn(payload("So E1S2?"), ctx)
    sent = str(b.calls[0][-1].content)
    assert "Sable: E1S2." in sent and sent.count("So E1S2?") == 1  # the message once, as the message


def test_a_long_thread_folds_its_older_messages_into_the_stored_summary_once():
    long = "word " * 400
    history = [{"id": f"m{n}", "thread_id": str(THREAD), "kind": "user", "speaker": "Dee", "text": f"{n} {long}"}
               for n in range(20)]
    ctx = ctx_with(history)
    summary = ScriptedChatModel(replies=[{"summary": "Dee asked twenty long questions."}])
    with two_models([answer("Ok.")], []) as (b, _):
        from hiru_ai.core import llm as door
        base = door._override.get()
        with door.use_models(lambda tier: summary if tier.name == "low" else base(tier)):  # type: ignore[misc]
            turn(payload("And now?"), ctx)
    thread = ctx.ports.chat.thread(THREAD)
    assert thread["summary"] == "Dee asked twenty long questions." and thread["summarised"] == 8
    sent = str(b.calls[0][-1].content)
    assert "Dee asked twenty long questions." in sent and "Dee: 7 word" not in sent and "Dee: 8 word" in sent


def test_a_staged_change_is_stored_pinned_to_its_shots_ids():
    ctx = ctx_with()
    op = {"op": "set", "shot": 1, "field": "framing", "value": "CU"}
    with two_models([tool("change_propose", summary="Open close.", ops=[op])],
                    [tool("change_propose", summary="Open on a close-up so the smile reads.", ops=[op]),
                     answer("A card.")]):
        turn(payload("Make S01 a close-up, exactly that."), ctx)
    card = next(b for b in saved(ctx)["blocks"] if b["kind"] == "sable_change")
    first = sorted((s for s in world()["fixtures"]["shots"]), key=lambda s: s["number"])[0]
    assert card["scene"] == "E1S2" and card["status"] == "open"
    assert card["ops"][0]["shot_id"] == str(first["id"]) and "shot" not in card["ops"][0]
