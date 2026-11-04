"""Phase 7 (plan/2026-11-04b): after the plan, the shot producer reads a shot's director's card.

A shot with a card (and the intent `adam_write` stored with it, `by = "adam"`) skips the intent agent, tells the DoP the
card's camera as fixed, keeps the card's performance per beat, and carries its sound and silence into the Veo prompt. A
shot without a card is untouched. Every check runs on the part and on the legacy engine it must agree with. Nothing here
calls a model.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "services" / "shot_producer"))

from shot_producer.engine import card as legacy_card
from shot_producer.engine import model as legacy_model
from shot_producer.engine import serialize as legacy_serialize
from shot_producer.engine import shots as legacy_shots
from tests.parity.adapters import run_case
from tests.parity.harness import outcome
from tests.services.production_fixture import CANON
from tests.services.shot_producer.conftest import fixture_scene

from contracts.staging import ShotIntent
from hiru_ai.core import parts
from hiru_ai.steps.prompt_lint import step as lint

CARD = {
    "number": 1, "moments": ["m1"], "title": "Her smile outlives her eyes", "size": "CU", "arrangement": "single",
    "subject": "Kamala", "angle": "low", "height": "chest", "lens_feel": "long", "movement": "push_in",
    "focus": {"kind": "rack", "from": "Kamala", "to": "Nimal"},
    "composition": {"foreground": "Nimal's shoulder, soft", "negative_space": "", "frame_side": "left"},
    "eyeline": "right", "blocking_in_shot": "she turns away",
    "beats": [{"window": [0, 2], "action": "she listens", "performance": "the smile holds a beat too long",
               "camera": "slow push-in"}],
    "lines": [{"line_id": "L1", "on_speaker": False, "over_whom": "Kamala"}],
    "sound": {"ambience": "the room drains to her breath", "effects": "a phone buzzing on wood", "music": "",
              "silence": False, "pre_lap": "", "carries_over": ""},
    "purpose": "The turn", "emotional_beat": "warmth to dread", "take_s": 6}
COVERAGE = {"axis": "stay on the street side", "motif": "a held close-up", "progression": "wide to close"}
ADAM_INTENT = {"purpose": "The turn", "what_we_see": "she listens", "emotional_beat": "warmth to dread",
               "on_screen": ["C01"], "heard_only": [], "voice_source": "", "by": "adam", "made_for": "",
               "written_at": None}


@pytest.fixture
def world() -> dict[str, Any]:
    scene_row, lines, rows = copy.deepcopy(fixture_scene(0))  # the fixture's rows are shared: never edit them
    rows[0].update({"card": CARD, "intent": ADAM_INTENT, "planner": "adam"})
    rows[0]["beats"] = [{**b, "performance": "she does not look up"} if i == 0 else b
                        for i, b in enumerate(rows[0]["beats"])]
    mod = parts.step("serialize", "model")
    settings = {"id": "p", "title": "Harbour Lights", "orientation": "horizontal", "settings": {}}
    persona = {"name": "Grounded", "style_note": "Held frames.", "charter": "Hold."}
    prod = mod.production_input(settings, CANON, persona)
    old_prod = legacy_model.production_input(settings, CANON, persona)
    return {"mod": mod, "prod": prod, "old_prod": old_prod, "rows": rows,
            "scene": mod.scene_input(scene_row, rows, lines, CANON, prod, (None, None)),
            "old_scene": legacy_model.scene_input(copy.deepcopy(scene_row), copy.deepcopy(rows), lines, CANON,
                                                  old_prod, (None, None))}


def test_the_card_reader_gives_the_panels_words_only_where_there_is_an_exact_one():
    cam = parts.step("serialize", "card").camera(CARD)
    assert cam == {"angle": "Low angle", "lens": "85mm", "movement": "Dolly in", "aperture": "f/2"}
    assert parts.step("serialize", "card").camera({**CARD, "angle": "dutch", "movement": "crane"}) == {
        "lens": "85mm", "aperture": "f/2"}
    assert parts.step("serialize", "card").of({"card": {}}) == {} and parts.step("serialize", "card").of({}) == {}


def test_the_legacy_engines_card_reader_is_a_copy_of_the_parts():
    new = parts.step("serialize", "card")
    for card in (CARD, {**CARD, "sound": {"silence": True}}, {}):
        assert new.camera(card) == legacy_card.camera(card)
        assert new.decisions_text(card) == legacy_card.decisions_text(card)
        assert new.sound_text(card) == legacy_card.sound_text(card)
        assert new.silent(card) == legacy_card.silent(card) and new.voiced_off(card) == legacy_card.voiced_off(card)


def test_a_shot_with_the_adam_intent_never_needs_the_intent_agent(world: dict[str, Any]):
    shot = world["scene"].shots[0]
    assert ShotIntent.of(shot.row).by == "adam" and not shot.intent_needed()  # type: ignore[union-attr]
    assert not world["old_scene"].shots[0].intent_needed()
    other = world["scene"].shots[1]
    assert other.intent_needed()  # a classic shot with no intent still does


def test_the_dop_is_told_the_cards_camera_as_fixed_and_the_performance_as_a_note_to_keep(world: dict[str, Any]):
    shots = parts.step("serialize", "shots")
    new = shots.shot_block(world["scene"].shots[0], 4, None, same_call=True)
    old = legacy_shots.shot_block(world["old_scene"].shots[0], 4, None, same_call=True)
    assert new == old
    assert "DIRECTOR'S CAMERA, FROM THE SHOT CARD (fixed; express it, do not change it)" in new
    assert "angle: low" in new and "rack from Kamala to Nimal" in new and "performance: she does not look up" in new
    plain = shots.shot_block(world["scene"].shots[1], 4, None, same_call=True)
    assert "SHOT CARD" not in plain and "performance:" not in plain  # a classic shot reads as it always did


def test_the_card_wins_the_recommendation_but_never_the_size(world: dict[str, Any]):
    shots = parts.step("serialize", "shots")
    asked = {"recommendation": {"angle": "High angle", "lens": "28mm", "movement": "Static", "framing": "Wide shot"}}
    got = shots.recommendation(asked, world["scene"].shots[0], world["scene"])
    assert (got.angle, got.lens, got.movement) == ("Low angle", "85mm", "Dolly in")
    assert got == legacy_shots.recommendation(asked, world["old_scene"].shots[0], world["old_scene"])
    classic = shots.recommendation(asked, world["scene"].shots[1], world["scene"])
    assert (classic.angle, classic.lens) == ("High angle", "28mm")


def test_the_cards_performance_is_kept_over_what_the_dop_wrote(world: dict[str, Any]):
    shots = parts.step("serialize", "shots")
    ir = {"beats": [{"time": "0-2s", "performance": "the DoP's own idea"}]}
    new = shots.fit_beats(ir, world["scene"].shots[0])["beats"][0]["performance"]
    assert new == "she does not look up" == legacy_shots.fit_beats(ir, world["old_scene"].shots[0])["beats"][0][
        "performance"]
    assert shots.fit_beats(ir, world["scene"].shots[1])["beats"][0]["performance"] == "the DoP's own idea"


def test_the_cards_sound_reaches_the_prompt_and_a_card_without_one_keeps_the_room_tone(world: dict[str, Any]):
    logic = parts.step("serialize", "logic")
    shot = world["scene"].shots[0]
    shot.sound_mode = "ambient"
    text = logic._audio_text(shot, {})
    assert "room: the room drains to her breath" in text and "effects: a phone buzzing on wood" in text
    old = world["old_scene"].shots[0]
    old.sound_mode = "ambient"
    assert legacy_serialize._audio_text(old, {}) == text
    bare = world["scene"].shots[1]
    bare.sound_mode = "ambient"
    assert "natural sound of the location" in logic._audio_text(bare, {})


@pytest.mark.parametrize("engine", ["legacy", "graph"])
def test_the_intent_agent_is_not_asked_about_a_shot_with_a_card_even_when_forced(engine: str):
    rows = {"1": {"card": CARD, "intent": ADAM_INTENT, "planner": "adam"}}
    reply = {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]}, "replies": {
        "shot_intent": [{"shots": [{"number": n, "purpose": "p", "what_we_see": "w", "emotional_beat": "b",
                                    "on_screen": ["C01"], "heard_only": [], "voice_source": "", "split_after": -1,
                                    "split_reason": ""} for n in (1, 2, 3, 4)], "coverage": COVERAGE}] * 2,
        "design_review": [{"acceptable": True, "notes": []}]}}
    got = outcome(run_case("shot_producer", {"runs": [{"force": True}], "rows": rows}, copy.deepcopy(reply), engine))
    stored = {k: v for k, v in got["intents"].items()}
    assert "adam" not in {i["by"] for i in stored.values()}  # the card's intent was not rewritten...
    first = next(r for r in got["shot_rows"].values() if r.get("planner") == "adam")
    assert first["intent"]["by"] == "adam" and first["intent"]["purpose"] == "The turn"  # ...and is still there


def test_both_engines_agree_on_a_scene_with_a_card_shot():
    rows = {"1": {"card": CARD, "intent": ADAM_INTENT, "planner": "adam"}}
    model = {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]},
             "replies": {"shot_intent": [{"shots": [{"number": n, "purpose": "p", "what_we_see": "w",
                                                     "emotional_beat": "b", "on_screen": ["C01"], "heard_only": [],
                                                     "voice_source": "", "split_after": -1, "split_reason": ""}
                                                    for n in (1, 2, 3, 4)], "coverage": COVERAGE}],
                         "design_review": [{"acceptable": True, "notes": []}]}}
    got = {e: outcome(run_case("shot_producer", {"runs": [{}], "rows": rows}, copy.deepcopy(model), e))
           for e in ("legacy", "graph")}
    assert got["graph"] == got["legacy"]


# ── the prompt lint learns the card ───────────────────────────────────────────────────────────


def section(ident: str, text: str) -> dict[str, Any]:
    return {"id": ident, "title": ident.title(), "segments": [{"text": text}]}


def prompt(prose: str) -> dict[str, Any]:
    return {"sections": [section(i, "x") for i in ("style", "camera", "action", "constraints")]
            + [section("format", "Aspect ratio 16:9. Duration 6 seconds.")], "prose": prose, "checks": []}


def codes(prose: str, card: dict[str, Any]) -> list[str]:
    shot = {"id": "s1", "duration_s": 6, "sound_mode": "ambient", "camera_link": "cut", "card": card}
    return [f["code"] for f in lint.run({"prompt": prompt(prose), "shot": shot, "lines": []})["findings"]]


def test_a_prompt_that_keeps_what_the_card_decided_is_clean():
    prose = ("Over 6 seconds: she listens. The smile holds a beat too long. The room drains to her breath; a phone "
             "buzzing on wood. Her voice is heard off screen.")
    assert codes(prose, CARD) == []


def test_a_prompt_that_drops_the_cards_performance_sound_or_off_screen_voice_is_flagged():
    found = codes("Over 6 seconds: she listens. Cut.", CARD)
    assert found == ["voice_not_off_screen", "performance_dropped", "sound_cue_missing"]


def test_a_card_that_asks_for_silence_must_have_silence_stated():
    silent = {**CARD, "lines": [], "beats": [], "sound": {**CARD["sound"], "effects": "", "silence": True}}
    assert codes("A face. Nothing else.", silent) == ["silence_unstated"]
    assert codes("A face. Silence: no music, no room tone.", silent) == []


def test_a_shot_without_a_card_is_linted_as_before():
    assert codes("anything", {}) == []
