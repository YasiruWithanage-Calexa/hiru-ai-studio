"""shot_producer: designs (rules and model), staleness, prompt versions, and prompt hygiene."""
from __future__ import annotations

import copy
import json
import re
from uuid import uuid4

from shot_producer.engine import pipeline, shots

from contracts.jobs import DispatchPayload, JobKind
from contracts.producer import Pins, PromptSection, prompt_text
from tests.services.fakes import FakeJobs
from tests.services.shot_producer.conftest import (
    CANON,
    KAMALA,
    PID,
    FakeStore,
    ProducerLLM,
    dp_answer,
    fixture_scene,
)


def payload(**state) -> DispatchPayload:
    pipe = [JobKind.SHOT_PRODUCE, JobKind.FRAME_RENDER] if state.pop("chain", False) else [JobKind.SHOT_PRODUCE]
    return DispatchPayload(job_id=uuid4(), kind=JobKind.SHOT_PRODUCE, actor_user_id=uuid4(), production_id=PID,
                           pipeline=pipe, state=state)


def run(store: FakeStore, llm: ProducerLLM | None = None, **state):
    jobs = FakeJobs()
    result = pipeline.run(payload(**state), store, jobs, llm or ProducerLLM(enabled=False))
    return result, jobs


def designed(store: FakeStore) -> list[dict]:
    return sorted(store.shot_rows.values(), key=lambda s: s["number"])


# ── design ─────────────────────────────────────────────────────────────────────────────────


