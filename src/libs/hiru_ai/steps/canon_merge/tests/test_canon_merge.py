"""The merges are the legacy engine's, unchanged."""
from __future__ import annotations

import copy
from typing import Any

from canon_extract.engine import model as legacy

from contracts.canon import CanonKind
from hiru_ai.steps.canon_merge import logic, step

ENTITIES: list[dict[str, Any]] = [
    {"kind": "character", "name": "kamala", "code": "C01", "aliases": ["Amma"], "core": True,
     "card": {"summary": "The mother", "age": "52", "voice": "warm", "colour": "ignored"}},
    {"kind": "character", "name": "AMMA", "code": "", "aliases": [], "core": False, "card": {"summary": "the mother"}},
    {"kind": "location", "name": "the harbour", "code": "X9", "aliases": [], "core": False,
     "card": {"summary": "A bay"}},
    {"kind": "prop", "name": "  ", "code": "", "aliases": [], "core": False, "card": {}}]


def test_the_answer_becomes_the_same_candidates():
    got = step.run({"op": "from_answer", "entities": copy.deepcopy(ENTITIES)})["candidates"]
    assert got == _legacy_extract(ENTITIES)


def _legacy_extract(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return legacy.extract(lambda system, user: {"entities": copy.deepcopy(entities)}, [], [])  # type: ignore[no-any-return]


def test_a_code_with_the_wrong_prefix_is_dropped_and_a_nameless_entity_is_skipped():
    out = logic.from_answer(copy.deepcopy(ENTITIES))
    assert len(out) == 3 and out[2]["code"] == "" and out[0]["code"] == "C01"  # X9 is no location code, C01 is fine


def test_combine_and_dedupe_match_the_legacy_functions():
    rules_side = [c for c in _legacy_extract(ENTITIES) if c["kind"] != CanonKind.PROP][:1]
    model_side = _legacy_extract(ENTITIES)
    assert logic.combine(copy.deepcopy(rules_side), copy.deepcopy(model_side)) == legacy.combine(
        copy.deepcopy(rules_side), copy.deepcopy(model_side))
    cands = logic.combine(copy.deepcopy(rules_side), copy.deepcopy(model_side))
    groups = [{"kind": "character", "keep": cands[0]["name"], "same_as_keep": ["Amma", "nobody"]},
              {"kind": "location", "keep": "ghost", "same_as_keep": [cands[-1]["name"]]}]
    assert logic.apply_groups(copy.deepcopy(cands), groups) == legacy.dedupe(
        lambda system, user: {"groups": groups}, copy.deepcopy(cands))


def test_two_coded_entities_are_never_merged():
    a, b = _legacy_extract(ENTITIES[:1])[0], _legacy_extract(ENTITIES[:1])[0]
    b["name"], b["code"] = "Kamali", "C02"
    kept = logic.apply_groups([a, b], [{"kind": "character", "keep": "Kamala", "same_as_keep": ["Kamali"]}])
    assert len(kept) == 2


def test_the_counts_name_speakers_and_places():
    cands = _legacy_extract(ENTITIES)
    cands[0]["lines"], cands[2]["scenes"] = 7, 3
    got = logic.counts(cands)
    assert {"name": cands[0]["name"], "count": 7} in got["speakers"]
    assert {"name": cands[2]["name"], "count": 3} in got["places"]
