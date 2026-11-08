"""Tests that live with the sable_summary agent (ADR 0006)."""
from __future__ import annotations

from hiru_ai.agents.sable.sable_summary import agent
from hiru_ai.agents.sable.sable_summary.schema import Input


def test_the_summary_so_far_comes_first_and_the_messages_last():
    text = agent.user_message(Input(summary="", messages="Dee: hi"))
    assert "(none yet)" in text and text.rstrip().endswith("</older_messages>")


def test_no_model_keeps_the_summary():
    assert agent.fallback(Input(summary="kept", messages="x")).summary == "kept"  # type: ignore[union-attr]
