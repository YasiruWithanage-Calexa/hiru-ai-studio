"""The Shot prompt agent in the shot_prompts system (plan/2026-11-20d D4; its own system since 2026-11-21), with a
scripted model. The fixture shots carry a planner's IR and are designed first by the shot producer (the rule camera).

* "Generate video prompt" (mode "video"): a shot with no shot prompt gets ONE full call and the prompt is stored on the
  shot; asked again while it is current, NO call; after a move-only change, ONE video-only call that keeps the opening
  and the frame; after an angle change, a full call.
* "Write prompts" (mode "write"): one call a shot, stored; never a design: a stale design says "Recommend settings
  first".
* Before a frame is drawn (mode "frames", `state.shot_prompts`): a shot with no current shot prompt gets one; a current
  one is kept.
* A failed answer is repaired ONCE; failing twice stores nothing and says why. No packet or no model: no call.
"""
from __future__ import annotations

import re
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_core.messages import BaseMessage

from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core import llm as door
from hiru_ai.core import shot_prompts
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.systems.shot_producer import graph as producer_graph
from hiru_ai.systems.shot_prompts import graph
from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter
from tests.services.fakes import FakeJobs
from tests.services.shot_producer.conftest import PID, FakeStore, dp_answer, fixture_scene

AGENT = "shot_prompter.write"
SPOKEN = re.compile(r"^- (L[\d.]+): ", re.M)
NAMES = ("Kamala", "Nimal")
# a composition that says every angle and size in physical words (the checks hold the design's)
COMPOSITION = ("The camera is at eye height, neither low nor high, not looking up at them nor down on them, not "
               "tilted, not overhead, above the ground; a medium, waist-up two-shot of both, wide and full, knee to "
               "chest, close on the detail, over the shoulder.")


class Vectors(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 4


@dataclass
class FakeBreakdown:
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)

    def packet(self, scene_id: str) -> dict[str, Any] | None:
        return self.rows.get(scene_id)


