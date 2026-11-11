"""The prompt writer plugged into shot_producer (plan/2026-11-11c), with a scripted model: the first frame's descriptive
sections are reworded and stored on the shot, a video prompt's descriptive sections are reworded while its action and
dialogue stay as code wrote them, a rewrite that loses a fact is not used, and nothing is called when the writer is off.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import replace
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.messages import BaseMessage

from contracts.prompt_polish import POLISHABLE
from hiru_ai.core import llm as door
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.systems.shot_producer import graph
from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter
from tests.services.fakes import FakeJobs
from tests.services.shot_producer.conftest import FakeStore, dp_answer, fixture_scene
from tests.services.shot_producer.test_shot_producer import payload

WRITER = "prompt_writer.polish"


def writer_reply(drop: str = "") -> Any:
    """Answers every section sent with "Vividly, " + its own words; section `drop` comes back without its anchors."""
    def reply(messages: list[BaseMessage]) -> dict[str, Any]:
        text = str(messages[-1].content)
        rows = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        return {"sections": [{"key": r["key"], "text": "A plain sentence." if r["key"] == drop and r["keep"]
                              else f"Vividly, {r['text']}"} for r in rows]}
    return reply


class Vectors(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 4


def run(store: FakeStore, rows: list[dict[str, Any]], *, on: bool = True, drop: str = "", **state: Any
        ) -> tuple[dict[str, Any], FakeJobs, list[str]]:
    jobs = FakeJobs()
    with ExitStack() as stack:
        stack.enter_context(environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_HIGH="m-high",
                                        OPENAI__MODEL_MEDIUM="m-medium",
                                        PROMPT_WRITER__ENABLED="true" if on else "false"))
        seen = stack.enter_context(scripted_models(
            {"shot_producer.scene": Endless([lambda messages: dp_answer([1, 2, 3, 4])]),
             WRITER: Endless([writer_reply(drop)])}, {"high": "m-high", "medium": "m-medium"}))
        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))
        scene_id = store.scene_row["id"]
        p = payload(scene_ids=[scene_id], **state)
        ctx = RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id, job_id=p.job_id,
                         usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, producer=store, search=store))
        result = graph.run(p, ctx)
    return result, jobs, list(seen.phases)


def world() -> tuple[FakeStore, list[dict[str, Any]]]:
    scene, lines, rows = fixture_scene(0)
    return FakeStore(scene, lines, rows), rows


def events(jobs: FakeJobs) -> list[str]:
    return [str(e) for e in jobs.events]


def test_the_first_frame_is_reworded_section_by_section_and_stored_on_the_shot():
    store, rows = world()
    result, jobs, phases = run(store, rows, mode="frame_prompt", drop="people")
    assert result["frame_prompts"] == len(rows) and WRITER in phases
    polish = store.shot_rows[rows[0]["id"]]["design"]["frame_polish"]
    assert polish and set(polish) <= set(POLISHABLE["first_frame"])
    assert all(v["text"].startswith("Vividly, ") and len(v["stamp"]) == 12 for v in polish.values())
    assert "people" not in polish, "a rewrite that lost a name is not used"
    assert any("People kept as written: the rewrite dropped" in e for e in events(jobs))
    assert not store.prompts, "the first frame's mode writes no video prompt"


def test_a_video_prompt_is_reworded_but_its_action_and_dialogue_are_not():
    store, rows = world()
    store.frames[rows[0]["id"]] = {"id": "f1", "shot_id": rows[0]["id"], "pins": {}}
    result, _, phases = run(store, rows, mode="prompt", shot_ids=[rows[0]["id"]])
    assert result["prompts"] == 1 and WRITER in phases
    sections = {s["id"]: s for s in store.prompts[0]["sections"]}
    texts = {k: "".join(str(seg.get("text") or "") for seg in s["segments"]) for k, s in sections.items()}
    assert texts["camera"].startswith("Vividly, ")
    assert not any(texts[k].startswith("Vividly") for k in texts if k not in POLISHABLE["video"])
    assert "Vividly, " in store.prompts[0]["prose"]
    assert any(c["label"].startswith("Wording polished by the prompt writer") for c in store.prompts[0]["checks"])


def test_with_the_writer_off_nothing_is_called_and_the_code_prompt_stands():
    store, rows = world()
    store.frames[rows[0]["id"]] = {"id": "f1", "shot_id": rows[0]["id"], "pins": {}}
    _, _, phases = run(store, rows, on=False, mode="prompt", shot_ids=[rows[0]["id"]])
    assert WRITER not in phases and "Vividly" not in store.prompts[0]["prose"]
    result, jobs, phases = run(store, rows, on=False, mode="frame_prompt")
    assert WRITER not in phases and "frame_prompts" not in result
    assert any("The prompt writer is off" in e for e in events(jobs))
    assert all("frame_polish" not in (r.get("design") or {}) for r in store.shot_rows.values())
