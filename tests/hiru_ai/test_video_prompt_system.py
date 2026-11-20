"""The video prompt agent in shot_producer, mode "prompt" (plan/2026-11-20b §5), with a scripted model: one call a shot
with the scene part first, a failed answer repaired ONCE, no new version (and a warning in the result) when it still
fails, when the scene's packet is missing or out of date, or when there is no model. The prompt writer is never
asked."""
from __future__ import annotations

import re
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import BaseMessage

from hiru_ai.core.context import Ports, RunContext
from hiru_ai.systems.shot_producer import graph
from tests.hiru_ai.test_prompt_writer_system import Vectors
from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter
from tests.services.fakes import FakeJobs
from tests.services.shot_producer.conftest import FakeStore, dp_answer, fixture_scene
from tests.services.shot_producer.test_shot_producer import payload

VIDEO = "video_prompter.write"
WRITER = "prompt_writer.polish"
SPOKEN = re.compile(r"^- (L[\d.]+): ", re.M)


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
            blocks.append({"id": f"B{i}", "kind": "dialogue", "text": ln["text"], "speaker": codes.get(ln["speaker"],
                                                                                                     "C09"),
                           "addressee": other, "presence": "on_screen", "delivery_hint": "quietly",
                           "intent": "to be understood"})
        else:
            blocks.append({"id": f"B{i}", "kind": b["kind"], "text": b.get("text", ""), "speaker": ""})
    return {"A_scene": {"title": "The return", "summary": "Nimal comes home.", "purpose": "a reunion"},
            "B_people": [{"id": "C01", "name": "Kamala", "presence": "on_screen", "wants": "to forgive",
                          "feeling_start": "guarded", "feeling_end": "softer"},
                         {"id": "C02", "name": "Nimal", "presence": "on_screen", "wants": "to be let in",
                          "feeling_start": "ashamed", "feeling_end": "hopeful"}],
            "C_place": {"name": "Kamala's house"}, "F_feeling": {"mood": ["tender"]}, "G_direction": [],
            "E_blocks": blocks}


def answer(bad: str = "") -> Any:
    """A director's answer for whatever clip it is sent: each spoken line once, in order. `bad` is a situation with a
    fault in it (Sinhala letters: a line's words are code's to write)."""
    def reply(messages: list[BaseMessage]) -> dict[str, Any]:
        lids = SPOKEN.findall(str(messages[-1].content).split("<cards>")[0])
        flow = [{"kind": "action", "text": "Kamala sets down the cup.", "line_id": "", "to": "", "how": "",
                 "listener": ""}]
        flow += [{"kind": "line", "text": "", "line_id": lid, "to": "Nimal", "how": "softly, testing him",
                  "listener": "He lowers his eyes."} for lid in lids]
        return {"situation": bad or "Dawn in the small house; Nimal has just come back.",
                "people": "Kamala by the stove.", "flow": flow, "camera": "A steady frame on a tripod.",
                "sound": "A kettle, crows; no music."}
    return reply


def run(store: FakeStore, *, replies: list[Any], models: bool = True, packet: bool = True,
        **state: Any) -> tuple[dict[str, Any], FakeJobs, list[str]]:
    jobs = FakeJobs()
    breakdown = FakeBreakdown()
    if packet:
        breakdown.rows[store.scene_row["id"]] = {"packet": packet_for(store.scene_row, list(store.line_rows)),
                                                  "script_version": 1, "waits": []}
    with ExitStack() as stack:
        stack.enter_context(environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m-high",
                                        OPENAI__MODEL_MEDIUM="m-medium", OPENAI__MODEL_VIDEO_PROMPTER="m-video",
                                        PROMPT_WRITER__ENABLED="true"))
        seen = stack.enter_context(scripted_models(
            {"shot_producer.scene": Endless([lambda messages: dp_answer([1, 2, 3, 4])]), VIDEO: replies},
            {"high": "m-high", "medium": "m-medium", "video_prompter": "m-video"}))
        from hiru_ai.core import llm as door

        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))
        if not models:  # no key: the job knows before it designs anything
            stack.enter_context(patch.object(graph.llm, "models_enabled", lambda: False))
        p = payload(scene_ids=[store.scene_row["id"]], mode="prompt", **state)
        ctx = RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id, job_id=p.job_id,
                         usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, producer=store, search=store,
                                       breakdown=breakdown))
        result = graph.run(p, ctx)
    return result, jobs, list(seen.phases)


def world() -> tuple[FakeStore, list[dict[str, Any]]]:
    scene, lines, rows = fixture_scene(0)
    store = FakeStore(scene, lines, rows)
    for r in rows:
        store.frames[r["id"]] = {"id": f"f-{r['id']}", "shot_id": r["id"], "pins": {}}
    return store, rows


def warnings(jobs: FakeJobs) -> list[str]:
    return [str(e) for e in jobs.events if "warning" in str(e).lower()]


def test_every_shot_gets_the_agents_prompt_with_the_scripts_own_words_and_no_writer_is_asked():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]))
    assert result["prompts"] == len(rows) and "warnings" not in result
    assert phases.count(VIDEO) == len(rows) and WRITER not in phases
    spoken = next(p for p in store.prompts if any("sinhala" in seg for s in p["sections"] for seg in s["segments"]))
    assert [s["id"] for s in spoken["sections"]] == ["opening", "situation", "people", "action", "camera", "sound",
                                                     "rules", "format"]
    assert {"label": "Lines verbatim from the script", "tone": "pass"} in spoken["checks"]
    assert spoken["version"] == 1 and spoken["frame_id"].startswith("f-")


def test_a_failed_answer_is_repaired_once_and_used():
    store, rows = world()
    result, _, phases = run(store, replies=[answer("She says ඔව්."), answer()], shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 1 and phases.count(VIDEO) == 2
    assert {"label": "Repaired once", "tone": "advisory"} in store.prompts[0]["checks"]


def test_an_answer_that_fails_twice_writes_no_prompt_and_says_why():
    store, rows = world()
    bad = answer("She says ඔව්.")
    result, jobs, phases = run(store, replies=[bad, bad], shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and not store.prompts and phases.count(VIDEO) == 2
    assert any("video prompt not written: situation: Sinhala letters" in w for w in result["warnings"])
    assert any("video prompt not written" in w for w in warnings(jobs))


def test_no_packet_no_prompt_and_the_reason():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]), packet=False, shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and VIDEO not in phases
    assert "no breakdown" in result["warnings"][0]


def test_no_model_no_prompt():
    store, rows = world()
    result, _, phases = run(store, replies=Endless([answer()]), models=False, shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 0 and VIDEO not in phases and not store.prompts
    assert "needs a model" in result["warnings"][0]
