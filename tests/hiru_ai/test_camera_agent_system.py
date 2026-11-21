"""The Camera agent in the shot producer (plan/2026-11-20c D11 c, d; D10), with a scripted model: "Recommend
settings" designs a scene's camera in ONE call (no switch: whenever a model can be called) and keeps the planner's
IR; a clip still faulty after the ONE repair keeps the rule camera with a warning while the rest keep the agent's;
"Ask Camera" redoes one shot with the person's note; shots without a planner's IR go to the DoP; no model, no call."""
from __future__ import annotations

import json
import re
from contextlib import ExitStack
from dataclasses import replace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import BaseMessage

from contracts.producer import CameraSettings
from hiru_ai.core import camera
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.systems.shot_producer import graph
from tests.hiru_ai.test_shot_prompt_system import Vectors
from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter
from tests.services.fakes import FakeJobs
from tests.services.shot_producer.conftest import FakeStore, dp_answer, fixture_scene
from tests.services.shot_producer.test_shot_producer import payload

CAMERA = "camera_agent.design"
DOP = "shot_producer.scene"
CLIP = re.compile(r'<clip slate="([^"]+)" n="\d+">.*?SIZE (\S+) .*?take (\d+(?:\.\d+)?) s', re.S)
TIGHTER = {"WIDE": "MS", "MS": "MCU", "TWO": "MS", "OTS": "MCU", "MCU": "CU", "CU": "ECU", "INSERT": "ECU"}
WIDER = {"CU": "MCU", "MCU": "MS", "MS": "WIDE", "TWO": "WIDE", "OTS": "MS", "INSERT": "CU", "WIDE": "EWS"}
FOCUS = re.compile(r"Design clips? (.+?) only,")
MOVES = ["slow_creep", "push_in", "pull_out", "push_then_hold", "pan_right", "tilt_up", "hold"]


def clip_answer(slate: str, size: str, take: float, n: int, *, sentence: str = "") -> dict[str, Any]:
    move = MOVES[n % len(MOVES)]
    held = move == "hold"
    if move in ("push_in", "push_then_hold"):
        lands = TIGHTER.get(size, size)
    else:
        lands = WIDER.get(size, size) if move == "pull_out" else size
    return {"slate": slate, "moment": "dialogue", "intensity": 3, "power": "equal",
            "angle_reason": "low on her resolve" if n == 1 else "", "support": "operated", "move": move,
            "direction": "" if held else "toward her",
            "speed": "none" if held else "slow", "start_s": 0 if held else 0.5, "end_s": 0 if held else take - 0.5,
            "trigger": "" if held else "her look", "motivation": "she understands", "opens_on": "her face",
            "lands_on": "her eyes", "end_size": lands,
            "angle": "slightly_low" if n == 1 else "eye_level", "height": "chest" if n == 1 else "eye",
            "lens": "50mm", "aperture": "f/2.8", "focus": "shallow_isolation", "rack_from": "", "rack_to": "",
            "rack_at_s": 0, "composition": "rule_of_thirds", "composition_note": "her on the left third",
            "time": "normal", "axis": "side_a", "omni": "works", "why": "the line lands",
            "camera_sentence": sentence or ("The camera holds on her face." if held else
                                            "At eye level, the camera slowly moves closer as she looks up.")}


def answer(bad: str = "") -> Any:
    """The Camera agent for whatever clips it is sent (or the ones a one-shot call names). `bad`: the first clip's
    sentence (a fault in it)."""
    def reply(messages: list[BaseMessage]) -> dict[str, Any]:
        text = str(messages[-1].content)
        clips = [(s, z, float(t)) for s, z, t in CLIP.findall(text)]
        focus = FOCUS.search(text)
        if focus:
            wanted = [s.strip() for s in focus.group(1).split(",")]
            clips = [c for c in clips if c[0] in wanted]
        out = [clip_answer(s, z, t, n, sentence=bad if n == 0 else "") for n, (s, z, t) in enumerate(clips)]
        return {"camera_language": "Calm and close; eases in as she understands.", "arc": "3 throughout",
                "peak_slate": out[0]["slate"] if out else "", "clips": out}
    return reply


def world(*, ir: bool = True) -> FakeStore:
    scene, lines, rows = fixture_scene(0)
    if ir:  # a planner's IR on every shot (Raphael's, say), no camera design yet
        for r in rows:
            r["ir"] = dp_answer([int(r["number"])])["shots"][0] | {"beats": []}
            r["ir"].pop("number", None)
    return FakeStore(scene, lines, rows)


