"""The director_chat system against the legacy engine on what the Phase 0 fixtures do not reach: a question answered
through the read tools, options offered and then confirmed in code, a choice applied. Each case runs on both engines and
the whole outcome (the event stream, the saved plan, the thread's rows) is compared.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any
from uuid import uuid4

from director_chat.engine import choice as legacy_choice

from contracts.director import ChoicePayload
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.systems.director_chat import graph
from tests.parity.adapters import run_case
from tests.parity.cases import _plan
from tests.parity.harness import outcome
from tests.services.director_chat.conftest import PID, FakeStore, fixture_scene


def same(inp: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    got = {engine: outcome(run_case("director_chat", copy.deepcopy(inp), copy.deepcopy(model), engine))
           for engine in ("legacy", "graph")}
    assert got["graph"] == got["legacy"]
    return got["graph"]


def test_a_question_is_answered_through_the_read_tools_and_comes_back_whole():
    got = same({"messages": ["how long is shot 2?"]}, {
        "enabled": True, "reply": "Shot 2 runs six seconds.",
        "tool_script": [{"content": "", "tool_calls": [{"name": "get_shot_timing"}]}],
        "replies": {"turn_plan": [_plan("chat")]}})
    assert [c["schema"] for c in got["llm"]] == ["turn_plan", "tools", "tools"]
    deltas = [e["data"]["text"] for e in got["events"] if e["event"] == "delta"]
    assert deltas == ["Shot 2 runs six seconds."]  # the tool round's answer is not streamed


def test_a_question_that_needs_no_tool_is_answered_in_one_round():
    got = same({"messages": ["hello"]}, {"enabled": True, "reply": "Hello.", "replies": {"turn_plan": [_plan("chat")]}})
    assert [c["schema"] for c in got["llm"]] == ["turn_plan", "tools"]


OPTIONS = {"question": "How should S02 play?", "options": [
    {"label": "Push in to a tight CU", "detail": "Closer on Nimal.", "intent": "",
     "ops": [{"op": "set", "shot": 2, "field": "framing", "value": "CU"}], "prompt": ""},
    {"label": "Ask for a mood", "detail": "Talk it through.", "intent": "", "ops": [], "prompt": "make it tenser"}]}


def test_options_leave_a_pending_card_and_a_confirmation_applies_it_in_code():
    got = same({"messages": ["give me options for shot 2", "i confirm"], "one_thread": True}, {
        "enabled": True, "replies": {"turn_plan": [_plan("options"), _plan("chat")], "chat_options": [OPTIONS]}})
    assert any(e["event"] == "message" and any(b["kind"] == "options" for b in e["data"]["blocks"])
               for e in got["events"])
    assert got["saved"], "the confirmation saved the plan"
    assert [p["status"] for p in got["pending_rows"]] == ["applied"]
    assert [c["schema"] for c in got["llm"]].count("chat_options") == 1


def test_confirming_with_nothing_waiting_says_so_without_asking_a_model():
    got = same({"messages": ["i confirm"]}, {"enabled": True, "replies": {"turn_plan": [_plan("chat")]}})
    assert not got["saved"]
    assert [c["schema"] for c in got["llm"]].count("stream") == 0


def test_a_choice_is_applied_like_the_legacy_choice():
    results = []
    for engine in ("legacy", "graph"):
        scene, lines, shots = fixture_scene(0)
        store = FakeStore(scene, lines, shots)
        ops = [{"op": "retime", "shot_id": shots[1]["id"], "seconds": 8}]
        req = ChoicePayload(production_id=PID, scene_id=scene["id"], actor_user_id=uuid4(), can_edit_script=True,
                            ops=ops)
        if engine == "legacy":
            result = legacy_choice.apply_choice(req, store)
        else:
            ctx = RunContext(production_id=PID, ports=replace(Ports(), scenes=store, director=store))
            result = graph.choose(req, ctx)
        results.append((result.model_dump(mode="json"), [s["duration_s"] for s in store.shot_rows], len(store.saved),
                        len(store.audits)))
    assert results[0] == results[1] and results[0][0]["applied"]
