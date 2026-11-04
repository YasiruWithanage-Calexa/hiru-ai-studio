"""plan/2026-11-04 Phase 2: the four agents' `with_tools` forms in the systems that call them.

The forms are off until `AGENT_TOOLS` names them, so the first tests prove nothing changed with it empty. The rest run a
director turn and a shot-producer review with a scripted model that calls the tools, so CI checks the loop without a
model: a question answered with a lookup, an options writer that does not get the memory list, staged cards shown as the
options card, citations from the search tools, and the critic's tools reading the drafts under review.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from contracts.director import TurnPayload
from hiru_ai.core import agents, llm
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeCanon, FakeSearch, FakeStructure
from hiru_ai.core.staging import StagedCards
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.director_chat import graph, staged
from hiru_ai.systems.director_chat.turn import cited, scene_brief
from hiru_ai.systems.shot_producer.drafts import DraftScenes, reviewing
from tests.parity.cases import _plan
from tests.parity.graph_support import environment
from tests.services.director_chat.conftest import PID, FakeStore, fixture_scene


def call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}", "type": "tool_call"}])


class ToolStore(FakeStore):
    """The director's fake store plus the two `SceneStore` reads the tools use and the legacy store lacks."""

    def scenes(self, production_id: Any, scene_ids: list[str] | None) -> list[dict[str, Any]]:
        return [self.scene_row] if scene_ids is None or self.scene_row["id"] in scene_ids else []

    def latest_prompts(self, shot_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {}


def final(**out: Any) -> AIMessage:
    return call("Output", **out)


def route_by_prompt(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return "answer" if "lead director on the board" in system else "options" if "genuinely" in system else "conduct"


def run(message: str, answers: list[Any], plan: dict[str, Any], **kw: Any) -> tuple[Any, RoutedChatModel, RunContext]:
    store_routes = {"conduct": [plan], "answer": answers, "options": kw.pop("options", [])}
    store = ToolStore(*fixture_scene(0))
    ports = replace(Ports(), scenes=store, director=store, canon=FakeCanon(None, None), structure=FakeStructure(),
                    search=FakeSearch(kw.pop("chunks", None)), staging=StagedCards())
    ctx = RunContext(production_id=PID, actor_user_id=uuid4(), ports=ports)
    req = TurnPayload(production_id=PID, scene_id=UUID(store.scene_row["id"]), thread_id=uuid4(),
                      actor_user_id=uuid4(), actor_name="Dee", can_edit=True, can_edit_script=True, message=message,
                      user_message_id=uuid4())
    model = RoutedChatModel(routes=store_routes, choose=route_by_prompt, calls=[], model_name="m", phases=[], models=[])
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m", OPENAI__MODEL_MEDIUM="m",
                     AGENT_TOOLS=kw.pop("tools", "")):
        with llm.use_models(lambda tier: model):
            events = list(graph.run(req, ctx))
    return events, model, ctx


# ── the chat answerer ────────────────────────────────────────────────────────────────────────────────────────────────


def test_with_agent_tools_empty_the_chat_answerer_is_the_single_call_it_always_was():
    assert not agents.build("chat_answerer").uses_tools


def test_a_question_is_answered_by_a_tool_loop_when_agent_tools_names_the_agent():
    events, model, ctx = run("how long is shot 2?", [call("timing_check"), final(text="Shot 2 runs six seconds.")],
                             _plan("chat"), tools="chat_answerer")
    assert [d["text"] for e, d in events if e == "delta"] == ["Shot 2 runs six seconds."]
    assert [(t.tool, t.error) for t in ctx.tool_events] == [("timing_check", "")]
    message = next(d for e, d in events if e == "message")
    assert message["blocks"][0]["text"] == "Shot 2 runs six seconds."
    user = str(model.calls[-1][1].content)
    assert "<scene>" in user and "<shot_list>" not in user  # the whole shot list is not in the prompt


def test_a_question_the_facts_answer_makes_no_lookup():
    events, _, ctx = run("hello", [final(text="Hello.")], _plan("chat"), tools="chat_answerer")
    assert [d["text"] for e, d in events if e == "delta"] == ["Hello."] and not ctx.tool_events


def test_the_search_tools_citations_reach_the_stored_reply():
    chunks = [{"id": "chunk-1", "content": "The boat is called Lanka Star.", "corpus": "production_docs",
               "source": "bible.md", "heading": "Boats"}]
    events, _, ctx = run("what is the boat called?", [call("search_kb", query="the boat", k=2),
                                                      final(text="Lanka Star.")], _plan("chat"),
                         tools="chat_answerer", chunks=chunks)
    message = next(d for e, d in events if e == "message")
    assert message["citations"] and message["citations"][0]["chunk_id"] == "chunk-1"
    assert ctx.citations == message["citations"]


def test_a_failing_tool_does_not_end_the_turn():
    events, _, ctx = run("who is Nobody?", [call("canon_read", name_or_code="Nobody"),
                                            final(text="There is nobody by that name in the canon.")],
                         _plan("chat"), tools="chat_answerer")
    assert [t.error for t in ctx.tool_events] == ["refused"]
    assert [d["text"] for e, d in events if e == "delta"] == ["There is nobody by that name in the canon."]
    assert events[-1][0] == "done"


def test_scene_brief_is_one_short_line_that_says_where_to_read_the_rest():
    class Kernel:
        shots = [object()] * 12

    brief = scene_brief(Kernel())  # type: ignore[arg-type]
    assert brief.startswith("12 shots, numbered S01-S12.") and "scene_read" in brief and "\n" not in brief


def test_citations_are_merged_without_repeats_and_capped():
    a = [{"chunk_id": "1", "label": "x"}, {"chunk_id": "2", "label": "y"}]
    b = [{"chunk_id": "2", "label": "other"}, *({"chunk_id": str(n), "label": "z"} for n in range(3, 12))]
    out = cited(a, b)
    assert [c["chunk_id"] for c in out] == ["1", "2", "3", "4", "5", "6", "7", "8"] and out[1]["label"] == "y"


# ── the options writer ───────────────────────────────────────────────────────────────────────────────────────────────

OPTIONS = {"question": "How should S02 play?", "options": [
    {"label": "Push in to a tight CU", "detail": "Closer on Nimal.", "intent": "",
     "ops": [{"op": "set", "shot": 2, "field": "framing", "value": "CU"}], "prompt": ""},
    {"label": "Ask for a mood", "detail": "Talk it through.", "intent": "", "ops": [], "prompt": "make it tenser"}]}


def full(option: dict[str, Any]) -> dict[str, Any]:
    ops = [{**dict.fromkeys(("seconds", "at_block", "end_block", "link", "beat", "after_shot", "description", "framing",
                             "title", "block", "kind", "speaker", "delivery", "shot", "field", "value")), **o}
           for o in option["ops"]]
    return {**option, "ops": ops}


def test_the_options_writer_with_tools_is_not_sent_the_memory_list_and_may_try_an_idea():
    reply = {**OPTIONS, "options": [full(o) for o in OPTIONS["options"]]}
    events, model, ctx = run("give me options for shot 2", [final(text="Here are two ways.")], _plan("options"),
                             options=[call("plan_try", ops=[{"op": "set", "shot": 2, "field": "framing",
                                                             "value": "CU"}]), final(**reply)],
                             tools="options_writer")
    assert [t.tool for t in ctx.tool_events] == ["plan_try"]
    sent = [str(c[1].content) for c in model.calls if "genuinely" in str(c[0].content)]
    assert sent and all("<production_memory>" not in s for s in sent)
    block = next(b for e, d in events if e == "message" for b in d["blocks"] if b["kind"] == "options")
    assert len(block["options"]) == 2 and block["options"][0]["ops"]


# ── staged cards shown as the options card ───────────────────────────────────────────────────────────────────────────


def kernel_of(store: FakeStore) -> Any:
    from hiru_ai.steps.scene_kernel.turn_logic import kernel_for

    return kernel_for(store.scene_row, store.line_rows, store.shot_rows, None, [])


def test_a_staged_change_becomes_an_option_pinned_to_the_shots():
    store = FakeStore(*fixture_scene(0))
    kernel = kernel_of(store)
    card = {"kind": "change", "scene_id": store.scene_row["id"], "summary": "Open on a close-up.",
            "ops": [{"op": "set", "shot": 1, "field": "framing", "value": "CU"}], "touched": ["S01"]}
    block = staged.merge(None, [card], kernel, store.scene_row["id"])
    assert block and block["kind"] == "options"
    option = block["options"][0]
    assert option["label"] == "Open on a close-up." and option["impact"] == "Touches S01"
    assert option["ops"][0]["shot_id"] == store.shot_rows[0]["id"] and "shot" not in option["ops"][0]


def test_a_staged_rule_becomes_a_message_for_the_board():
    store = FakeStore(*fixture_scene(0))
    block = staged.merge(None, [{"kind": "memory", "rule": "No hand-held in the kitchen", "scope": "production"}],
                         kernel_of(store), store.scene_row["id"])
    assert block and block["options"][0]["prompt"] == "Remember from now on: No hand-held in the kitchen"
    assert not block["options"][0]["ops"]


def test_a_card_for_another_scene_or_an_unknown_kind_is_not_shown():
    store = FakeStore(*fixture_scene(0))
    kernel = kernel_of(store)
    other = {"kind": "change", "scene_id": str(uuid4()), "summary": "x", "ops": [{"op": "retime", "shot": 1,
                                                                                 "seconds": 8}]}
    assert staged.merge(None, [other, {"kind": "mystery"}], kernel, store.scene_row["id"]) is None


def test_staged_cards_join_the_options_the_turn_already_has_up_to_four():
    store = FakeStore(*fixture_scene(0))
    existing = {"kind": "options", "question": "q", "options": [{"label": str(n)} for n in range(3)]}
    cards = [{"kind": "memory", "rule": f"rule {n}", "scope": "production"} for n in range(3)]
    block = staged.merge(existing, cards, kernel_of(store), store.scene_row["id"])
    assert block and len(block["options"]) == 4 and block["question"] == "q"


def test_a_stage_tool_that_is_not_the_agents_stages_nothing():
    events, _, ctx = run("remember that the kitchen is never hand-held",
                         [call("memory_propose", rule="No hand-held in the kitchen", scope="production"),
                          final(text="I have put it down as a rule for you to confirm.")],
                         _plan("chat"), tools="chat_answerer")
    # memory_propose is not one of chat_answerer's tools (it only reads): the loop answers the call with an error
    assert not ctx.ports.staging.staged()  # type: ignore[union-attr]
    assert events[-1][0] == "done"


# ── the critic reads the drafts under review ─────────────────────────────────────────────────────────────────────────


def test_the_overlay_serves_the_draft_in_place_of_the_stored_design_and_refuses_writes():
    store = FakeStore(*fixture_scene(0))
    first = store.shot_rows[0]
    overlay = DraftScenes(store, {str(first["id"]): ({"cinematography": {"camera": "draft"}}, ["c1"])})  # type: ignore[arg-type]
    rows = overlay.shots(store.scene_row["id"])
    assert rows[0]["ir"] == {"cinematography": {"camera": "draft"}} and rows[0]["design"]["on_screen"] == ["c1"]
    assert rows[1] == store.shot_rows[1]  # a shot not under review is the stored one
    assert overlay.lines(store.scene_row["id"]) == store.line_rows  # every other read goes through
    with pytest.raises(PermissionError):
        overlay.save_design("x", {}, {})


def test_the_critic_context_has_the_scene_in_scope_and_the_overlay_as_its_scenes_port():
    store = ToolStore(*fixture_scene(0))
    ctx = reviewing(RunContext(production_id=PID, ports=replace(Ports(), scenes=store)), store.scene_row["id"], {})
    assert ctx.scene_id == UUID(store.scene_row["id"]) and isinstance(ctx.ports.scenes, DraftScenes)


def test_the_critic_with_tools_calls_a_check_on_the_drafts_and_gives_its_notes():
    store = ToolStore(*fixture_scene(0))
    ctx = reviewing(RunContext(production_id=PID, ports=replace(Ports(), scenes=store, canon=FakeCanon(None, None),
                                                                  structure=FakeStructure())),
                    store.scene_row["id"], {})
    script = [call("staging_check"), final(acceptable=False, notes=["S01: frame Nimal"])]
    model = RoutedChatModel(routes={"all": script}, choose=lambda m: "all", model_name="m")
    critic = agents.build("shot_critic", with_tools=True)
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m"):
        with llm.use_models(lambda tier: model):
            out = critic.run({"scene_number": 1, "heading": "INT. KITCHEN - DAWN", "drafts": ["S01 - MCU"],
                              "free": ["S01 does not frame its speaker"]}, ctx)
    assert out.notes == ["S01: frame Nimal"] and [t.tool for t in ctx.tool_events] == ["staging_check"]


# ── validate holds the tools form to the rules of a react agent ───────────────────────────────────────────────────────


def problems_with(agent: str, **form: Any) -> list[str]:
    from hiru_ai.core import manifest as mf
    from hiru_ai.core.registry import Component, Registry, default

    reg = default()
    comp = reg.get("agent", agent)
    manifest = comp.manifest
    assert isinstance(manifest, mf.AgentManifest) and manifest.with_tools is not None
    changed = manifest.model_copy(update={"with_tools": manifest.with_tools.model_copy(update=form)})
    clone = Registry(reg.root, reg.package)
    clone.components = {**reg.components, ("agent", agent): Component(changed, comp.folder, comp.package)}
    return [p.message for p in clone.validate(imports=False) if p.where.startswith(f"agent {agent}")]


def test_the_shipped_tools_forms_are_valid():
    assert problems_with("chat_answerer") == []


def test_a_tools_form_may_not_list_a_tool_that_writes():
    assert any("writes stored data" in p for p in problems_with("chat_answerer", tools=["scene_write"]))


def test_a_tools_form_may_not_list_more_than_eight_tools_or_one_twice():
    nine = ["canon_read", "canon_find", "memory_search", "questions_read", "shot_read", "scene_read", "episode_read",
            "frame_read", "glossary_read"]
    assert any("at most 8" in p for p in problems_with("chat_answerer", tools=nine))
    assert any("twice" in p for p in problems_with("chat_answerer", tools=["shot_read", "shot_read"]))


def test_a_tools_form_needs_a_prompt_of_its_own():
    same = problems_with("chat_answerer", prompts={"system": "prompts/system.md"})
    missing = problems_with("chat_answerer", prompts={"system": "prompts/nope.md"})
    assert any("same system prompt" in p for p in same) and any("missing or empty" in p for p in missing)


def test_a_tools_form_that_names_a_tool_that_does_not_exist_is_refused():
    assert any("does not exist" in p for p in problems_with("chat_answerer", tools=["no_such_tool"]))


def test_the_catalog_says_which_agents_have_a_tools_form():
    from hiru_ai.cli.tools import catalog
    from hiru_ai.core.registry import default

    row = next(r for r in catalog(default()).splitlines() if r.startswith("| `chat_answerer`"))
    assert "+ tools form" in row and "shot_read" in row


# ── the A/B between the single call and its tools form ────────────────────────────────────────────────────────────────


def test_the_ab_of_the_two_forms_reports_each_side_over_the_cases_that_apply_to_it():
    from hiru_ai.cli import evals
    from hiru_ai.core.registry import default

    reg = default()
    base, tools = evals.run_ab(reg, "options_writer", ("base", "tools"))
    assert all(r.passed for r in base + tools) and len(tools) > len(base)
    text = evals.report_ab("options_writer", ("base", "tools"), [base, tools])
    assert f"{len(base)} of {len(base)} -> {len(tools)} of {len(tools)}" in text and "tool calls" in text


def test_a_live_ab_would_put_every_case_through_both_forms():
    from hiru_ai.cli import evals
    from hiru_ai.core.registry import default

    reg = default()
    names = {c["name"] for c in evals.cases_of(reg, "options_writer", every=True)}
    either = {c["name"] for form in (False, True) for c in evals.cases_of(reg, "options_writer", tools=form)}
    assert names == either
