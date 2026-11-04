from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.glossary_read import tool


def test_the_canons_spellings_are_listed_for_people_and_places_only():
    out, _ = run_example("glossary_read", {"language": "en"})
    assert [e["code"] for e in out.entries] == ["C01", "C02", "C03", "L01"] and out.translated_lines_seen == 0
    assert out.entries[0] == {"code": "C01", "name": "Kasun", "written_as": []}


def test_names_narrow_it_by_name_alias_or_code():
    out, _ = run_example("glossary_read", {"language": "en", "names": ["father", "c02"]})
    assert [e["code"] for e in out.entries] == ["C03", "C02"]


def test_an_accepted_translation_shows_how_a_name_was_written():
    case = example_of("glossary_read")
    case["fixtures"]["lines"][0] |= {"text": "Kasun said: I started with five thousand.",
                                     "source_text": "කසුන් කීවා", "source_lang": "si"}
    out = tool.run(tool.Args(language="en", names=["Kasun", "Anudi"]), example_ctx(case))
    assert out.translated_lines_seen == 1
    assert out.entries[0]["written_as"] == ["Kasun"] and out.entries[1]["written_as"] == []


def test_a_line_translated_into_another_language_is_not_evidence_for_this_one():
    case = example_of("glossary_read")
    case["fixtures"]["lines"][0] |= {"text": "Kasun said: hello.", "source_text": "x", "source_lang": "si"}
    assert tool.run(tool.Args(language="si"), example_ctx(case)).translated_lines_seen == 0


def test_an_unknown_name_lists_the_closest():
    with pytest.raises(ToolRefused) as refused:
        run_example("glossary_read", {"language": "en", "names": ["Kasn"]})
    assert "Kasun" in refused.value.how_to_fix
