from __future__ import annotations

from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.dialogue_check import tool


def test_words_the_person_wrote_pass_and_words_they_did_not_are_listed():
    out, _ = run_example("dialogue_check")
    first, second, third = out.results
    assert first == {"op": "block.set", "dialogue": True, "ok": True}
    assert second["ok"] is False and {"come", "home", "right"} <= set(second["not_theirs"])
    assert third == {"op": "set", "dialogue": False} and not out.all_theirs


def test_a_removal_carries_no_words_and_passes_even_when_the_person_wrote_nothing():
    case = example_of("dialogue_check")
    out = tool.run(tool.Args(ops=[{"op": "block.remove", "block": 3}]), example_ctx(case, said=""))
    assert out.all_theirs and out.person_wrote_nothing


def test_when_the_person_wrote_nothing_no_line_may_be_made():
    case = example_of("dialogue_check")
    out = tool.run(tool.Args(ops=[{"op": "block.insert", "block": 2, "kind": "dialogue", "value": "Hello"}]),
                   example_ctx(case, said=""))
    assert not out.all_theirs and out.person_wrote_nothing and out.results[0]["not_theirs"] == ["hello"]


def test_a_typo_fixed_is_still_theirs():
    case = example_of("dialogue_check")
    out = tool.run(tool.Args(ops=[{"op": "block.set", "block": 1, "kind": "dialogue", "value": "kinder"}]),
                   example_ctx(case, said="Make father kindr."))
    assert out.all_theirs


def test_the_models_cannot_pass_the_persons_words():
    assert "said" not in tool.Args.model_fields and "written" not in tool.Args.model_fields
