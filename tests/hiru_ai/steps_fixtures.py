"""Scenes the step tests and the step/legacy parity tests share (plan/2026-11-03 Phase 2).

`felt_scene` is the Kasun / Anudi phone scene with a reading (a turn at the call, Anudi's reaction held) and a staging
map (stall and street): the same scene tests/services/shot_producer/test_feeling.py uses. `teleporting_scene` moves
Anudi from the street back to the stall with nothing to show the way.
"""
from __future__ import annotations

from typing import Any

from contracts import reading as rd
from contracts import sceneplan, stagemap
from tests.services.production_fixture import PHONE_CANON, PID, phone_scene

CAST = ["Kasun", "Anudi", "Anudi's Father"]
PRODUCTION = {"id": str(PID), "title": "Harbour Lights", "orientation": "horizontal", "settings": {}, "summary": ""}
PERSONA = {"id": "p1", "name": "Classic", "specialty": "teledrama", "style_note": "warm, unhurried",
           "charter": "Keep it humane."}

MARKS = [
    {"block": 0, "who": "Kasun", "zone": "stall", "facing": "right", "frame_side": "left", "holding": ""},
    {"block": 2, "who": "Anudi", "zone": "street", "facing": "left", "frame_side": "right", "holding": "her phone"},
]

IR: dict[str, Any] = {
    "setting": "Kasun's food three-wheeler on a Colombo roadside",
    "cinematography": {"camera": "slider, 85mm, f/2.8", "angle": "eye level", "framing": "medium close-up",
                       "movement": "slow lateral slide", "white_balance": "5600K", "color_tone": "warm",
                       "depth_of_field": "Medium", "lens_artifacts": "none"},
    "lighting": "Open shade under the umbrella.",
    "subjects": [{"id": "C02", "description": "Anudi, chest-up", "action": "smiles, then answers the phone"},
                 {"id": "C03", "description": "only a voice through the phone", "action": "speaks"}],
    "beats": [{"time": "0-3s", "camera": "MCU", "director_line": "She smiles.", "action": "smiles",
               "performance": "her smile holds, then slips"},
              {"time": "3-6s", "camera": "holds", "director_line": "The phone rings.", "action": "answers"},
              {"time": "6-8s", "camera": "settles", "director_line": "She listens.", "action": "listens"}],
    "audio": "street bed, a ringtone",
    "first_frame": {"composition": "Anudi at the stall, smiling", "subjects": ["Anudi smiling"],
                    "setting": "the stall", "lighting": "open shade"},
    "on_screen": ["C02"],
}


def _with_reading(marks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    scene, lines, shots = phone_scene()
    items = sceneplan.items_for(scene["script"], lines)
    reading = rd.validate({
        "about": "A smile is cut short by a call.", "value": {"start": "joy", "end": "dread"}, "tone": "warm, uneasy",
        "units": [{"from_block": 0, "to_block": 1, "wants": [{"character": "Kasun", "verb": "to impress"}],
                   "turn_block": None},
                  {"from_block": 2, "to_block": 5, "wants": [{"character": "Anudi", "verb": "to hide it"}],
                   "turn_block": 5}],
        "subtext": [],
        "breath": [{"after_block": 5, "kind": "reaction", "who": "Anudi", "seconds": 1.5, "priority": 1,
                    "why": "the call breaks her joy"}],
        "ending": "Anudi's face, the smile gone."}, items, CAST, version=1, by="model")
    staging = stagemap.validate({"zones": ["stall", "street"], "marks": marks}, items, CAST, version=1, by="model")
    scene = {**scene, "reading": reading.model_dump(mode="json"), "staging": staging.model_dump(mode="json")}
    return scene, lines, shots


def felt_scene() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    return _with_reading(MARKS)


def teleporting_scene() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    return _with_reading([*MARKS, {"block": 5, "who": "Anudi", "zone": "stall", "facing": "left",
                                   "frame_side": "right", "holding": ""}])


def bundle(scene: dict[str, Any], lines: list[dict[str, Any]], shots: list[dict[str, Any]],
           **extra: Any) -> dict[str, Any]:
    return {"scene": scene, "lines": lines, "shots": shots, "canon": PHONE_CANON, "cast": CAST, **extra}


def run_ctx(scene: dict[str, Any], lines: list[dict[str, Any]], shots: list[dict[str, Any]], *,
            canon: list[dict[str, Any]] | None = None, actor: str | None = None, corpora: tuple[str, ...] = (),
            **fixtures: Any) -> Any:
    """A RunContext over in-memory ports holding one scene (production and ids taken from the scene row)."""
    from uuid import UUID

    from hiru_ai.core.context import RunContext
    from hiru_ai.core.fakes import ports_from

    production = {**PRODUCTION, "id": scene["production_id"]}
    ports = ports_from({"production": production, "scenes": [scene], "lines": lines, "shots": shots,
                        "canon": PHONE_CANON if canon is None else canon, **fixtures})
    return RunContext(production_id=UUID(scene["production_id"]), actor_user_id=UUID(actor) if actor else None,
                      ports=ports, corpora=corpora)
