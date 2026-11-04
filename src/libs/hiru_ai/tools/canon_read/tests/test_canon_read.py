from __future__ import annotations

import pytest

from hiru_ai.core.errors import PortMissing, ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.canon_read import tool


def test_a_character_by_nickname_with_the_look_worn_in_the_episode():
    out, _ = run_example("canon_read", {"name_or_code": "anudi", "episode": 2})
    assert (out.code, out.kind, out.name) == ("C02", "character", "Anudi")
    assert out.look and out.look["name"] == "Office whites" and out.looks == ["Office whites (1-3)"]
    assert out.card == {} and out.aliases == [], "concise leaves the full card out"


def test_a_code_works_and_an_episode_no_look_covers_gives_no_look():
    out, _ = run_example("canon_read", {"name_or_code": "c02", "episode": 9})
    assert out.name == "Anudi" and out.look is None and out.looks == ["Office whites (1-3)"]


def test_detailed_adds_the_whole_card_and_the_whole_look():
    out, _ = run_example("canon_read", {"name_or_code": "C02", "episode": 1, "response_format": "detailed"})
    assert out.card and out.look and out.look["episodes"] == "1-3" and out.look["accessories"]


def test_an_alias_finds_the_character():
    out, _ = run_example("canon_read", {"name_or_code": "Father"})
    assert out.code == "C03"


def test_a_name_that_is_not_there_answers_with_the_closest_names():
    with pytest.raises(ToolRefused) as refused:
        run_example("canon_read", {"name_or_code": "Anudy"})
    assert "Anudi" in refused.value.how_to_fix and refused.value.example


def test_without_the_canon_port_it_says_which_port():
    case = example_of("canon_read")
    ctx = example_ctx(case)
    from dataclasses import replace

    with pytest.raises(PortMissing, match="canon"):
        tool.run(tool.Args(name_or_code="C01"), replace(ctx, ports=replace(ctx.ports, canon=None)))