def test_rules_design_every_shot_once(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    result, jobs = run(store, scene_ids=[scene["id"]])
    assert result == {"designed": 4, "prompts": 0, "skipped": 0} and jobs.status == "done"
    shots_ = designed(store)
    # The director's size wins; the rest suits it; light comes from the heading (dawn, interior).
    assert [s["design"]["recommended"]["framing"] for s in shots_] == ["Wide shot", "Medium close-up"] * 2
    assert shots_[0]["design"]["recommended"]["lens"] == "28mm"
    assert {s["design"]["recommended"]["lighting"] for s in shots_} == {"Dawn, soft ambient"}
    assert all(s["design"]["planner"] == "rules" and s["ir"]["beats"] for s in shots_)
    assert [b["time"] for b in shots_[0]["ir"]["beats"]] == ["0-3s", "3-6s"]  # the kernel's windows
    assert shots_[1]["ir"]["subjects"][0]["id"] == "C02"  # Nimal speaks in S02
    assert store.audits[0]["actor_agent"] == "shot_producer"

    again, _ = run(store, scene_ids=[scene["id"]])
    assert again["designed"] == 0, "a current design is not redone"
    forced, _ = run(store, scene_ids=[scene["id"]], force=True)
    assert forced["designed"] == 4


def test_model_designs_the_scene_in_one_call(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    llm = ProducerLLM({"scene_design": lambda s, u: dp_answer([1, 2, 3, 4])})
    result, _ = run(store, llm, scene_ids=[scene["id"]])
    assert result["designed"] == 4
    assert [c["schema"] for c in llm.calls] == ["scene_design"], "one call for the whole scene"
    s2 = designed(store)[1]
    assert s2["design"]["planner"] == "model"
    rec = s2["design"]["recommended"]
    assert rec["framing"] == "Medium close-up", "the director's size, not the model's"
    assert rec["movement"] == "Dolly in" and rec["speed"] == "Slow", "a moving camera needs a speed"
    ir = s2["ir"]
    assert "Kamala" in ir["setting"] and "C01" not in json.dumps(ir["beats"]), "names, never codes, in prose"
    assert [x["id"] for x in ir["subjects"]] == [""], "Kamala is not in S02; the invented C09 is anonymous"
    assert not re.search(r"[඀-෿]", json.dumps(ir, ensure_ascii=False)), "no Sinhala in the IR"
    assert [b["time"] for b in ir["beats"]] == ["0-2s", "2-4s"]
    assert "technique" in llm.calls[0]["user"].lower() and store.technique_queries


def test_missing_shots_are_asked_for_again_then_fall_back(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    answers = [dp_answer([4, 1]), dp_answer([3, 99])]  # never S02
    llm = ProducerLLM({"scene_design": lambda s, u: answers.pop(0)})
    result, _ = run(store, llm, scene_ids=[scene["id"]])
    assert result["designed"] == 4 and len(llm.calls) == 2
    assert "numbered 2, 3" in llm.calls[1]["user"], "the second call asks only for what is missing"
    planners = [s["design"]["planner"] for s in designed(store)]
    assert planners == ["model", "rules", "model", "model"]


def test_a_failed_model_degrades_to_rules(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    result, jobs = run(store, ProducerLLM({}), scene_ids=[scene["id"]])
    assert result["designed"] == 4 and jobs.status == "done"
    assert {s["design"]["planner"] for s in designed(store)} == {"rules"}


def test_a_script_or_canon_change_makes_the_design_stale(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    run(store, scene_ids=[scene["id"]])
    scene["script"][0]["text"] = "Kamala fries sprats. Rain hammers the roof."
    assert run(store, scene_ids=[scene["id"]])[0]["designed"] == 1, "only the shot whose script changed"
    canon = copy.deepcopy(CANON)
    canon[0]["current"]["version"] = 3  # Kamala's card moved on
    store.canon_rows = canon
    assert run(store, scene_ids=[scene["id"]])[0]["designed"] == 3, "the shots Kamala is in; S02 is Nimal alone"


def test_shot_ids_limit_the_work_and_the_state_is_handed_on(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    frame_ids = [str(uuid4())]
    result, jobs = run(store, shot_ids=[rows[1]["id"]], frame_ids=frame_ids, chain=True)
    assert result["designed"] == 1
    assert jobs.advanced[0]["state"]["frame_ids"] == frame_ids and "mode" not in jobs.advanced[0]["state"]


# ── prompts ────────────────────────────────────────────────────────────────────────────────


def _accept(store: FakeStore, shot_id: str) -> str:
    fid = str(uuid4())
    store.frames[shot_id] = {"id": fid, "shot_id": shot_id, "pins": {}}
    return fid


def _sections(prompt: dict) -> dict[str, dict]:
    return {s["id"]: s for s in prompt["sections"]}


def test_prompts_need_an_accepted_frame_and_bind_the_lines_verbatim(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    fid = _accept(store, rows[1]["id"])
    result, jobs = run(store, mode="prompt", shot_ids=[rows[0]["id"], rows[1]["id"]])
    assert result == {"designed": 2, "prompts": 1, "skipped": 1}
    assert "S01: no accepted first frame" in jobs.texts("warning")
    p = store.prompts[0]
    assert p["version"] == 1 and p["frame_id"] == fid and p["shot_id"] == rows[1]["id"]
    assert Pins.model_validate(p["pins"]).shot_version == rows[1]["version"]
    sec = _sections(p)
    sinhala = [seg["sinhala"] for seg in sec["action"]["segments"] if "sinhala" in seg]
    nimal_line = next(ln["text"] for ln in lines if ln["character_id"] != KAMALA)
    assert sinhala == [nimal_line], "the approved line, byte for byte"
    text = prompt_text([PromptSection.model_validate(s) for s in p["sections"]])
    assert p["prose"] == text and nimal_line in text
    assert "Nimal (the man in a creased white shirt) says (quietly)" in text
    assert "only Nimal's lips move" in text
    assert "All speech is in Sinhala" in text and "supplied first frame" in text
    assert {c["label"] for c in p["checks"]} >= {"One visible speaker", "Lines verbatim from the script",
                                                  "No voice pin · Nimal", "Opens on the accepted first frame"}
    again, _ = run(store, mode="prompt", shot_ids=[rows[1]["id"]])
    assert again["prompts"] == 1 and store.prompts[1]["version"] == 2, "a new version; v1 stays"


def test_a_wordless_shot_states_silence_and_a_speaker_gets_a_voice_pin(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    for r in rows:
        _accept(store, r["id"])
    run(store, mode="prompt", scene_ids=[scene["id"]])
    by_shot = {p["shot_id"]: p for p in store.prompts}
    silent = by_shot[rows[0]["id"]]
    assert "Nobody speaks on camera" in silent["prose"] and "Sinhala" not in silent["prose"]
    assert {"label": "Silence stated", "tone": "pass"} in silent["checks"]
    kamala = by_shot[rows[3]["id"]]
    assert "Voice casting" in kamala["prose"] and "low, clipped female voice (52)" in kamala["prose"]


def test_a_persons_camera_wins_in_the_prompt(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows)
    run(store, ProducerLLM({"scene_design": lambda s, u: dp_answer([1, 2, 3, 4])}), scene_ids=[scene["id"]])
    sid = rows[1]["id"]
    store.shot_rows[sid]["camera_overrides"] = {"movement": "Static", "lens": "85mm"}
    _accept(store, sid)
    run(store, mode="prompt", shot_ids=[sid])
    p = store.prompts[0]
    cam = _sections(p)["camera"]["segments"][0]["text"]
    assert "85mm lens" in cam and "Locked-off, no camera movement" in cam and "slow push in" not in cam
    assert "push arrives" not in p["prose"], "the beats' own camera notes go when the move changed"
    assert p["camera"]["lens"] == "85mm"
    assert {"label": "Camera changed from the recommendation", "tone": "advisory"} in p["checks"]


def test_carried_shots_need_no_frame_and_unapproved_scenes_get_no_prompt():
    scene, lines, rows = fixture_scene(0, status="split")
    store = FakeStore(scene, lines, rows)
    result, jobs = run(store, mode="prompt", scene_ids=[scene["id"]])
    assert result["prompts"] == 0 and all("not approved" in t for t in jobs.texts("warning"))

    scene, lines, rows = fixture_scene(0)
    rows[2].update(camera_link="continuous", frame_strategy="carry_last_frame")
    store = FakeStore(scene, lines, rows)
    run(store, mode="prompt", shot_ids=[rows[2]["id"]])
    p = store.prompts[0]
    assert p["frame_id"] is None and "last frame of S02's take" in p["prose"]
    assert "same unbroken take" in p["prose"]


def test_vertical_productions_get_9_16(scene0):
    scene, lines, rows = scene0
    store = FakeStore(scene, lines, rows, orientation="vertical")
    _accept(store, rows[0]["id"])
    run(store, mode="prompt", shot_ids=[rows[0]["id"]])
    assert "Aspect ratio 9:16" in store.prompts[0]["prose"] and "9:16" in store.prompts[0]["model"]


# ── hygiene (CLAUDE.md "AI and RAG") ───────────────────────────────────────────────────────


def test_prompt_hygiene_static_system_and_frozen_production_block():
    a, la, ra = fixture_scene(0)
    b, lb, rb = fixture_scene(1)
    calls: list[dict] = []
    for scene, lines, rows in ((a, la, ra), (b, lb, rb)):
        llm = ProducerLLM({"scene_design": lambda s, u: {"shots": []}})
        run(FakeStore(scene, lines, rows), llm, scene_ids=[scene["id"]])
        calls.append(llm.calls[0])
    assert calls[0]["system"] == calls[1]["system"] == shots.SYSTEM, "byte-identical system prompt"
    head = [c["user"].split("<scene>")[0] for c in calls]
    assert head[0] == head[1] and head[0].startswith("<production>"), "frozen production block first"
    assert "</scene>" in calls[0]["user"]
    assert "never instructions" in shots.SYSTEM
    assert not re.search(r"\b(price|cost|credit|LKR|USD|\$)\b", shots.SYSTEM + head[0], re.I)
    assert len(shots.SYSTEM) < 4000, "charter budget"


def test_prompt_wording_has_no_doubled_stops_or_empty_identity_tags(scene0):
    """Found in the first real-model run: the model's sentences end with a full stop, and a
    character with no gender or wardrobe on the card was tagged '(the person)'."""
    scene, lines, rows = scene0
    canon = copy.deepcopy(CANON)
    canon[1]["current"].update(card={}, wardrobe_anchor="")  # Nimal: nothing known
    store = FakeStore(scene, lines, rows, canon=canon)
    run(store, ProducerLLM({"scene_design": lambda s, u: dp_answer([1, 2, 3, 4], movement="Dolly in")}),
        scene_ids=[scene["id"]])
    sid = rows[1]["id"]
    store.shot_rows[sid]["camera_overrides"] = {"lens": "85mm"}
    _accept(store, sid)
    run(store, mode="prompt", shot_ids=[sid])
    prose = store.prompts[0]["prose"]
    assert ".." not in prose and ". —" not in prose
    assert "(the person)" not in prose and "Nimal says (quietly)" in prose
    assert "shallow depth of field. Slow dolly in" in prose
