"""The rules are the legacy engine's, unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from doc_ingest.engine import roles

from hiru_ai.steps.document_role import step

HERE = Path(__file__).resolve().parents[1]
CORPUS = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "corpus"


@pytest.mark.parametrize("name", sorted(p.name for p in CORPUS.iterdir() if p.is_file() and p.suffix in
                                        (".fountain", ".txt", ".md")))
def test_the_rules_guess_what_the_legacy_engine_guessed(name: str):
    text = (CORPUS / name).read_text(encoding="utf-8")
    old = roles.detect_by_rules(name, text)
    new = step.run({"filename": name, "text": text})
    assert (new["role"], new["confidence"], new["reason"], new["source"]) == (
        old.role.value, old.confidence, old.reason, old.source)
    assert new["ask_model"] == (old.confidence < roles.LLM_THRESHOLD)


def test_it_runs_on_its_example():
    case = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    assert step.run(case)["role"] == "script"
