"""plan/2026-11-05 Phase 0: what a run's model calls cost, priced from the rows `token_usage` holds.

The live runner and the spike keep the rows in memory and print this table; the interface never shows a cost."""
from __future__ import annotations

import sys
from pathlib import Path

from tests.adam import gold
from tests.adam.test_take_system import NAME, World, per_tier, route, routes_for

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import adam_cost as cost

from hiru_ai.core import llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.adam.adam_shot_planner import scene as planner


def row(model: str, prompt: int, cached: int, answer: int, reasoning: int = 0, component: str = "") -> dict:
    return {"phase": "p", "model": model, "input_tokens": prompt, "cached_input_tokens": cached,
            "output_tokens": answer, "reasoning_tokens": reasoning, "component": component}


def test_a_row_is_priced_at_list_prices_with_the_cached_part_of_the_prompt_at_the_cached_rate():
    # gpt-5: $1.25 in, $0.125 cached, $10 out per million tokens
    assert abs(cost.cost(row("gpt-5", 10_000, 0, 13_000)) - (0.0125 + 0.13)) < 1e-9
    assert abs(cost.cost(row("gpt-5", 10_000, 8_000, 13_000)) - (2_000 * 1.25e-6 + 8_000 * 0.125e-6 + 0.13)) < 1e-9
    assert abs(cost.cost(row("gpt-5-mini", 1_000_000, 0, 1_000_000)) - (0.25 + 2.0)) < 1e-9


def test_a_model_name_is_priced_as_the_longest_listed_prefix_it_starts_with():
    assert cost.prices("gpt-5-mini-2026-08-07") == cost.PRICES["gpt-5-mini"]
    assert cost.prices("gpt-5-nano") == cost.PRICES["gpt-5-nano"]
    assert cost.prices("gpt-5.1") == cost.PRICES["gpt-5"] and cost.prices("something-new") == cost.PRICES["gpt-5"]


def test_the_measured_staged_build_prices_to_what_plan_2026_11_05_found():
    """Section 1: 13 designer calls of about 10,453 prompt and 13,238 answer tokens cost about $1.79 (some of the prompt
    was cached, which only lowers it)."""
    rows = [row("gpt-5", 10_453, 0, 13_238, 8_700, "agent:adam_shot_designer")] * 13
    assert 1.80 < cost.total(rows) < 2.0
    assert cost.by_agent(rows)[0]["reasoning"] == 8_700


def test_the_table_lists_the_dearest_agent_first_and_the_cost_of_one_scene():
    rows = [row("gpt-5", 8_000, 0, 20_000, 14_000, "agent:adam_take"),
            row("gpt-5-mini", 4_000, 0, 3_000, 0, "agent:adam_critic"),
            row("gpt-5-mini", 4_000, 0, 1_000, 0, "agent:adam_sound_designer")]
    text = cost.table(rows, scenes=2)
    lines = text.splitlines()
    assert lines[1].startswith("adam_take") and lines[-2].startswith("total") and lines[-1].startswith("per scene")
    assert abs(cost.total(rows) / 2 - float(lines[-1].split()[-1])) < 1e-4


def test_a_one_take_scene_run_with_the_detail_on_leaves_one_row_a_call_and_names_the_agent_of_each():
    """The live runner passes `RunContext(usage_sink=rows.append, usage_detail=True)`; every call leaves a row that says
    which agent made it, so the table can be read by agent."""
    rows: list[dict] = []
    world = World()
    sc = gold.scene(NAME)
    script, ids = planner.script_of(world.scene, world.scenes.lines(world.scene_id), cast=sc["cast"],
                                    place=sc["place"]["name"], objects=sc["place"]["objects"])
    model = RoutedChatModel(routes=routes_for(), choose=route, model_name="gpt-5")
    with llm.use_models(per_tier(model)):
        planner.Planner(RunContext(usage_sink=rows.append, usage_detail=True), script, context={}, line_ids=ids,
                        removed=[], editorial=True).plan_take()
    assert [cost.agent_of(r) for r in rows] == ["adam_take", "adam_sound_designer", "adam_critic"]
    assert all("reasoning_tokens" in r and r["component"].startswith("agent:") for r in rows)
