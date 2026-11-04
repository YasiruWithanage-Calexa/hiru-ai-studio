from __future__ import annotations

from hiru_ai.core.testing import run_example


def test_the_canon_listed_by_kind():
    out, _ = run_example("canon_find", {"kind": "character"})
    assert [e["code"] for e in out.entities] == ["C01", "C02", "C03"] and out.total == 3 and out.next_page is None
    assert all(set(e) == {"code", "kind", "name"} for e in out.entities)


def test_a_word_finds_a_name_an_alias_or_a_code():
    assert [e["code"] for e in run_example("canon_find", {"kind": None, "query": "father"})[0].entities] == ["C03"]
    assert [e["code"] for e in run_example("canon_find", {"kind": None, "query": "L01"})[0].entities] == ["L01"]
    assert run_example("canon_find", {"kind": None, "query": "zzz"})[0].total == 0


def test_a_long_list_is_paged_and_detailed_adds_the_fields():
    first, _ = run_example("canon_find", {"kind": None, "page_size": 2, "response_format": "detailed"})
    assert len(first.entities) == 2 and first.total == 4 and first.next_page == 2
    assert "aliases" in first.entities[0] and "locked" in first.entities[0]
    second, _ = run_example("canon_find", {"kind": None, "page_size": 2, "page": 2})
    assert [e["code"] for e in second.entities] == ["C03", "L01"] and second.next_page is None
