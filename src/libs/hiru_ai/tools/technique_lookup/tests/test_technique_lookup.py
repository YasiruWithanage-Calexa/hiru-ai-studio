from __future__ import annotations

from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.technique_lookup import tool


def test_it_returns_the_techniques_the_library_found():
    out, ctx = run_example("technique_lookup")
    assert out.found == 2 and out.techniques[0]["name"] == "Rack focus"
    assert ctx.ports.search.asked == [{"technique_query": "a smile that slips", "embedding": None, "k": 3}]


def test_concise_cuts_a_long_use_and_detailed_adds_the_definition():
    case = example_of("technique_lookup")
    case["fixtures"]["techniques"] = [{"name": "Dolly zoom", "effect": "u" * 500, "definition": "d", "category": "lens",
                                       "prompt_phrase": "dolly zoom"}]
    short = tool.run(tool.Args(intent="unease"), example_ctx(case))
    assert len(short.techniques[0]["use"]) == tool.USE_CHARS and "definition" not in short.techniques[0]
    whole = tool.run(tool.Args(intent="unease", response_format="detailed"), example_ctx(case))
    assert len(whole.techniques[0]["use"]) == 500 and whole.techniques[0]["definition"] == "d"


def test_a_library_with_nothing_to_say_answers_with_none():
    case = example_of("technique_lookup")
    case["fixtures"]["techniques"] = []
    assert tool.run(tool.Args(intent="unease"), example_ctx(case)).found == 0
