"""Sable's model choice (plan/2026-11-08 Phase 2, §4.4): average first, deeper when the work needs it, at most one
switch per turn and only upward. Two fake models, one per tier; no network."""
from __future__ import annotations

from typing import Any

import pytest

from hiru_ai.agents.sable.sable_agent.schema import Input
from hiru_ai.core import agents
from hiru_ai.core.middleware import tiering
from tests.sable.fakes import answer, context, tool, two_models

INP = Input(message="How far along is episode 1?", scene="E1S2")


def run(base: list[Any], deep: list[Any], *, tier: str | None = None, rows: list[Any] | None = None):
    ctx = context(rows)
    with two_models(base, deep) as (b, d):
        out = agents.build("sable_agent").run(INP, ctx, tier=tier)
    return out, ctx, b, d


def test_a_turn_that_needs_nothing_more_stays_on_the_average_model():
    out, ctx, b, d = run([tool("sable_overview", episode=1), answer("Three scenes.")], [])
    assert out.text == "Three scenes." and len(b.calls) == 2 and d.calls == []
    assert ctx.tiering == {"tier_start": "sable", "tier_end": "sable", "escalated_by": "", "reason": ""}


def test_think_harder_moves_every_later_call_up_and_never_back():
    out, ctx, b, d = run(
        [tool("sable_overview", episode=1), tool("sable_think_harder", reason="A judgement of coverage.")],
        [tool("scene_read", scene="E1S2"), answer("Mostly enough.")])
    assert out.text == "Mostly enough."
    assert len(b.calls) == 2 and len(d.calls) == 2  # the base model never runs again after the switch
    assert ctx.tiering["escalated_by"] == "model" and ctx.tiering["tier_end"] == "sable_deep"
    assert ctx.tiering["reason"] == "A judgement of coverage."


def test_the_deep_model_continues_the_thread_with_what_was_already_read():
    _, _, b, d = run([tool("sable_overview", episode=1), tool("sable_think_harder", reason="Compare.")],
                     [answer("Done.")])
    sent = d.calls[0]
    assert any(getattr(m, "type", "") == "tool" and "Harbour Lights" in str(m.content) for m in sent)
    assert str(sent[0].content) == str(b.calls[0][0].content)  # the same system prompt, byte for byte


def test_the_tool_list_and_the_system_prompt_are_the_same_bytes_on_both_tiers():
    _, _, b, d = run([tool("sable_think_harder", reason="Hard.")], [answer("Ok.")])
    assert b.bound and d.bound and b.bound[0] == d.bound[0]
    assert len(b.bound[0]) >= 24  # every tool (and the answer schema) is bound on both
    names = [n for n in b.bound[0] if n != "Output"]
    assert names == sorted(names)


def test_two_refusals_in_a_row_move_the_turn_up():
    out, ctx, _, d = run([tool("canon_read", 0, name_or_code="Nobody"), tool("canon_read", 1, name_or_code="Nemo")],
                         [answer("I could not find that person.")])
    assert ctx.tiering["escalated_by"] == "refusals" and out.text.startswith("I could not")
    assert len(d.calls) == 1


def test_one_refusal_then_a_good_lookup_does_not():
    _, ctx, _, d = run([tool("canon_read", 0, name_or_code="Nobody"), tool("canon_read", 1, name_or_code="Kasun"),
                        answer("Kasun runs the stall.")], [])
    assert ctx.tiering["escalated_by"] == "" and d.calls == []


def test_at_the_cap_the_final_answer_is_written_on_the_deep_model():
    lookups = [tool("sable_overview", n, episode=1) for n in range(8)]
    out, ctx, b, d = run(lookups, [answer("Here is what I found.")])
    assert ctx.tiering["escalated_by"] == "cap" and out.text == "Here is what I found."
    assert len(b.calls) == 8 and len(d.calls) == 1


def test_a_card_is_drafted_again_by_the_deep_model():
    _, ctx, b, d = run(
        [tool("memory_propose", rule="Anudi never shouts.", scope="production")],
        [tool("memory_propose", rule="Anudi never raises her voice at her father.", scope="production"),
         answer("I left a card.")])
    assert ctx.tiering["escalated_by"] == "stage"
    cards = ctx.ports.staging.staged()  # type: ignore[union-attr]
    assert [c["rule"] for c in cards] == ["Anudi never raises her voice at her father."]  # the deep model's
    assert len(b.calls) == 1 and len(d.calls) == 2


def test_a_pre_routed_turn_starts_deep_and_says_why():
    _, ctx, b, d = run([], [tool("sable_overview", episode=1), answer("Compared.")], tier="sable_deep")
    assert b.calls == [] and len(d.calls) == 2
    assert ctx.tiering == {"tier_start": "sable_deep", "tier_end": "sable_deep", "escalated_by": "route",
                           "reason": ""}


def test_deep_calls_are_their_own_phase_in_token_usage():
    rows: list[Any] = []
    run([tool("sable_think_harder", reason="Hard.")], [answer("Ok.")], rows=rows)
    assert [r["phase"] for r in rows] == ["sable.turn", "sable.deep"]
    assert [r["model"] for r in rows] == ["base-model", "deep-model"]


def test_a_deep_call_carries_the_trace_tag():
    seen: list[Any] = []
    built = tiering.build(agent="sable", start="sable", deep="sable_deep",
                          get_model=lambda tier: seen.append(tier) or _Tagged())
    built.escalate("model")
    assert built.deep_model().tags == ["sable:deep"] and seen == ["sable_deep"]


def test_the_signals_the_manifest_turns_off_do_nothing():
    record: dict[str, Any] = {}
    built = tiering.build(agent="sable", start="sable", deep="sable_deep", signals=("model",), record=record)
    built.refusals = 5
    assert record["escalated_by"] == "" and not built.escalated


@pytest.mark.parametrize(("content", "is_refused"), [
    ('{"error": "there is no character", "how_to_fix": "x"}', True),
    ('{"name": "Anudi"}', False), ("plain text", False), ("{not json", False)])
def test_what_counts_as_a_refusal(content: str, is_refused: bool):
    assert tiering.refused(content) is is_refused


def test_the_deep_phase_name():
    assert tiering.deep_phase("sable.turn") == "sable.deep" and tiering.deep_phase("x") == "x.deep"


class _Tagged:
    def __init__(self) -> None:
        self.tags: list[str] = []

    def model_copy(self, update: dict[str, Any]) -> Any:
        out = _Tagged()
        out.tags = update["tags"]
        return out
