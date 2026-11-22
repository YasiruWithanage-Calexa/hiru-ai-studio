"""The Shot prompt agent's one door (plan/2026-11-20d D4, D5, D6): brief, ask, check, repair once, store.

    on()                                           a model to call (no switch: the agent runs whenever one can be)
    facts_for(shot, scene, prod, frame, ...)       -> the facts the brief, the checks and the video assembly read
    write(ctx, facts, ...)                         -> Written: the record to store on the shot, or why there is none
    needs(world, shot_row)                         -> "current" | "video_only" | "both": what a "Generate video prompt"
                                                      needs (D4 b)
    drawn_from(record, frame)                      -> the accepted frame was painted from this stored shot prompt: a
                                                      video-only rewrite may keep it (plan/2026-11-22c)

Called from the shot producer (`systems/shot_producer`): before a frame is painted ("Draw first frame" runs the shot
producer first for a shot with no current shot prompt, D4 a), for "Generate video prompt" (the stored prompt when it is
current, else ONE call in video-only mode when only the video is out of date, D4 b), and for "Rewrite prompts" (one
shot, or every shot of a scene, D4 c). A failed answer gets ONE repair; still failing, nothing is stored and the caller
reports the faults (D6): the old prompt and frame stay.

`shot`, `scene` and `prod` are the `serialize` step's `ShotInput`, `SceneInput` and `ProductionInput`; `world` is the
`frame_compose` step's world of the scene (it says whether a stored shot prompt is current, with the same pins the
frame and the shot screen use).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts import picture_pins
from contracts.frame_brief import agent_camera
from contracts.producer import PersonEdits, camera_changes
from contracts.staging import ShotIntent
from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings

_log = logging.getLogger(__name__)
Row = dict[str, Any]
AGENT = "shot_prompter"
MAX_OUTPUT = 12000  # D2: the lab's cap
NEEDS_MODEL = "the Shot prompt agent needs a model"
# plan/2026-11-22c (option 1): a video-only rewrite writes the video from the stored opening and frame words, so it is
# only safe while the accepted frame was painted from those words. Otherwise it is said, never guessed.
FRAME_NOT_FROM_PROMPT = ("the accepted first frame was not drawn from this shot's prompt words, so a video-only "
                         "rewrite could describe a different picture: draw the first frame again from the prompts, "
                         "then rewrite")


@dataclass
class Written:
    record: Row | None = None  # what `design.shot_prompt` stores; None when nothing could be written
    answer: Row | None = None
    faults: list[str] = field(default_factory=list)
    repaired: bool = False
    failed: str = ""  # why nothing was written, in words for the job's warning


def on() -> bool:
    return llm.models_enabled()


def model_name() -> str:
    return str(get_settings().openai.model_shot_prompter)


def facts_for(shot: Any, scene: Any, prod: Any, frame: Row | None, *, lids: Mapping[str, str],
              wardrobe: Mapping[str, str] | None = None) -> Row:
    """The `video_prompt` step's clip facts plus the frame's: the planner's opening picture, the state the shot opens
    in (Raphael's ledger), and the camera (the Camera agent's design, or the panel's fields)."""
    facts: Row = parts.step("video_prompt", "facts").clip_facts(shot, scene, prod, frame, lids=dict(lids),
                                                                wardrobe=dict(wardrobe or {}))
    step = parts.module("step", "shot_prompt", "step")
    camera = shot.camera(scene)
    facts["camera"] = step.run({"op": "camera", "settings": camera.model_dump(), "block": agent_camera(shot.row),
                                "sentence": facts.get("camera_sentence") or ""})["camera"]
    ir = shot.row.get("ir") or {}
    facts["first_frame"] = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    intent = ShotIntent.of(shot.row)
    facts["opens_state"] = " ".join((intent.opens if intent else "").split())
    facts["video_note"] = " ".join(PersonEdits.of(shot.row).video_note.split())  # plan/2026-11-22c
    return facts


def drawn_from(record: Mapping[str, Any] | None, frame: Mapping[str, Any] | None) -> bool:
    """The accepted `frame` was painted from the stored shot prompt `record`: the frame's picture pin holds the hash of
    the record's opening state (a frame drawn from the prompts pins it, `frame_compose` `pins_now(frame=True)`). A frame
    drawn from code's words, before the Shot prompt agent, or uploaded pins none, and so does not match."""
    want = picture_pins.short(picture_pins.opening_text((record or {}).get("opening")))
    pins = (frame or {}).get("pins")
    picture = (pins.get("picture") if isinstance(pins, Mapping) else None) or {}
    return bool(want) and isinstance(picture, Mapping) and str(picture.get("opening") or "") == want


def timed(record: Mapping[str, Any] | None) -> bool:
    """The stored shot prompt gives every step of its video a range (lab/timecodes, 2026-11-21)."""
    flow = (((record or {}).get("video") or {}).get("flow") or []) if isinstance(record, Mapping) else []
    return bool(flow) and all(isinstance(s, Mapping) and s.get("start_s") is not None and s.get("end_s") is not None
                              for s in flow)


def needs(world: Any, shot_row: Row) -> str:
    """What this shot's prompts need (D4 b): "current" (assemble from the stored prompt, no call), "video_only" (only
    the video is out of date: the motion, the script or the shot moved, or it was written before timecodes; the
    picture, the people and their looks did not) or "both" (no stored prompt, or the picture moved)."""
    reasons = world.shot_prompt_reasons(shot_row)
    record = (shot_row.get("design") or {}).get("shot_prompt")
    if not reasons:
        return "current" if timed(record) else "video_only"
    made = (record or {}).get("pins") if isinstance(record, Mapping) else None
    if not made:
        return "both"
    now = world.pins_now(shot_row)
    picture_moved = camera_changes(made.get("picture") or {}, now["picture"], head="x")
    people_moved = set(made.get("canon") or {}) != set(now["canon"]) or {
        k: (v or {}).get("stamp") for k, v in (made.get("looks") or {}).items()} != {
        k: (v or {}).get("stamp") for k, v in (now.get("looks") or {}).items()} or any(
        int(v) != int((now["canon"] or {}).get(k) or 0) for k, v in (made.get("canon") or {}).items())
    return "both" if picture_moved or people_moved or not made.get("picture") else "video_only"


def write(ctx: RunContext, facts: Row, *, scene_part: str, pins: Row, mode: str = "both",
          stored: Mapping[str, Any] | None = None, job_id: str = "") -> Written:
    """One shot's prompts: brief → agent → checks → ONE repair → the record (D6). `pins`: the shot's pins now (the
    frame_compose world's `pins_now`), stored with the record. `mode` "video_only" hands the agent the `stored`
    opening and frame as fixed and puts them back in its answer."""
    out = Written()
    if not on():
        out.failed = NEEDS_MODEL
        return out
    step = parts.module("step", "shot_prompt", "step")
    brief = step.run({"op": "brief", "facts": facts})
    inp: Row = {"scene": scene_part, "shot": brief["shot"], "camera": brief["camera"], "cards": brief["cards"],
                "mode": mode, "video_note": str(facts.get("video_note") or "")}
    if mode == "video_only":
        inp["fixed"] = json.dumps({"opening": (stored or {}).get("opening"), "frame": (stored or {}).get("frame")},
                                  ensure_ascii=False)
    agent = agents.build(AGENT)

    def ask(extra: Row) -> Row:
        answer = agent.run({**inp, **extra}, ctx, max_output=MAX_OUTPUT).model_dump(mode="json")
        if mode == "video_only":
            answer = step.run({"op": "fixed", "answer": answer, "stored": stored})["answer"]
        return dict(answer)

    try:
        answer = ask({})
        faults = step.run({"op": "check", "answer": answer, "facts": facts, "mode": mode})["faults"]
        if faults:  # D6: ONE repair, shown its first answer and exactly what code found
            out.repaired = True
            answer = ask({"repair": faults, "previous": json.dumps(answer, ensure_ascii=False)})
            faults = step.run({"op": "check", "answer": answer, "facts": facts, "mode": mode})["faults"]
    except Exception:  # the model failed or is down: nothing is stored, and the job says so
        _log.warning("the Shot prompt agent failed for %s", facts.get("code"), exc_info=True)
        out.failed = "the model call failed"
        return out
    out.answer, out.faults = answer, list(faults)
    if faults:
        out.failed = "; ".join(faults)[:400]
        return out
    out.record = step.run({"op": "record", "answer": answer, "model": model_name(), "job_id": job_id, "pins": pins,
                           "mode": mode, "repaired": out.repaired})["record"]
    return out
