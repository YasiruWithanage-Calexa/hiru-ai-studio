"""The shot_producer system against the legacy pipeline on the model-driven paths the Phase 0 fixtures do not reach: a
model's intents, craft problems steering the technique lookup, a partial answer asked for again, and the review that
leads to one revision. Each case runs on both engines and the whole outcome is compared. Then the code halves (the
`serialize` step's modules) against the legacy functions they were ported from.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest
from shot_producer.engine import continuity as legacy_continuity
from shot_producer.engine import critique as legacy_critique
from shot_producer.engine import intent as legacy_intent
from shot_producer.engine import model as legacy_model
from shot_producer.engine import shots as legacy_shots
from shot_producer.engine import techniques as legacy_techniques

from hiru_ai.core import parts
from tests.parity.adapters import run_case
from tests.parity.harness import outcome
from tests.services.production_fixture import PHONE_CANON  # noqa: F401  (a canon with a phone call, used below)
from tests.services.shot_producer.conftest import dp_answer, fixture_scene


def same(inp: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Run one case on both engines; they must agree. -> the (graph) outcome."""
    got = {engine: outcome(run_case("shot_producer", copy.deepcopy(inp), copy.deepcopy(model), engine))
           for engine in ("legacy", "graph")}
    assert got["graph"] == got["legacy"]
    return got["graph"]


def intent_entry(n: int) -> dict[str, Any]:
    return {"number": n, "purpose": f"why shot {n} exists", "what_we_see": f"what shot {n} shows",
            "emotional_beat": "warmth to dread", "on_screen": ["C01"], "heard_only": [], "voice_source": "",
            "split_after": -1, "split_reason": ""}


INTENT = {"shots": [intent_entry(n) for n in (1, 2, 3, 4)],
          "coverage": {"axis": "stay on the street side", "motif": "a held close-up", "progression": "wide to close"}}
NO_NOTES = {"acceptable": True, "notes": []}
NOTE = {"acceptable": False, "notes": ["S01: closer on C01"]}


def test_a_models_intents_and_coverage_plan_are_written_and_saved_like_the_legacy_ones():
    got = same({"runs": [{}]}, {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]},
                                "replies": {"shot_intent": [INTENT], "design_review": [NO_NOTES]}})
    assert got["results"][0]["intents"] == 4
    assert {i["by"] for i in got["intents"].values()} == {"model"}
    assert got["scene_row"]["coverage"]["axis"] == "stay on the street side"
    assert [c["schema"] for c in got["llm"]][:2] == ["shot_intent", "craft_problems"]


def test_craft_problems_steer_the_technique_lookup_on_both_engines():
    got = same({"runs": [{}]}, {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]},
                                "replies": {"craft_problems": [{"problems": ["show a call turn a warm moment cold"]}]}})
    assert got["technique_queries"][0].startswith("show a call turn a warm moment cold")


def test_shots_the_model_skipped_are_asked_for_again_then_fall_back_to_rules():
    got = same({"runs": [{}]}, {"enabled": True, "replies": {"scene_design": [dp_answer([1, 2]), dp_answer([3])]}})
    planners = {s["design"]["planner"] for s in got["shot_rows"].values()}
    assert planners == {"model", "rules"}  # shot 4 is never answered
    assert [c["schema"] for c in got["llm"]].count("scene_design") == 2  # asked, then the missing shots once more


def test_a_review_note_leads_to_one_revision_that_is_kept_only_when_it_does_not_add_problems():
    got = same({"runs": [{}]}, {"enabled": True, "replies": {
        "scene_design": [dp_answer([1, 2, 3, 4]), dp_answer([1, 2, 3, 4], movement="Static")],
        "design_review": [NOTE]}})
    design = next(iter(got["shot_rows"].values()))["design"]
    assert design["review"]["notes"] == ["S01: closer on C01"]
    assert [c["schema"] for c in got["llm"]].count("scene_design") == 2  # the draft and ONE revision
    assert any("review notes" in str(e) for e in got["jobs"]["events"])


def test_a_content_reviewer_leaves_the_first_draft():
    got = same({"runs": [{}]}, {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]},
                                "replies": {"design_review": [NO_NOTES]}})
    assert "review" not in next(iter(got["shot_rows"].values()))["design"]


def test_a_person_keeps_their_intent_and_a_force_redoes_the_rest():
    got = same({"runs": [{}, {"force": True}]}, {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]},
                                                 "replies": {"shot_intent": [INTENT, INTENT]}})
    assert len(got["results"]) == 2


# ── the code halves against the functions they were ported from ────────────────────────────────