def packet_for(scene: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """The scene as its breakdown packet: block i is script block i, the n-th spoken block the line of `ord` n."""
    by_id = {str(ln["id"]): ln for ln in lines}
    codes = {"Kamala": "C01", "Nimal": "C02"}
    blocks = []
    for i, b in enumerate(scene["script"]):
        ln = by_id.get(str(b.get("line_id"))) if b["kind"] == "dialogue" else None
        if ln is not None:
            other = "C02" if codes.get(ln["speaker"]) == "C01" else "C01"
            blocks.append({"id": f"B{i}", "kind": "dialogue", "text": ln["text"],
                           "speaker": codes.get(ln["speaker"], "C09"), "addressee": other, "presence": "on_screen",
                           "delivery_hint": "quietly", "intent": "to be understood"})
        else:
            blocks.append({"id": f"B{i}", "kind": b["kind"], "text": b.get("text", ""), "speaker": ""})
    return {"A_scene": {"title": "The return", "summary": "Nimal comes home.", "purpose": "a reunion"},
            "B_people": [{"id": "C01", "name": "Kamala", "presence": "on_screen", "wants": "to forgive",
                          "feeling_start": "guarded", "feeling_end": "softer"},
                         {"id": "C02", "name": "Nimal", "presence": "on_screen", "wants": "to be let in",
                          "feeling_start": "ashamed", "feeling_end": "hopeful"}],
            "C_place": {"name": "Kamala's house"}, "F_feeling": {"mood": ["tender"]}, "G_direction": [],
            "E_blocks": blocks}


def timed(flow: list[dict[str, Any]], shot: str) -> None:
    """lab/timecodes: each step's range, as the agent gives it: the first step a lead-in, each line its speech time
    (half seconds), the take filled to its length."""
    take = float(re.search(r"take (\d+(?:\.\d+)?) s", shot).group(1))  # type: ignore[union-attr]
    secs = [float(m) for m in re.findall(r"about (\d+(?:\.\d+)?) s of speech", shot)]
    need = [1.0] + [max(1.0, -(-(s - 0.5) * 2 // 1) / 2) for s in secs]
    need[0] += max(0.0, take - sum(need))
    t = 0.0
    for step, n in zip(flow, need, strict=True):
        step["start_s"], step["end_s"] = t, t + n
        t += n


def answer(bad: str = "", seen: list[str] | None = None) -> Any:
    """An answer for whatever shot it is sent: the people in frame in the opening, the frame and the video; each spoken
    line once, in order. `bad`: a frame composition with a fault in it. `seen` collects each message."""
    def reply(messages: list[BaseMessage]) -> dict[str, Any]:
        text = str(messages[-1].content)
        if seen is not None:
            seen.append(text)
        shot = text.split("<camera>")[0]
        lids = SPOKEN.findall(shot)
        people = [n for n in NAMES if re.search(rf"^In frame: [^\n]*\b{n}\b", shot, re.M)]
        opening = {"people": [{"name": n, "side": "centre", "facing": "the other", "posture": "standing",
                               "hands": "empty", "expression": "guarded"} for n in people],
                   "background": "The small kitchen.", "light": "Dawn through the window."}
        frame = {"composition": bad or COMPOSITION, "people": " ".join(f"{n} stands, guarded." for n in people),
                 "background": "The small kitchen.", "light": "Dawn through the window."}
        flow = [{"kind": "action", "text": "A kettle ticks on the stove.", "line_id": "", "to": "", "how": "",
                 "listener": ""}]
        flow += [{"kind": "line", "text": "", "line_id": lid, "to": "Nimal", "how": "softly, testing him",
                  "listener": "He lowers his eyes."} for lid in lids]
        timed(flow, shot)
        video = {"situation": "Dawn in the small house; Nimal has just come back.",
                 "people": " ".join(f"{n} by the stove." for n in people), "flow": flow,
                 "sound": "A kettle, crows; no music."}
        return {"opening": opening, "frame": frame, "video": video}
    return reply


def payload(kind: JobKind = JobKind.SHOT_PROMPTS, **state: Any) -> DispatchPayload:
    pipe = [kind, JobKind.FRAME_RENDER] if state.pop("chain", False) else [kind]
    return DispatchPayload(job_id=uuid4(), kind=kind, actor_user_id=uuid4(), production_id=PID, pipeline=pipe,
                           state=state)


def design(store: FakeStore) -> dict[str, Any]:
    """"Recommend settings" with no model: the shot producer keeps each planner's IR and gives the rule camera."""
    p = payload(JobKind.SHOT_PRODUCE, scene_ids=[store.scene_row["id"]])
    with patch.object(door, "models_enabled", lambda: False):
        return producer_graph.run(p, RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id,
                                                job_id=p.job_id, ports=replace(Ports(), jobs=FakeJobs(), scenes=store,
                                                                               producer=store, search=store)))


def run(store: FakeStore, *, replies: Any, models: bool = True, packet: bool = True, mode: str = "video",
        **state: Any) -> tuple[dict[str, Any], FakeJobs, list[str]]:
    jobs = FakeJobs()
    breakdown = FakeBreakdown()
    if packet:
        breakdown.rows[store.scene_row["id"]] = {"packet": packet_for(store.scene_row, list(store.line_rows)),
                                                  "script_version": 1, "waits": []}
    with ExitStack() as stack:
        stack.enter_context(environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m-high",
                                        OPENAI__MODEL_MEDIUM="m-medium", OPENAI__MODEL_SHOT_PROMPTER="m-shot"))
        seen = stack.enter_context(scripted_models(
            {AGENT: replies}, {"high": "m-high", "medium": "m-medium", "shot_prompter": "m-shot"}))
        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))
        if not models:  # no key
            stack.enter_context(patch.object(shot_prompts.llm, "models_enabled", lambda: False))
        p = payload(scene_ids=[store.scene_row["id"]], mode=mode, **state)
        ctx = RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id, job_id=p.job_id,
                         usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, producer=store, search=store,
                                       breakdown=breakdown))
        result = graph.run(p, ctx)
    return result, jobs, list(seen.phases)


def world() -> tuple[FakeStore, list[dict[str, Any]]]:
    """The fixture scene planned (a planner's IR on every shot, as Raphael leaves it) and designed, each shot with an
    accepted first frame."""
    scene, lines, rows = fixture_scene(0)
    for r in rows:
        r["ir"] = dp_answer([int(r["number"])])["shots"][0] | {"beats": []}
        r["ir"].pop("number", None)
    store = FakeStore(scene, lines, rows)
    design(store)
    for r in rows:
        store.frames[r["id"]] = {"id": f"f-{r['id']}", "shot_id": r["id"], "pins": {}}
    return store, list(store.shot_rows.values())


