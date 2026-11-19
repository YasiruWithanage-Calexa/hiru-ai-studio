"""The cut order honours a blend note that opens a moment (plan/2026-11-18b phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.raphael.stored import StoredRaphael
from hiru_ai.steps.raphael.raphael_write.logic import order

# The coverage lab's Raphael plan of Api Denna E01-S03: c08 (3H-1) is the establishing wide, "Open moment 1 before c01"
LAB = Path(__file__).resolve().parents[7] / "lab" / "coverage" / "runs" / "coverage" / "12_raphael" / "E01-S03.json"


def _stored() -> StoredRaphael:
    return StoredRaphael.model_validate(json.loads(LAB.read_text(encoding="utf-8"))["result"])


def test_a_cinematic_clip_that_opens_a_moment_before_a_clip_is_cut_ahead_of_it():
    stored = _stored()
    assert [c.id for c in order(stored.clips, stored.blend_notes)] == [
        "c08", "c01", "c02", "c03", "c04", "c05", "c06", "c07"
    ]


def test_without_the_notes_the_order_is_moment_stage_id_as_before():
    stored = _stored()
    assert [c.id for c in order(stored.clips)] == ["c01", "c02", "c08", "c03", "c04", "c05", "c06", "c07"]


def test_a_note_that_only_opens_a_moment_goes_ahead_of_the_moments_first_clip():
    stored = _stored()
    opens = "c08 - Opens moment 1 with the roadside view."
    notes = [opens if n.startswith("c08") else n for n in stored.blend_notes]
    assert [c.id for c in order(stored.clips, notes)][:3] == ["c08", "c01", "c02"]


def test_a_note_that_names_another_clip_only_in_passing_keeps_the_usual_place():
    stored = _stored()
    # c06 names c05 ("cut from c05") but says nothing about playing before it
    assert [c.id for c in order(stored.clips, stored.blend_notes)].index("c06") == 6
