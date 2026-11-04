from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.search_kb import tool


def test_the_scope_is_the_runs_and_the_model_supplies_the_question():
    out, ctx = run_example("search_kb", {"corpus": None, "k": 2})
    assert out.found == 2
    (asked,) = ctx.ports.search.asked
    assert asked["corpora"] == ["production_docs", "memory"] and asked["k"] == 2
    assert asked["embedding"] is None, "keyword-only, no key"


def test_a_model_may_narrow_the_scope_to_one_corpus_but_never_widen_it():
    _, ctx = run_example("search_kb")
    assert ctx.ports.search.asked[0]["corpora"] == ["production_docs"]
    with pytest.raises(ToolRefused) as refused:
        run_example("search_kb", {"corpus": "craft"})
    assert "production_docs" in refused.value.how_to_fix and refused.value.example


def test_a_passage_names_its_source_and_a_citation_and_hides_the_internals():
    out, _ = run_example("search_kb", {"corpus": None})
    first = out.passages[0]
    assert set(first) == {"cite", "source", "text"} and first["source"].startswith("memory:")


def test_detailed_adds_the_whole_text_and_the_corpus():
    case = example_of("search_kb")
    case["fixtures"]["chunks"] = [{"id": "c1", "corpus": "production_docs", "source": "bible.md", "heading": "Premise",
                                   "content": "x" * 900, "score": 0.4, "embedding": [0.1], "fts": "secret"}]
    short = tool.run(tool.Args(query="premise"), example_ctx(case))
    assert len(short.passages[0]["text"]) == tool.CONCISE_CHARS and short.passages[0]["source"] == "bible.md — Premise"
    whole = tool.run(tool.Args(query="premise", response_format="detailed"), example_ctx(case))
    assert len(whole.passages[0]["text"]) == 900 and whole.passages[0]["corpus"] == "production_docs"
    assert "embedding" not in whole.passages[0] and "fts" not in whole.passages[0]


def test_with_no_corpus_in_scope_nothing_is_searched():
    case = example_of("search_kb")
    ctx = example_ctx(case, corpora=())
    with pytest.raises(ToolRefused, match="no knowledge base"):
        tool.run(tool.Args(query="premise"), ctx)
    assert ctx.ports.search.asked == []


def test_an_unknown_corpus_in_scope_is_refused():
    with pytest.raises(ToolRefused, match="unknown corpus"):
        tool.run(tool.Args(query="premise"), example_ctx(example_of("search_kb"), corpora=("everything",)))
