"""Memory that disagrees with itself, or asks for what the system cannot make, is reported and left for a person."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.memory_conflicts import logic, step


def entry(id_: str, says: str, *, topic: str = "camera", applies_to: str = "production", document: str | None = "d1",
          status: str = "draft") -> dict[str, Any]:
    return {"id": id_, "topic": topic, "applies_to": applies_to, "says": says, "strength": "prefer", "status": status,
            "document_id": document}


def kinds(found: list[dict[str, Any]]) -> list[str]:
    return [c["kind"] for c in found]


def test_a_lens_the_camera_does_not_have_is_reported_and_the_ones_it_has_are_not():
    found = logic.find([entry("a", "Use 24mm for geography, 35mm for movement and 50mm for emotional impact.",
                              applies_to="when:action scenes")])
    assert kinds(found) == ["lens"] and "24mm" in found[0]["text"] and "28mm, 35mm, 50mm, 85mm" in found[0]["text"]
    assert logic.find([entry("a", "Use 50mm and 85mm lenses, shallow focus.", applies_to="when:love scenes")]) == []
    found = logic.find([entry("a", "Use a 135 mm lens for the chase and a 14mm for the van.")])
    assert kinds(found) == ["lens", "lens"]


def test_a_shot_length_veo_cannot_make_is_reported_and_a_limit_is_not():
    assert kinds(logic.find([entry("a", "Hold every shot for 10 seconds.", topic="edit")])) == ["length"]
    assert kinds(logic.find([entry("a", "Use a 5-second take for the reveal.", topic="edit")])) == ["length"]
    assert logic.find([entry("a", "An 8 second shot on the wedding.", topic="edit")]) == []  # Veo makes 8
    assert logic.find([entry("a", "No shot longer than 10 seconds.", topic="edit")]) == []  # a limit, not a length
    assert logic.find([entry("a", "Slow motion lasts 2 seconds.", topic="edit")]) == []  # not a shot length


def test_two_documents_that_say_different_things_about_the_same_thing_are_reported_with_the_newer_suggested():
    rows = [entry("a", "Natural light only.", topic="visual", document="d1"),
            entry("b", "Hard sodium light.", topic="visual", document="d2")]
    (conflict,) = logic.find(rows, {"d1": "2026-11-01T00:00:00+00:00", "d2": "2026-11-04T00:00:00+00:00"})
    assert conflict["kind"] == "disagree" and conflict["ids"] == ["a", "b"]
    assert "Natural light only." in conflict["text"] and "newer document's entry is suggested" in conflict["text"]
    assert conflict["text"].split("suggested (")[1].startswith("visual · production: Hard sodium light.")
    older = logic.find(rows, {"d1": "2026-11-09T00:00:00+00:00", "d2": "2026-11-04T00:00:00+00:00"})
    assert older[0]["text"].split("suggested (")[1].startswith("visual · production: Natural light only.")


def test_one_document_agrees_with_itself_and_the_same_direction_twice_is_not_a_conflict():
    one = [entry("a", "Handheld.", document="d1"), entry("b", "Fast cuts on impact.", document="d1")]
    assert logic.find(one) == []
    twice = [entry("a", "Handheld.", document="d1"), entry("b", "handheld.", document="d2")]
    assert logic.find(twice) == []


def test_different_topics_or_targets_do_not_conflict_and_a_rejected_or_a_persons_entry_is_not_a_side():
    assert logic.find([entry("a", "Handheld.", applies_to="place:Colombo", document="d1"),
                       entry("b", "Locked off.", applies_to="place:Mahawewa", document="d2")]) == []
    assert logic.find([entry("a", "Handheld.", topic="camera", document="d1"),
                       entry("b", "Warm.", topic="visual", document="d2")]) == []
    rejected = entry("b", "Locked off.", document="d2", status="rejected")
    assert logic.find([entry("a", "Handheld.", document="d1"), rejected]) == []
    assert logic.find([entry("a", "Handheld.", document="d1"), entry("b", "Locked off.", document=None)]) == []


def test_the_same_place_written_two_ways_is_one_target():
    rows = [entry("a", "Handheld.", applies_to="place:Colombo", document="d1"),
            entry("b", "Locked off.", applies_to="Place: colombo", document="d2")]
    assert kinds(logic.find(rows)) == ["disagree"]


def test_the_step_runs_from_json():
    out = step.run({"entries": [entry("a", "Use 24mm.")]})
    assert [c["kind"] for c in out["conflicts"]] == ["lens"]
