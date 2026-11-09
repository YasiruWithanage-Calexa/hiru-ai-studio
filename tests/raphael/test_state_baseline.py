"""The "before" number (plan/2026-11-09 phase 0): the state checks over the lab's run 3 bin (stage 1) and pass 5 (the
final bin) with the gold ledger, a person's reading of the roadside. These are the faults Raphael made with no memory;
phase 9's lab compares its runs with them.

Expected by the plan, and found: c05 shows the phone handed over with neither hand; Kasun is put back by the counter
after he ran after Anudi (c07, and also c12 and c14, the closing clips, by the same reading); Anudi's handbag is in her
description and never placed."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.raphael import checks
from tests.raphael import gold

RUN3 = Path(__file__).resolve().parents[2] / "lab" / "raphael" / "runs" / "3-gpt_5_high_episode1" / "bin.json"

BASELINE = {
    "state:handover:c05:phone:9",
    "state:zone:c07:Kasun",
    "state:zone:c12:Kasun",
    "state:zone:c14:Kasun",
    "state:unplaced:handbag",
}


def keys(found: list[checks.Fault]) -> set[str]:
    return {f.key for f in found}


def test_run_3s_must_bin_against_the_gold_ledger():
    found = checks.state(gold.ledger_scene(), gold.stage1())
    assert keys(found) == BASELINE
    assert all(f.code == "state" and f.fix == "report" and f.owner == "raphael" for f in found)
    handover = next(f for f in found if f.key.startswith("state:handover"))
    assert handover.sentence == (
        "c05: the phone passes from Kasun to Anudi at b9: show Kasun's hand giving it and Anudi's left hand taking it."
    )


def test_the_cinematic_pass_adds_no_state_fault_of_its_own():
    assert keys(checks.state(gold.ledger_scene(), gold.final())) == BASELINE


def test_the_lab_bin_is_the_fixture_the_baseline_reads():
    """The fixture is run 3's bin, saved; the lab's own copy (while the lab exists) holds the same clips."""
    if not RUN3.exists():
        return
    lab = json.loads(RUN3.read_text(encoding="utf-8"))
    clips = lab["clips"] if isinstance(lab, dict) else lab
    assert sorted(c["id"] for c in clips) == sorted(c.id for c in gold.stage1().clips)


def test_the_baseline_reports_and_never_blocks_finish():
    brief = checks.Brief(scene=gold.ledger_scene(), guide_s=gold.brief().guide_s)
    with_ledger = checks.check_stage1(brief, gold.stage1())
    without = checks.check_stage1(gold.brief(), gold.stage1())
    assert checks.blocking(with_ledger) == checks.blocking(without) == []
    assert keys(with_ledger) - keys(without) == BASELINE
