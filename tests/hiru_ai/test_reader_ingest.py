"""The document reader in the graph engine (plan/2026-11-06f §4.5): the doc_ingest system reads a script with the
reader agents when `READER__ENABLED`; the structure build and the canon extraction then use the stored reading, in both
engines, the same way."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import BaseMessage

from contracts.doc_read import Reading, reading_candidates
from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core import doc_reader, llm
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeDocs, FakeFiles, FakeJobs
from hiru_ai.core.settings import AISettings, ReaderSettings
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.doc_ingest import graph
from tests.contracts.reader_fakes import canon_answer, piece_answer

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "corpus"
SCRIPT = "harbour-lights-ep01-script.fountain"
GOLD = json.loads((ROOT / "eval" / "reader" / "gold" / "ekama-sakshiya.json").read_text(encoding="utf-8"))


class ReaderModel(RoutedChatModel):
    """Answers the reader's agents from the message they send; every other call fails (each is absent-safe)."""

    def _route(self, messages: list[BaseMessage], metadata: dict[str, Any]) -> Any:
        system, user = str(messages[0].content), messages[-1].content
        text = user if isinstance(user, str) else next(b["text"] for b in user if b.get("type") == "text")
        if "You read the scripts of a Sri Lankan" in system:
            return piece_answer(text)
        if "you list the drama's CANON" in system:
            return canon_answer(text)
        raise RuntimeError("not the reader")


@pytest.fixture
def reader_on(monkeypatch: pytest.MonkeyPatch) -> None:
    on = AISettings(reader=ReaderSettings(enabled=True, workers=2))
    monkeypatch.setattr(doc_reader, "get_settings", lambda: on)


def ingest() -> tuple[FakeDocs, FakeFiles, FakeJobs, dict[str, Any]]:
    document_id, production_id = uuid4(), uuid4()
    docs = FakeDocs([{"id": str(document_id), "production_id": str(production_id), "filename": SCRIPT,
                      "mime_type": "text/plain", "storage_path": "p/f", "confirmed_role": "script"}])
    files = FakeFiles({("documents", "p/f"): (CORPUS / SCRIPT).read_bytes()})
    jobs = FakeJobs()
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.DOC_INGEST, actor_user_id=uuid4(),
                              state={"document_id": str(document_id)})
    model = ReaderModel()
    with llm.use_models(model):
        result = graph.run(payload, RunContext(ports=replace(Ports(), docs=docs, files=files, jobs=jobs)))
    return docs, files, jobs, result


def test_off_the_graph_reads_nothing_with_the_reader():
    docs, _, _, result = ingest()
    assert result["status"] == "ready" and "reading_path" not in docs.document_rows[0]


def test_on_a_script_is_read_and_kept_beside_its_text(reader_on: None):
    docs, files, _, result = ingest()
    row = docs.document_rows[0]
    assert result["status"] == "ready" and row["read_from"] == "text"
    reading = Reading.loads(files.objects[("documents", row["reading_path"])])
    assert reading is not None and reading.episodes[0].scenes


def test_the_two_engines_send_the_same_prompts():
    for ident in ("reader_canon", "reader_episode", "reader_repair"):
        agent = ROOT.parent / "src" / "libs" / "hiru_ai" / "agents" / "reader" / ident / "prompts" / "system.md"
        service = ROOT.parent / "src" / "services" / "doc_ingest" / "doc_ingest" / "engine" / "reader_prompts"
        assert agent.read_text(encoding="utf-8") == (service / f"{ident}.md").read_text(encoding="utf-8"), ident


# ── the readers of a reading: structure_build and canon_extract, both engines ──────────────────────────────────────


def ekama_reading() -> dict[str, Any]:
    answer = GOLD["answer"]
    return Reading(filename="ekama.pdf", source="pages", canon=answer["canon"],
                   episodes=answer["episodes"]).model_dump(mode="json")


def test_analyse_takes_the_reading_in_both_engines():
    from structure_build.engine import analyse as legacy

    from hiru_ai.steps.structure_analyse import logic as graph_analyse

    doc = {"id": "d1", "filename": "ekama.pdf", "role": "script", "text": "unused", "reading": ekama_reading()}
    plans = [m.analyse([doc], []) for m in (legacy, graph_analyse)]
    assert plans[0] == plans[1]
    unit = next(iter(plans[0]["units"].values()))
    assert len(unit["scenes"]) == 9 and unit["number"] is None
    first = unit["scenes"][0]
    assert first["read_from"] == "pages" and first["envelope_s"] == 60
    assert [b["speaker"] for b in first["blocks"] if b["kind"] == "dialogue"] == ["Aruni"]


def test_a_scene_from_a_reading_is_written_with_how_it_was_read_in_both_engines():
    from structure_build.engine import write as legacy

    from hiru_ai.tools.structure_write import plan as graph_write

    doc = {"id": "d1", "filename": "ekama.pdf", "role": "script", "text": "", "reading": ekama_reading()}
    from structure_build.engine import analyse

    structure = analyse.apply_answers(analyse.analyse([doc], []), {"episode:d1:0": {"value": "1"}}, [])
    rows = []
    for m in (legacy, graph_write):
        p = m.plan(structure, production_id=str(uuid4()), canon=[], existing_episodes=[], existing_scenes=[],
                   envelope_s=60, aspect_ratio="16:9", actor=None)
        rows.append(p.scenes[0][0])
    for scene in rows:
        assert scene["read_from"] == "pages" and scene["read_confirmed_at"] is None and scene["envelope_s"] == 60


def test_canon_comes_from_the_readings_with_codes_from_the_rules_in_both_engines():
    from canon_extract.engine import pipeline as legacy
    from canon_extract.engine import rules as legacy_rules

    from hiru_ai.steps.canon_rules import logic as graph_rules
    from hiru_ai.steps.canon_rules import step as graph_step

    index = {"id": "i", "filename": "index.md", "role": "canon_index", "text": "C07 Dinu — the driver, 30."}
    script = {"id": "s", "filename": "ekama.pdf", "role": "script", "text": "", "reading": ekama_reading()}
    found = [reading_candidates([script, index], rule_candidates=r, merge=m.merge, same=m.same)
             for r, m in ((legacy.rule_candidates, legacy_rules), (graph_step.rule_candidates, graph_rules))]
    assert found[0] == found[1] and found[0] is not None
    dinu = next(c for c in found[0] if c["name"] == "Dinu")
    assert dinu["card"]["age"] == "30" and dinu["lines"] == 7
    assert reading_candidates([index], rule_candidates=legacy.rule_candidates, merge=legacy_rules.merge,
                              same=legacy_rules.same) is None