def stored(store: FakeStore, shot_id: str) -> dict[str, Any] | None:
    return (store.shot_rows[shot_id].get("design") or {}).get("shot_prompt")


def test_generate_video_prompt_writes_and_stores_the_shot_prompt_then_assembles_the_video():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]))
    assert result["prompts"] == len(rows) and "warnings" not in result
    assert phases.count(AGENT) == len(rows)
    for r in rows:
        rec = stored(store, r["id"])
        assert rec and rec["frame"]["composition"] == COMPOSITION and rec["mode"] == "both"
        assert rec["pins"]["picture"]["angle"] and rec["pins"]["motion"]["sentence"]
    spoken = next(p for p in store.prompts if any("sinhala" in seg for s in p["sections"] for seg in s["segments"]))
    assert [s["id"] for s in spoken["sections"]] == ["opening", "situation", "people", "action", "camera", "sound",
                                                     "rules", "format"]
    assert {"label": "Lines verbatim from the script", "tone": "pass"} in spoken["checks"]
    assert spoken["pins"]["picture"] and spoken["pins"]["motion"], "D8: the video prompt pins the camera too"


def test_a_current_shot_prompt_is_used_with_no_call():
    store, rows = world()
    run(store, replies=Endless([answer()]))
    before = len(store.prompts)
    result, _, phases = run(store, replies=Endless([answer()]))
    assert AGENT not in phases and result["prompts"] == len(rows) and len(store.prompts) == 2 * before


def test_a_current_shot_prompt_needs_no_model_for_the_video():
    store, rows = world()
    run(store, replies=Endless([answer()]))
    result, _, phases = run(store, replies=Endless([answer()]), models=False)
    assert AGENT not in phases and result["prompts"] == len(rows)


def test_a_move_only_change_rewrites_the_video_only_and_keeps_the_frame():
    store, rows = world()
    run(store, replies=Endless([answer()]))
    first = stored(store, rows[0]["id"])
    store.shot_rows[rows[0]["id"]]["camera_overrides"] = {"movement": "Pull out", "speed": "Slow"}
    seen: list[str] = []
    other = answer(bad="A different frame, the camera is low.", seen=seen)
    result, _, phases = run(store, replies=Endless([other]), shot_ids=[rows[0]["id"]])
    assert phases.count(AGENT) == 1 and result["prompts"] == 1
    assert "VIDEO ONLY" in seen[0] and "<fixed>" in seen[0]
    now = stored(store, rows[0]["id"])
    assert now["mode"] == "video_only" and now["frame"] == first["frame"] and now["opening"] == first["opening"]


def test_an_angle_change_rewrites_both():
    store, rows = world()
    run(store, replies=Endless([answer()]))
    store.shot_rows[rows[0]["id"]]["camera_overrides"] = {"angle": "Low angle"}
    seen: list[str] = []
    _, _, phases = run(store, replies=Endless([answer(seen=seen)]), shot_ids=[rows[0]["id"]])
    assert phases.count(AGENT) == 1 and "VIDEO ONLY" not in seen[0] and "Angle low angle" in seen[0]
    assert stored(store, rows[0]["id"])["mode"] == "both"


def test_write_prompts_rewrites_each_shot_prompt_then_assembles_its_video_with_no_second_call():
    """The shot header's one button (2026-11-21): the agent writes the prompts (one call a shot), then each shot with
    an accepted first frame gets its video prompt assembled from them by code, with no further call."""
    store, rows = world()
    run(store, replies=Endless([answer()]))
    before = {r["id"]: stored(store, r["id"])["written_at"] for r in rows}
    versions = len(store.prompts)
    result, _, phases = run(store, replies=Endless([answer()]), mode="write")
    assert phases.count(AGENT) == len(rows) and result["shot_prompts"] == len(rows)
    assert len(store.prompts) == versions + len(rows) and result["prompts"] == len(rows)
    assert all("[0-" in p["prose"] for p in store.prompts[versions:])
    assert all(stored(store, r["id"])["written_at"] >= before[r["id"]] for r in rows)


