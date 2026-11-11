"""The david writers carry the safe-depiction line word for word (plan/2026-11-10b, contracts.safe_depiction)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from contracts.safe_depiction import PROMPT_LINE

AGENTS = Path(__file__).resolve().parents[2] / "src" / "libs" / "hiru_ai" / "agents" / "david"


@pytest.mark.parametrize("agent", ["david_author"])
def test_the_writer_is_told_the_rule(agent: str):
    text = re.sub(r"\s+", " ", (AGENTS / agent / "prompts" / "system.md").read_text(encoding="utf-8"))
    line = re.sub(r"\s+", " ", PROMPT_LINE)
    assert line in text or line[2:] in text