@pytest.fixture
def world() -> dict[str, Any]:
    scene_row, lines, rows = fixture_scene(0)
    from tests.services.production_fixture import CANON

    mod = parts.step("serialize", "model")
    prod = mod.production_input({"id": "p", "title": "Harbour Lights", "orientation": "horizontal", "settings": {}},
                                CANON, {"name": "Grounded", "style_note": "Held frames.", "charter": "Hold."})
    scene = mod.scene_input(scene_row, rows, lines, CANON, prod, (None, None))
    old_prod = legacy_model.production_input(
        {"id": "p", "title": "Harbour Lights", "orientation": "horizontal", "settings": {}}, CANON,
        {"name": "Grounded", "style_note": "Held frames.", "charter": "Hold."})
    old_scene = legacy_model.scene_input(copy.deepcopy(scene_row), copy.deepcopy(rows), lines, CANON, old_prod,
                                         (None, None))
    return {"prod": prod, "scene": scene, "old_prod": old_prod, "old_scene": old_scene, "canon": CANON}


def test_the_prompts_the_agents_read_are_the_legacy_ones(world: dict[str, Any]):
    intent, shots = parts.step("serialize", "intent"), parts.step("serialize", "shots")
    assert intent.production_block(world["prod"]) == legacy_intent.production_block(world["old_prod"])
    assert intent.scene_prompt(world["scene"], world["scene"].shots) == legacy_intent.scene_prompt(
        world["old_scene"], world["old_scene"].shots)
    assert shots.production_block(world["prod"]) == legacy_shots.production_block(world["old_prod"])
    new_ledger = parts.step("serialize", "continuity").ContinuityLedger(world["prod"].cast)
    old_ledger = legacy_continuity.ContinuityLedger(world["old_prod"].cast)
    group, old_group = world["scene"].shots[:2], world["old_scene"].shots[:2]
    assert shots.scene_tail(world["scene"], group, opening=new_ledger.identity_block(group[0]), others=[]) == \
        legacy_shots.scene_tail(world["old_scene"], old_group, opening=old_ledger.identity_block(old_group[0]),
                                others=[])


def test_the_rules_intent_and_design_are_the_legacy_ones(world: dict[str, Any]):
    intent, shots = parts.step("serialize", "intent"), parts.step("serialize", "shots")
    for new, old in zip(world["scene"].shots, world["old_scene"].shots, strict=True):
        got, want = intent.by_rules(new, world["scene"]), legacy_intent.by_rules(old, world["old_scene"])
        assert got.model_copy(update={"written_at": ""}) == want.model_copy(update={"written_at": ""})
        assert shots.design_by_rules(world["scene"], new) == legacy_shots.design_by_rules(world["old_scene"], old)
        ir, rec, why = shots.finish(shots.design_by_rules(world["scene"], new), new, world["scene"], world["prod"])
        old_ir, old_rec, old_why = legacy_shots.finish(legacy_shots.design_by_rules(world["old_scene"], old), old,
                                                       world["old_scene"], world["old_prod"])
        assert (ir, rec, why) == (old_ir, old_rec, old_why)
    assert intent.plan_by_rules(world["scene"]).progression == legacy_intent.plan_by_rules(
        world["old_scene"]).progression


def test_the_review_checks_are_the_legacy_ones(world: dict[str, Any]):
    crit, shots = parts.step("serialize", "critique"), parts.step("serialize", "shots")
    characters = [c for c in world["canon"] if c.get("kind") == "character"]
    for new, old in zip(world["scene"].shots, world["old_scene"].shots, strict=True):
        raw = shots.design_by_rules(world["scene"], new)
        ir, _, _ = shots.finish(raw, new, world["scene"], world["prod"])
        on = shots.on_screen_ids(raw, new)
        assert crit.free_problems(new, ir, on, characters, world["scene"]) == legacy_critique.free_problems(
            old, ir, on, characters, world["old_scene"])
        assert crit._draft(new, ir, on) == legacy_critique._draft(old, ir, on)


def test_the_technique_palette_and_the_ledger_are_the_legacy_ones():
    tech = parts.step("serialize", "techniques")
    rows = [{"name": "Push in", "abbreviation": "PI", "use_case": "Build tension", "definition": "Slowly closer."}]

    def lookup(query: str, vector: Any) -> list[dict[str, Any]]:
        return rows

    intents = ["a call turns cold", "A call turns cold ", "a chase", ""]
    assert tech.palette(intents, "Sri Lankan drama", lookup, None) == legacy_techniques.palette(
        intents, "Sri Lankan drama", lookup, None)
    assert tech.problems_block(["a", "b"]) == legacy_techniques.problems_block(["a", "b"])
    assert tech.articulate(None, ["x"]) == [] == legacy_techniques.articulate(None, ["x"])
    assert tech.articulate(lambda scenes: ["one"], ["x"]) == ["one"]

    def boom(scenes: list[str]) -> list[str]:
        raise RuntimeError("down")

    assert tech.articulate(boom, ["x"]) == []