def test_a_shot_prompt_written_before_timecodes_gets_its_video_rewritten_and_keeps_its_opening():
    """A stored shot prompt with no ranges: "Write prompts" rewrites the video only; the opening and the frame words
    (and so the drawn frame) stay."""
    store, rows = world()
    run(store, replies=Endless([answer()]))
    for r in rows:
        rec = stored(store, r["id"])
        for step in rec["video"]["flow"]:
            step.pop("start_s", None)
            step.pop("end_s", None)
    kept = {r["id"]: stored(store, r["id"])["opening"] for r in rows}
    run(store, replies=Endless([answer()]), mode="write")
    for r in rows:
        rec = stored(store, r["id"])
        assert rec["mode"] == "video_only" and rec["opening"] == kept[r["id"]]
        assert all(s.get("start_s") is not None for s in rec["video"]["flow"])


def test_before_a_frame_only_a_shot_without_a_current_shot_prompt_is_written():
    store, rows = world()
    ids = [r["id"] for r in rows]
    result, _, phases = run(store, replies=Endless([answer()]), mode="frames", shot_prompts=ids, frame_ids=["f1"])
    assert phases.count(AGENT) == len(rows) and result["shot_prompts"] == len(rows)
    assert all(stored(store, i) for i in ids)
    result, _, phases = run(store, replies=Endless([answer()]), mode="frames", shot_prompts=ids, frame_ids=["f1"])
    assert AGENT not in phases and "shot_prompts" not in result


def test_the_frames_hop_gets_the_frame_ids_but_not_the_shot_prompt_list():
    store, rows = world()
    _, jobs, _ = run(store, replies=Endless([answer()]), mode="frames", shot_prompts=[rows[0]["id"]],
                     frame_ids=["f1"], chain=True)
    assert jobs.advanced and jobs.advanced[-1]["state"]["frame_ids"] == ["f1"]
    assert "shot_prompts" not in jobs.advanced[-1]["state"]


def test_a_failed_answer_is_repaired_once_and_used():
    store, rows = world()
    result, _, phases = run(store, replies=[answer(bad="A wide frame. She begins to turn."), answer()],
                            shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 1 and phases.count(AGENT) == 2
    assert stored(store, rows[0]["id"])["repaired"] is True
    assert {"label": "Repaired once", "tone": "advisory"} in store.prompts[0]["checks"]


def test_an_answer_that_fails_twice_stores_nothing_and_says_why():
    store, rows = world()
    bad = answer(bad="A wide frame. She begins to turn.")
    result, _, phases = run(store, replies=[bad, bad], shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and not store.prompts and phases.count(AGENT) == 2
    assert stored(store, rows[0]["id"]) is None
    assert any("shot prompt not written: frame: a still has no motion" in w for w in result["warnings"])


def test_no_packet_no_call_and_the_reason():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]), packet=False, shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and AGENT not in phases
    assert "no breakdown" in result["warnings"][0]


def test_no_model_no_call():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]), models=False, shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and AGENT not in phases and not store.prompts
    assert "needs a model" in result["warnings"][0]


def test_write_prompts_never_designs_a_stale_shot_it_says_recommend_settings_first():
    """2026-11-21: "Write prompts" only writes prompts. A shot whose design is out of date gets no call, no record."""
    store, rows = world()
    store.shot_rows[rows[0]["id"]]["design"] = {**store.shot_rows[rows[0]["id"]]["design"], "pins": {}}
    before = dict(store.shot_rows[rows[0]["id"]]["design"])
    result, _, phases = run(store, replies=Endless([answer()]), mode="write", shot_ids=[rows[0]["id"]])
    assert AGENT not in phases and "shot_prompts" not in result
    assert any("Recommend settings first" in w for w in result["warnings"])
    assert store.shot_rows[rows[0]["id"]]["design"] == before, "no design was run"


def test_a_shot_without_a_plan_gets_no_prompt():
    store, rows = world()
    store.shot_rows[rows[0]["id"]]["ir"] = {}
    result, _, phases = run(store, replies=Endless([answer()]), mode="write", shot_ids=[rows[0]["id"]])
    assert AGENT not in phases and any("Recommend settings first" in w for w in result["warnings"])


def test_after_the_design_hop_the_mode_is_frames():
    """"Draw first frame": the shot producer's hop hands on no mode; the shot_prompts list makes it the frames mode."""
    store, rows = world()
    ids = [r["id"] for r in rows]
    result, _, _ = run(store, replies=Endless([answer()]), mode="", shot_prompts=ids, frame_ids=["f1"])
    assert result["shot_prompts"] == len(rows) and result["prompts"] == 0
