"""Offline tests of the lightweight editor: what code reads itself, the words guard, the story-check wiring. No model."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "lab" / "zora_rows"), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import agents  # noqa: E402
import light  # noqa: E402
from prod import Production  # noqa: E402
from turn import Thread  # noqa: E402

PROD = Production.load(HERE / "input" / "story_production.json")


def scene():
    return PROD.coverage("E2S2")


def test_code_reads_an_added_clip_in_the_persons_words() -> None:
    cov = scene()
    ops = light.quick_add("Add a 4-second insert after S03 of Dilini's anatomy textbook.", cov)["ops"]
    assert ops == [{"op": "insert", "after": "S03", "role": "insert", "size": "INSERT", "take_s": 4, "first_block": 3,
                    "last_block": 3, "who": ["Dilini"], "what": "Dilini's anatomy textbook"}]
    ops = light.quick_add("Add a shot after S06 of Sahan handing Dilini a stethoscope.", cov)["ops"]
    assert (ops[0]["size"], ops[0]["take_s"], ops[0]["what"], ops[0]["who"]) == (
        "MS", 4, "Sahan handing Dilini a stethoscope", ["Dilini", "Sahan"])
    assert light.quick_add("add a 6s close-up after S02 showing her hands", cov)["ops"][0]["size"] == "CU"


def test_code_reads_what_a_shot_shows_in_the_persons_words() -> None:
    cov = scene()
    for message in ("In S05, show Dilini wearing jeans and a t-shirt.", "make S05 show Dilini wearing jeans and a t-shirt",
                    "S05 should show Dilini wearing jeans and a t-shirt"):
        assert light.quick_show(message, cov)["ops"] == [
            {"op": "set", "shot": "S05", "field": "sees", "value": "Dilini wearing jeans and a t-shirt"}], message


def test_what_code_does_not_read_goes_to_the_model() -> None:
    cov = scene()
    for message in ("Add more tension after S03.", "Add a 5-second insert after S03 of the bag.",
                    "Add an insert after S99 of the bag.", "Show me the options for the ending.",
                    "Add a 4-second insert of the letter after S02.", "In S05, show me why it is wide",
                    "Why is S05 showing Dilini?"):
        got = light.quick_add(message, cov) or light.quick_show(message, cov)
        assert got is None or message.startswith("In S05"), message


def test_an_edit_code_reads_still_goes_through_the_story_check() -> None:
    th = Thread(cov=scene())
    th.open_label = "E2S2"  # type: ignore[attr-defined]
    script = {"t1.check": {"conflicts": [{"fact": "Dilini wears a saree.", "source": "Dilini's card",
                                          "why": "this shows her in jeans."}]}}
    rec = light.run_turn(th, "In S05, show Dilini wearing jeans and a t-shirt.", agents.Rehearsal(script), "t1", PROD)
    assert rec["by_code"] and rec["card"] and "Heads-up: the story says Dilini wears a saree" in rec["reply"]
    assert not rec["saved"]


def test_a_size_change_read_by_code_is_not_story_checked() -> None:
    th = Thread(cov=scene())
    th.open_label = "E2S2"  # type: ignore[attr-defined]
    be = agents.Rehearsal({})
    rec = light.run_turn(th, "Make S01 a wide.", be, "t2", PROD)
    assert rec["saved"] and not any(c["role"] == "check" for c in be.calls)


def test_the_words_guard_keeps_the_persons_subject() -> None:
    rec: dict = {}
    ops = light.keep_words([{"op": "insert", "after": "S02", "what": "Dilini's Colombo Medical Faculty acceptance letter"}],
                           "Add a 4-second insert after S02 of Dilini's engineering faculty admission letter.", rec)
    assert "engineering" in ops[0]["what"] and rec["guarded"]
