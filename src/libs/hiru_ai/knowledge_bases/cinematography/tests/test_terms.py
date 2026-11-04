"""The cinematography terms load cleanly, merge with camera_shots.csv, and fit `craft_techniques`."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from cine_terms import (  # noqa: E402
    LEGACY_SOURCE,
    SHORT_FORM_CATEGORIES,
    TERMS_SOURCE,
    effect_text,
    load_terms,
    norm,
)

KB = ROOT / "src" / "knowledge_base"
TERMS, LEGACY = KB / "cinematography", KB / "techniques" / "camera_shots.csv"
TOTAL_TERMS = 629


def test_drama_index_leaves_out_short_form_but_keeps_everything_else():
    rows = load_terms(TERMS, LEGACY)
    from_terms = [r for r in rows if r["source"] == TERMS_SOURCE]
    everything = load_terms(TERMS, LEGACY, include_short_form=True)
    assert len([r for r in everything if r["source"] == TERMS_SOURCE]) == TOTAL_TERMS
    assert {r["category"] for r in everything} - {r["category"] for r in rows} == {
        "Video Format & Type", "Ad Structure & Formula", "Social & Short-Form Technique"}
    assert len(SHORT_FORM_CATEGORIES) == 3
    assert {r["domain"] for r in from_terms} == {"camera", "light", "post", "story", "format", "animation"}


def test_a_technique_in_both_sources_is_one_row_that_keeps_the_legacy_fields():
    rows = load_terms(TERMS, LEGACY)
    push = [r for r in rows if r["slug"] == "push_in_creep_in" or norm(r["name"]) == "pushin"]
    assert len(push) == 1
    assert push[0]["source"] == TERMS_SOURCE
    assert push[0]["example_film"] == "The Godfather", "kept from camera_shots.csv"
    assert push[0]["use_case"].startswith("Close pressure in"), "the feeling-first legacy use_case wins"
    assert push[0]["prompt_phrase"], "prompt_phrase comes from the terms database"
    assert len([r for r in rows if norm(r["name"]) == "dolly"]) == 1
    legacy_only = [r for r in rows if r["source"] == LEGACY_SOURCE]
    assert legacy_only and all(r["domain"] == "camera" for r in legacy_only)
    assert not {norm(r["name"]) for r in legacy_only} & {norm(r["name"]) for r in rows if r["source"] == TERMS_SOURCE}


def test_rows_are_unique_per_source_and_hash_and_carry_the_new_columns():
    rows = load_terms(TERMS, LEGACY)
    assert len({(r["source"], r["row_hash"]) for r in rows}) == len(rows)
    one = next(r for r in rows if r["slug"] == "push_in_creep_in")
    assert one["tags"] and isinstance(one["ai_supported"], bool)
    assert {x["type"] for r in rows for x in r["related"]} <= {"pairs_well_with", "alternative_to", "contrast_to"}


def test_effect_text_leads_with_the_feeling_and_ends_with_the_label():
    text = effect_text("Emotional realization", "Builds intimacy", "Camera moves forward", "Dolly",
                       "Camera Movement", "dolly in", ["tense", "intimate"])
    assert text.startswith("Emotional realization. Builds intimacy. Camera moves forward.")
    assert "(Dolly, Camera Movement; also called dolly in)" in text and text.endswith("Tags: tense, intimate.")


def test_every_row_key_is_a_column_of_the_table():
    schema = (ROOT / "Database" / "schema_v6.sql").read_text(encoding="utf-8")
    block = re.search(r"create table public\.craft_techniques \((.*?)\n\);", schema, re.S)
    assert block
    columns = set(re.findall(r"^\s{2}(\w+)\s", block.group(1), re.M))
    all_rows = load_terms(TERMS, LEGACY, include_short_form=True)
    keys = set().union(*(r.keys() for r in all_rows))
    assert all(r.keys() == all_rows[0].keys() for r in all_rows), "bulk inserts need identical keys"
    assert keys <= columns, keys - columns
    migration = next((ROOT / "supabase" / "migrations").glob("*_cinematography_terms.sql")).read_text(encoding="utf-8")
    for column in keys - {"domain", "category", "name", "abbreviation", "definition", "use_case",
                          "example_film", "effect_text", "source", "row_hash"}:
        assert f"add column {column} " in migration, column


@pytest.mark.parametrize("file, old, new", [
    ("term_relations.csv", "1,7,126,", "1,7,99999,"),
    ("term_tags.csv", "1,18\n", "1,9999\n"),
])
def test_a_dangling_reference_is_an_error_not_a_silent_drop(tmp_path, file, old, new):
    copy = tmp_path / "terms"
    shutil.copytree(TERMS, copy)
    path = copy / file
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError):
        load_terms(copy, LEGACY)
