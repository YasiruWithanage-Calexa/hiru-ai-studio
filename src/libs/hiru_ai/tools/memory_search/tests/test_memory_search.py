from __future__ import annotations

from uuid import UUID

from hiru_ai.core.context import RunContext
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.memory_search import tool


def test_it_finds_remembered_decisions_with_a_citation_and_never_the_documents():
    out, ctx = run_example("memory_search")
    assert out.found == 1 and out.memories[0]["cite"] == "c0000000-0000-4000-8000-000000000001"
    assert "hands" in out.memories[0]["text"] and "heading" not in out.memories[0]
    (asked,) = [a for a in ctx.ports.search.asked if "memory_query" in a]
    assert asked["production_id"] == example_of("memory_search")["production_id"] and asked["k"] == 4
    assert asked["embedding"] is None, "no key: keyword search"


def test_concise_cuts_a_long_decision_and_detailed_keeps_it_whole():
    long = "x" * 900
    case = example_of("memory_search")
    case["fixtures"]["chunks"] = [{"id": "m1", "corpus": "memory", "source": "memory:1", "heading": "Decision",
                                   "content": long}]
    short = tool.run(tool.Args(query="anything"), example_ctx(case))
    assert len(short.memories[0]["text"]) == tool.CONCISE_CHARS
    whole = tool.run(tool.Args(query="anything", response_format="detailed"), example_ctx(case))
    assert whole.memories[0]["text"] == long and whole.memories[0]["heading"] == "Decision"


def test_the_production_is_the_runs_never_the_models():
    assert "production_id" not in tool.Args.model_fields
    out = tool.run(tool.Args(query="anything"), RunContext(production_id=UUID(int=1),
                                                          ports=example_ctx(example_of("memory_search")).ports))
    assert out.found == 1
