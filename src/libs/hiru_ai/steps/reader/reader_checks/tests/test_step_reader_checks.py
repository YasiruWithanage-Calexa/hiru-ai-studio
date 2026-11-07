"""reader_checks runs alone, on JSON (the document reader's own tests are tests/contracts/test_doc_read.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hiru_ai.steps.reader.reader_checks import step

HERE = Path(__file__).resolve().parents[1]


def test_the_example_runs():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out == {"mode": "text", "corrupt_pages": []}


def test_pieces_and_a_check():
    text = "SCENE 01 - EXT. CANAL - DAWN\nARUNI - Oya enawada?"
    assert step.run({"op": "pieces", "text": text})["pieces"][0]["kind"] == "whole"
    answer = {"canon": {"characters": [], "locations": [], "props": []}, "transcription": [],
              "episodes": [{"number": 0, "title": "", "stated_runtime": "", "scenes": [
                  {"number": "01", "heading": "SCENE 01 - EXT. CANAL - DAWN", "int_ext": "EXT", "location": "Canal",
                   "sub_location": "", "time_of_day": "DAWN", "clock": "", "stated_seconds": 0, "flashback": False,
                   "lines": [1, 2], "blocks": [{"kind": "dialogue", "speaker": "Aruni", "cue": "ARUNI",
                                                "delivery": "", "text": "Are you coming?", "src": [2, 2]}]}]}]}
    problems = step.run({"op": "check", "text": text, "answer": answer})["problems"]
    assert len(problems) == 1 and "not the words of L0002" in problems[0]


def test_an_unknown_op_is_refused():
    with pytest.raises(ValueError):
        step.run({"op": "nope", "text": ""})
