from __future__ import annotations

from typing import Any

from hiru_ai.steps.canon_rules import step

INDEX = "C01 Kamala (Amma): the mother, mid 40s, wears a faded blue saree\nL01 Harbour: the breakwater at dawn\n"


def run(*docs: tuple[str, str, str]) -> dict[str, Any]:
    return step.run({"documents": [{"filename": f, "role": r, "text": t} for f, r, t in docs]})


def test_an_index_gives_codes_names_aliases_and_kinds():
    out = run(("index.md", "canon_index", INDEX))
    by_code = {c["code"]: c for c in out["candidates"]}
    assert by_code["C01"]["name"] == "Kamala" and by_code["C01"]["aliases"] == ["Amma"]
    assert by_code["C01"]["kind"] == "character" and by_code["L01"]["kind"] == "location"


def test_chips_count_what_was_found_and_omit_zeros():
    out = run(("index.md", "canon_index", INDEX))
    assert "1 locations" in out["chips"] and not any(c.startswith("0 ") for c in out["chips"])


def test_no_documents_no_candidates():
    assert run() == {"candidates": [], "chips": [], "notes": []}


def test_the_critic_names_what_a_core_character_is_missing():
    cands: Any = [{"kind": "character", "core": True, "code": "C01", "name": "Kamala", "card": {"voice": "warm"}}]
    assert step.critic(cands) == ["C01: no wardrobe anchor in the documents yet."]
