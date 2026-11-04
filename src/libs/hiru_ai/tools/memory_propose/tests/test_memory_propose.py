from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.memory_propose import tool


def test_a_rule_becomes_a_card_and_nothing_is_remembered():
    out, ctx = run_example("memory_propose")
    assert out.staged and out.scope == "scene" and "Nothing is remembered yet" in out.next
    (card,) = ctx.ports.staging.staged()
    assert card["kind"] == "memory" and card["rule"].startswith("Anudi's anger")
    assert card["scene_id"] == example_of("memory_propose")["scene_id"]


def test_a_production_rule_belongs_to_no_scene():
    _, ctx = run_example("memory_propose", {"scope": "production"})
    assert ctx.ports.staging.staged()[0]["scene_id"] is None


def test_a_scene_rule_without_a_scene_in_scope_is_refused_with_the_fix():
    with pytest.raises(ToolRefused) as refused:
        run_example("memory_propose", scene_id=None)
    assert "production" in refused.value.how_to_fix


def test_whitespace_is_tidied_and_a_rule_that_is_too_long_is_refused():
    ctx = example_ctx(example_of("memory_propose"))
    out = tool.run(tool.Args(rule="Keep   the\nfather kind.", scope="production"), ctx)
    assert out.rule == "Keep the father kind."
    with pytest.raises(ValidationError):
        tool.Args(rule="x" * 400, scope="production")
