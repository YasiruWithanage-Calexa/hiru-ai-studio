"""sable_think_harder changes nothing: it answers at once; the tiering middleware does the rest (tests/sable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import default
from hiru_ai.tools.sable.sable_think_harder import tool


def test_it_answers_ok_and_touches_no_port():
    out = tool.run(tool.Args(reason="Comparing three scenes."), RunContext())
    assert out.ok and "again" in out.next
    assert default().get("tool", "sable_think_harder").manifest.ports == []  # type: ignore[union-attr]


def test_a_reason_is_needed():
    with pytest.raises(ValidationError):
        tool.Args(reason="")
