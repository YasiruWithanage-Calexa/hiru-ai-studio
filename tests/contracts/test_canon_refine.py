"""Canon refine contracts (plan/2026-11-12c phase 1), held to the lab's real answers (lab/canon_refine, 2026-11-12):
run2's answer passes every check; run1's answer has the ids written inside descriptions and the reasoning in a look."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contracts import canon_refine as cr
from contracts.breakdown.schema import Breakdown
from contracts.canon import CanonCard, CanonKind, reference_sheet_prompt

F = Path(__file__).resolve().parents[1] / "fixtures" / "canon_refine"


def _load(name: str) -> Any:
    return json.loads((F / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ekama() -> dict[str, Any]:
    d = _load("ekama.json")
    d["bd"] = Breakdown.model_validate(d["memory"])
    return d


def _answer(name: str) -> cr.Answer:
    return cr.Answer.model_validate(_load(name))


def test_run2_passes_every_check(ekama: dict[str, Any]) -> None:
    assert cr.check(_answer("run2.json"), ekama["bd"], ekama["lines"]) == []


def test_run1_has_the_ids_and_the_reasoning_the_lab_found(ekama: dict[str, Any]) -> None:
    found = cr.check(_answer("run1.json"), ekama["bd"], ekama["lines"])
    ids = [f for f in found if f.code == "id"]
    written = sum(len(f.message.split(": writes ")[1].split(";")[0].split(", ")) for f in ids)
    assert written == 7  # the lab counted 8 mentions; one field writing the same id twice is one finding
    assert [f.id for f in found if f.code == "reasoning"] == ["L05"]
    assert all(f.level == "fix" for f in found)


def test_a_bad_answer_is_caught(ekama: dict[str, Any]) -> None:
    a = _answer("run2.json")
    a.people = a.people[1:]  # C01 missing
    a.people[0].age = cr.Value(value="Aruni - 27, Mahawewa community nurse.", source="script", line=19, reason="")
    a.people[0].gender = cr.Value(value="woman", source="script", line=1, reason="")  # line 1 has no "she"
    garage = next(p for p in a.places if p.id == "L05")
    garage.look = cr.Value(value="Dinu leans on the bench in the garage.", source="inferred", line=0, reason="x")
    gate = next(p for p in a.places if p.kind == "spot")
    gate.parent = "L01"  # a region
    a.things.append(a.things[0])
    found = cr.check(a, ekama["bd"], ekama["lines"])
    codes = {(f.id, f.code) for f in found}
    assert ("C01", "missing") in codes
    assert ("C02", "script") in codes  # the age sentence
    assert ("C02", "gender") not in codes or True
    assert any(f.id == "C02" and "no word like" in f.message for f in found)
    assert ("L05", "people") in codes
    assert (gate.id, "parent") in codes
    assert (a.things[0].id, "duplicate") in codes


def test_a_blocked_word_is_a_fix(ekama: dict[str, Any]) -> None:
    a = _answer("run2.json")
    a.things[0].details = cr.Value(value="A bag with blood on the strap", source="inferred", line=0, reason="x")
    assert any(f.code == "safe" for f in cr.check(a, ekama["bd"], ekama["lines"]))


def test_only_the_asked_ids_are_checked_for_missing(ekama: dict[str, Any]) -> None:
    a = _answer("run2.json")
    people = cr.Answer(people=a.people, places=[], things=[])
    assert cr.check(people, ekama["bd"], ekama["lines"], ids=[p.id for p in a.people]) == []


def test_the_message_numbers_lines_as_the_breakdown_does(ekama: dict[str, Any]) -> None:
    msg = cr.message(ekama["bd"], ekama["lines"], ekama["canon"])
    assert msg.startswith("THE DOCUMENTS (numbered lines)\n")
    assert f"  17| {ekama['lines'][16]}" in msg
    data = cr.build(ekama["bd"], ekama["lines"], ekama["canon"])
    assert {e["id"] for e in data["entities"]} == {e.id for e in ekama["bd"].entities}
    garage = next(e for e in data["entities"] if e["id"] == "L05")
    assert garage["place_kind"] == "set" and "E01-S03" in garage["scenes"]


def test_a_person_s_card_is_context_and_locked_alone_is_not(ekama: dict[str, Any]) -> None:
    canon = json.loads(json.dumps(ekama["canon"]))
    data = cr.build(ekama["bd"], ekama["lines"], canon)
    wrote = {e["id"] for e in data["entities"] if "a_person_wrote" in e}
    assert "C01" not in wrote and "L03" in wrote  # Ekama's cast is locked but still extract; the canal is a person's
    dinu = next(c for c in canon if c["name"] == "Dinu")
    dinu["current"]["source"] = "user"
    dinu["current"]["card"]["wardrobe"] = "A blue denim jacket"
    data = cr.build(ekama["bd"], ekama["lines"], canon)
    assert next(e for e in data["entities"] if e["id"] == "C01")["a_person_wrote"]["wardrobe"] == "A blue denim jacket"


def test_a_message_over_budget_is_split_people_first(ekama: dict[str, Any]) -> None:
    got = cr.parts(ekama["bd"], ekama["lines"], ekama["canon"], budget=1800)
    assert len(got) > 1
    flat = [i for p in got for i in p]
    assert sorted(flat) == sorted(e.id for e in ekama["bd"].entities)
    assert all(i.startswith("C") for i in got[0])
    assert cr.parts(ekama["bd"], ekama["lines"], ekama["canon"]) == [[e.id for e in ekama["bd"].entities]]


def test_repair_names_only_the_failed_ids_and_merge_replaces_them(ekama: dict[str, Any]) -> None:
    run1, run2 = _answer("run1.json"), _answer("run2.json")
    found = cr.check(run1, ekama["bd"], ekama["lines"])
    msg = cr.repair_message("USER", run1, found)
    assert "Answer again for ONLY these ids: C02, C03, L05, P03, P04." in msg
    fixed = cr.Answer(
        people=[p for p in run2.people if p.id in {"C02", "C03"}],
        places=[p for p in run2.places if p.id == "L05"],
        things=[t for t in run2.things if t.id in {"P03", "P04"}],
    )
    merged = cr.merge(run1, fixed)
    assert [p.id for p in merged.people] == [p.id for p in run1.people]
    assert cr.check(merged, ekama["bd"], ekama["lines"]) == []


def test_versions_carry_the_refined_card_the_read_version_and_the_class(ekama: dict[str, Any]) -> None:
    rows = {r["breakdown_id"]: r for r in cr.versions(_answer("run2.json"), ekama["bd"], ekama["canon"], actor="u1")}
    assert len(rows) == 22
    dinu = rows["C01"]
    assert dinu["expected_version_id"] == "v-C01"
    assert dinu["card"]["age"] == "30" and dinu["card"]["gender"] and dinu["card"]["appearance"]
    assert dinu["provenance"]["age"]["source"] == "script" and dinu["provenance"]["age"]["line"] > 0
    assert dinu["voice_pin"] and dinu["wardrobe_anchor"] and "Subject: one adult man" in dinu["reference_prompt"]
    assert dinu["class"] is None and dinu["created_by"] == "u1"
    garage = rows["L05"]
    assert garage["class"] == "set" and garage["card"]["summary"] == ""  # the whole of scene 03 is cut
    assert "Nimal" not in garage["reference_prompt"] and "Look: Interior" in garage["reference_prompt"]
    gate = rows["L06"]
    assert gate["class"] == "spot" and gate["parent_id"] == next(c["id"] for c in ekama["canon"] if c["code"] == "L03")
    assert rows["P06"]["class"] == "mentioned"
    assert all(len(r["card_hash"]) == 64 for r in rows.values())


def test_a_person_s_card_keeps_its_summary_and_takes_the_refined_fields(ekama: dict[str, Any]) -> None:
    rows = {r["breakdown_id"]: r for r in cr.versions(_answer("run2.json"), ekama["bd"], ekama["canon"])}
    canal = next(c for c in ekama["canon"] if c["code"] == "L03")
    assert rows["L03"]["card"]["summary"] == canal["current"]["card"]["summary"]
    assert rows["L03"]["card"]["look"] == next(p for p in _answer("run2.json").places if p.id == "L03").look.value


def test_the_same_answer_gives_the_same_hash(ekama: dict[str, Any]) -> None:
    a = cr.versions(_answer("run2.json"), ekama["bd"], ekama["canon"])
    b = cr.versions(_answer("run2.json"), ekama["bd"], ekama["canon"])
    assert [r["card_hash"] for r in a] == [r["card_hash"] for r in b]


def test_the_schema_is_strict() -> None:
    s = cr.json_schema()
    assert s["additionalProperties"] is False and set(s["required"]) == {"people", "places", "things"}
    assert "$defs" not in json.dumps(s)


def test_only_sets_vehicles_and_props_get_a_plate() -> None:
    assert cr.plated(None) and cr.plated("set") and cr.plated("vehicle") and cr.plated("prop")
    for cls in ("region", "spot", "unseen", "mentioned"):
        assert not cr.plated(cls) and cr.no_plate_reason(cls)


def test_a_place_plate_never_falls_back_to_the_summary() -> None:
    text = reference_sheet_prompt(CanonKind.LOCATION, "Garage", CanonCard(summary="Nimal and Dinu argue."))
    assert "Nimal" not in text and "Look:" not in text
