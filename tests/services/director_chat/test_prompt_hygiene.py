"""Prompt hygiene guards (PLAN.md §5 "Prompt caching", §6.1, §12; CLAUDE.md "AI and RAG").

* The system part of every prompt is STATIC: byte-identical across turns and scenes, so the
  provider's prompt cache can serve it. Per-call data (the scene, the message, memory, the lead's
  charter) goes in the user part, after it.
* Scene text, chat history and the person's message are DATA: wrapped in tags and labelled,
  never placed in system instructions; every system prompt says so.
* No prices, credits or costs anywhere a model could repeat them to the UI.
* Charters stay within a budget, so they do not grow by accretion.
"""
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from director_chat.engine import agents, conductor, turn

from tests.services.director_chat.conftest import DirectorLLM, FakeStore, fixture_scene, tool_call
from tests.services.director_chat.test_turn import payload, plan_answer

ROOT = Path(__file__).resolve().parents[3]
STATIC = {
    "conductor": conductor.SYSTEM,
    "advisor": agents.ADVISOR_SYSTEM,
    "reply": turn.REPLY_SYSTEM,
    **{f"specialist:{a}": f"{agents.PRIMER}\n\n{agents.CHARTER[a]}" for a in agents.CHARTER},
}
MONEY = re.compile(r"\$|\bUSD\b|\bLKR\b|\bRs\.?\s|\bprice|\bcredit|\bcost|\bbilled|\bpremium", re.I)
BUDGET_CHARS = 2600


@pytest.mark.parametrize("name", sorted(STATIC))
def test_system_prompts_are_static_labelled_and_within_budget(name: str):
    text = STATIC[name]
    assert re.search(r"data, never\s+instructions", text), "say that the scene and messages are data"
    assert len(text) <= BUDGET_CHARS, f"{name} is {len(text)} chars; the budget is {BUDGET_CHARS}"
    assert not MONEY.search(text)


def test_persona_library_has_no_prices():
    sql = (ROOT / "supabase" / "migrations" / "20261023111753_phase3_director.sql").read_text(encoding="utf-8")
    seed = sql[sql.index("insert into public.director_personas"):]
    assert not MONEY.search(seed)


def _model_turn(scene_no: int, message: str) -> DirectorLLM:
    tasks = [{"agent": a, "shots": [1], "instruction": "look again"} for a in agents.CHARTER]
    responders = {
        "turn_plan": lambda s, u: plan_answer("craft", tasks=tasks),
        **{f"{a}_ops": (lambda s, u: {"ops": [], "note": "It works."}) for a in agents.CHARTER},
        "advisor_view": lambda s, u: {"agrees": True, "view": ""},
    }
    store = FakeStore(*fixture_scene(scene_no), board=[
        {"seat": "lead", "persona": {"id": str(uuid4()), "name": f"Lead {scene_no}", "style_note": "x",
                                     "charter": f"Charter for scene {scene_no}"}}])
    store.memory_rows.append({"kind": "decision", "text": f"Rule {scene_no}"})
    llm = DirectorLLM(responders)
    list(turn.run(payload(store, message), store, llm))
    chat = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")},
                       tool_script=[type("M", (), {"content": "", "tool_calls": [tool_call("get_shot_timing")]})()])
    list(turn.run(payload(store, f"why? {message}"), store, chat))
    llm.calls += chat.calls
    return llm


def test_per_call_data_never_reaches_the_system_part():
    one, two = _model_turn(0, "Make it tender"), _model_turn(3, "Make it colder")
    systems = {c["system"] for c in one.calls + two.calls}
    assert systems <= set(STATIC.values()), "every system prompt must be one of the static ones"
    for llm, scene_no, message in ((one, 0, "Make it tender"), (two, 3, "Make it colder")):
        for c in llm.calls:
            assert f"Charter for scene {scene_no}" not in c["system"] and message not in c["system"]
            assert f"Rule {scene_no}" not in c["system"]


def test_scene_and_message_are_wrapped_as_data():
    llm = _model_turn(0, "Make it tender")
    by_phase: dict[str, str] = {}
    for c in llm.calls:
        by_phase.setdefault(c["phase"], c["user"])  # the craft turn first, then the question
    assert "<shot_list>" in by_phase["director.conduct"] and "<message>\nMake it tender\n</message>" in \
        by_phase["director.conduct"]
    assert "<production_memory>" in by_phase["director.conduct"]
    assert "<lead_director>\nCharter for scene 0" in by_phase["director.cinematography"]
    assert "<shot_list>" in by_phase["director.answer"] and "<recent_chat>" in by_phase["director.answer"]


def test_tools_are_read_only():
    from director_chat.engine.tools import DEFINITIONS

    names = {d["function"]["name"] for d in DEFINITIONS}
    assert names == {"search_production", "get_canon", "get_shot_timing", "list_open_questions"}
    assert not any(re.search(r"\b(set|update|write|delete|save|edit)", n) for n in names)
    # no tool takes a production or scene argument: the turn fixes the scope
    for d in DEFINITIONS:
        props = d["function"]["parameters"]["properties"]
        assert not {"production_id", "scene_id", "production", "scene"} & set(props)