def run(store: FakeStore, *, replies: Any, on: bool = True,
        **state: Any) -> tuple[dict[str, Any], FakeJobs, list[str], list[str]]:
    jobs = FakeJobs()
    sent: list[str] = []

    def spy(r: Any) -> Any:
        def go(messages: list[BaseMessage]) -> Any:
            sent.append(str(messages[-1].content))
            return r(messages)
        return go

    with ExitStack() as stack:
        stack.enter_context(environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m-high",
                                        OPENAI__MODEL_MEDIUM="m-medium", OPENAI__MODEL_CAMERA_AGENT="m-camera"))
        cam = Endless([spy(replies)]) if callable(replies) else [spy(r) for r in replies]
        seen = stack.enter_context(scripted_models(
            {DOP: Endless([lambda messages: dp_answer([1, 2, 3, 4])]), CAMERA: cam},
            {"high": "m-high", "medium": "m-medium", "camera_agent": "m-camera"}))
        from hiru_ai.core import llm as door

        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))
        if not on:  # the Camera agent cannot be called (no model for it)
            stack.enter_context(patch.object(camera, "on", lambda: False))
        p = payload(scene_ids=[store.scene_row["id"]], **state)
        ctx = RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id, job_id=p.job_id,
                         usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, producer=store, search=store))
        result = graph.run(p, ctx)
    return result, jobs, list(seen.phases), sent


def designs(store: FakeStore) -> list[dict[str, Any]]:
    return [store.shot_rows[k]["design"] for k in sorted(store.shot_rows, key=lambda k: store.shot_rows[k]["number"])]


def warnings(jobs: FakeJobs) -> list[str]:
    return [json.dumps(e, default=str) for e in jobs.events if "warning" in str(e).lower()]


def test_recommend_settings_designs_the_scene_in_one_call_and_keeps_the_planners_ir():
    store = world()
    irs = {k: r["ir"]["setting"] for k, r in store.shot_rows.items()}
    result, jobs, phases, sent = run(store, replies=answer(), mode="design", force=True)
    assert phases.count(CAMERA) == 1 and DOP not in phases
    assert result["designed"] == len(store.shot_rows)
    assert sent[0].startswith("<clips>") and sent[0].count("<clip slate=") == len(store.shot_rows)
    for k, row in store.shot_rows.items():
        d = row["design"]
        assert d["camera"]["state"] == "designed" and d["camera"]["language"].startswith("Calm and close")
        assert d["camera"]["model"] == "m-camera" and d["pins"] and row["ir"]["setting"].startswith(irs[k][:20])
        rec = CameraSettings.model_validate(d["recommended"])
        assert rec.support == "Operated" and rec.height
    moves = [CameraSettings.model_validate(d["recommended"]).movement for d in designs(store)]
    assert moves[:3] == ["Slow creep", "Push in", "Pull out"]
    assert not warnings(jobs)


def test_a_clip_still_faulty_after_the_repair_keeps_the_rule_camera_the_rest_the_agents():
    store = world()
    gear = "The camera rides the dolly closer as she looks up."
    _, jobs, phases, _ = run(store, replies=[answer(gear), answer(gear)], mode="design", force=True)
    assert phases.count(CAMERA) == 2  # ONE repair
    first, *rest = designs(store)
    assert first["camera"]["state"] == "not designed" and "names gear" in first["camera"]["faults"][0]
    assert CameraSettings.model_validate(first["recommended"]).movement == "Hold"  # the rule camera (D10)
    assert all(d["camera"]["state"] == "designed" for d in rest)
    assert any("could not design S01" in w for w in warnings(jobs))


def test_a_repaired_answer_is_used():
    store = world()
    _, _, phases, sent = run(store, replies=[answer("The camera barely moves."), answer()], mode="design",
                             force=True)
    assert phases.count(CAMERA) == 2 and "Code checked your answer" in sent[1] and "<your_first_answer>" in sent[1]
    assert all(d["camera"]["state"] == "designed" for d in designs(store))


def test_ask_camera_redoes_one_shot_with_the_note_and_the_scene_as_context():
    store = world()
    run(store, replies=answer(), mode="design", force=True)
    first = sorted(store.shot_rows.values(), key=lambda r: r["number"])
    target, other = first[1], first[2]
    before_other = other["design"]
    _, _, phases, sent = run(store, replies=answer(), mode="camera_ask", shot_ids=[target["id"]],
                             note="Too still: a visible slow push toward her.")
    assert phases.count(CAMERA) == 1 and DOP not in phases
    assert "<scene_camera>" in sent[0] and "Too still: a visible slow push toward her." in sent[0]
    assert sent[0].count("<clip slate=") == len(first)  # the whole scene as context
    assert store.shot_rows[other["id"]]["design"] == before_other  # only the asked shot changes
    assert store.shot_rows[target["id"]]["design"]["camera"]["state"] == "designed"


def test_ask_camera_with_no_model_says_so_and_changes_nothing():
    store = world()
    before = {k: r.get("design") for k, r in store.shot_rows.items()}
    _, jobs, phases, _ = run(store, replies=answer(), on=False, mode="camera_ask",
                                  shot_ids=[next(iter(store.shot_rows))], note="push in")
    assert CAMERA not in phases and {k: r.get("design") for k, r in store.shot_rows.items()} == before
    assert any("needs a model" in w for w in warnings(jobs))


def test_shots_without_a_planners_ir_go_to_the_dop():
    store = world(ir=False)
    _, _, phases, _ = run(store, replies=answer(), mode="design", force=True)
    assert CAMERA not in phases and DOP in phases


def test_no_model_no_call():
    with patch.object(camera.llm, "models_enabled", lambda: False):
        got = camera.design(RunContext(), object(), object())
    assert got.designs == {} and got.warnings == [camera.NEEDS_MODEL]
