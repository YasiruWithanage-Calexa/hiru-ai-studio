"""plan/2026-11-20: takes that hold the line (phase 3) and long lines in parts (phases 4-5), on the bins
`lab/line_parts` stored (Api Denna v2 E01-S04, runs 001 with steps and 002 with any length)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import timing
from contracts.raphael import checks
from contracts.raphael.bin import Bin
from contracts.raphael.packet import scene_from_packet
from contracts.raphael.scene import Brief, SceneS
from contracts.raphael.stored import StoredRaphael

LAB = Path(__file__).resolve().parents[2] / "lab" / "line_parts" / "runs"


def run(name: str) -> tuple[SceneS, StoredRaphael]:
    """The run's stored result and the scene it was planned on (the lab's own split packet)."""
    stored = StoredRaphael.load(json.loads((LAB / name / "result.json").read_text(encoding="utf-8"))["result"])
    assert stored is not None
    scene, _ = scene_from_packet(json.loads((LAB / name / "packet.json").read_text(encoding="utf-8")), stored.takes)
    return scene, stored


def blocking_clock(scene: SceneS, stored: StoredRaphael) -> list[checks.Fault]:
    brief = Brief(scene, float(scene.envelope_s or 0))
    found = checks.check_stage1(brief, Bin(edit=stored.edit, clips=stored.musts()))
    return [f for f in checks.blocking(found) if f.code == "clock"]


# ── phase 3: an overrun Raphael can fix blocks `finish` (D5) ─────────────────────────────────────────────────────────


def test_run_001_cannot_finish_with_takes_too_short_for_their_lines():
    """Run 001 finished with 5 clips over their takes (the overrun was report-only). Each now blocks, and says which
    take holds it."""
    scene, stored = run("001")
    faults = blocking_clock(scene, stored)
    assert sorted(c for f in faults for c in f.clips) == ["c02", "c03", "c04", "c08", "c11"]
    assert all("which holds it" in f.sentence for f in faults)
    assert "c02 needs 8.6 s for what it carries and the take is 8 s: take 10 s" in faults[0].sentence


def test_run_002_finishes_on_the_clock_the_lab_ran(monkeypatch: pytest.MonkeyPatch):
    """Run 002 (any length) had no clip over its take on the lab's clock, which paused between parts but not at a
    sentence end inside one line."""
    monkeypatch.setattr(timing, "SENTENCE_PAUSE_S", 0.0)
    scene, stored = run("002")
    assert blocking_clock(scene, stored) == []


def test_on_the_product_clock_run_002_is_five_clips_a_second_short_each_one_take_up():
    """D1 counts the pause at every sentence end inside a line too ("ඔව්. පොඩියට පටන් ගත්තේ."), so five of run 002's
    clips are 0.1 to 0.7 s short. Each blocks with the next length, which holds it: Raphael fixes them itself."""
    scene, stored = run("002")
    faults = blocking_clock(scene, stored)
    assert sorted(c for f in faults for c in f.clips) == ["c04", "c05", "c10", "c12", "c13"]
    assert all("which holds it" in f.sentence for f in faults)


def test_an_overrun_no_take_can_hold_blocks_only_when_the_clip_can_be_split():
    scene, stored = run("001")
    one = scene.model_copy(update={"takes": [4, 6]})  # nothing here holds the father's whole call
    clip = next(c for c in stored.clips if c.id == "c02")
    spoken = [i for i in checks._items(one, clip) if i.is_line]
    need = 99.0
    assert len(spoken) > 1
    assert checks.overrun(one, clip, need, spoken).fix == "repair"
    assert "cut it at a line or a part" in checks.overrun(one, clip, need, spoken).sentence
    assert checks.overrun(one, clip, need, spoken[:1]).fix == "report"


# ── phase 3: the length target (D6) ──────────────────────────────────────────────────────────────────────────────────


def test_the_target_is_the_scripts_own_time_when_that_is_longer():
    scene, _ = run("001")
    own = checks.script_s(scene)
    assert own > 45  # the scene is stated as 45 s
    brief = Brief(scene, 45.0)
    assert checks.target_s(brief) == float(int(own) + 1)
    assert checks.limit_s(brief) == checks.target_s(brief) * 1.5
    assert checks.target_s(Brief(scene, 90.0)) == 90.0
    assert checks.target_s(Brief(scene, 0.0)) == 0.0


def test_the_length_block_says_the_script_is_longer_and_keeps_its_words_when_it_is_not():
    from contracts.raphael.pack import length_block

    scene, _ = run("001")
    longer = length_block(Brief(scene, 45.0))
    assert "longer than the given 45 s, so the target and the cap are measured from the script" in longer
    assert "(the target x 1.5)" in longer
    shorter = length_block(Brief(scene, 90.0))
    assert "measured from the script" not in shorter and "(the given length x 1.5)" in shorter


# ── phase 5: Raphael plans in parts (D7, D11) ────────────────────────────────────────────────────────────────────────

E2E = Path(__file__).resolve().parents[2] / "lab" / "llm_reader" / "runs" / "e2e"


def packet() -> dict:
    return json.loads((E2E / "05_packets.json").read_text(encoding="utf-8"))["E01-S04"]


def test_e01_s04_is_given_with_its_three_long_lines_in_parts():
    from contracts.raphael.packet import split_packet
    from contracts.raphael.scene import part_groups

    split = split_packet(packet())
    scene, ids = scene_from_packet(split, [4, 6, 8, 10, 15])
    groups = {ids[g.lids[0]].rsplit("-P", 1)[0]: g for g in part_groups(scene)}
    assert {k: (len(g.lids), g.must) for k, g in groups.items()} == {
        "E01-S04-B02": (2, False), "E01-S04-B08": (2, False), "E01-S04-B12": (3, True)}
    assert groups["E01-S04-B12"].need_s == pytest.approx(9.46, abs=0.01)
    lab = json.loads((LAB / "001" / "packet.json").read_text(encoding="utf-8"))  # what the lab gave Raphael
    assert [{k: v for k, v in b.items() if k not in ("part", "parts", "whole")} for b in split["E_blocks"]] == \
        lab["E_blocks"]
    from contracts.raphael.packet import opening

    text, _, _ = opening(packet(), takes=[4, 6, 8, 10, 15], parts=True)
    assert "the whole line L13 + L14 + L15: 9.5 s as one take" in text and "too long for one take" in text
    assert "Part 1 of 3 of ONE line" in text  # the block's intent, as the lab gave it


def parted() -> tuple[SceneS, StoredRaphael]:
    """Run 002's stored bin on the scene cut by the product's own split (the same blocks the lab gave it)."""
    from contracts.raphael.packet import split_packet

    _, stored = run("002")
    scene, _ = scene_from_packet(split_packet(packet()), stored.takes)
    return scene, stored


def test_one_must_clip_holding_all_of_a_line_too_long_for_one_take_fails():
    scene, stored = parted()
    work = Bin(edit=stored.edit, clips=stored.musts())
    assert [f for f in checks.line_parts(scene, work)] == []  # run 002 spreads the father's call over c08 and c09
    c08 = next(c for c in work.clips if c.id == "c08")
    c08.lines = ["L13", "L14", "L15"]
    c08.blocks = sorted({*c08.blocks, 13, 14, 15})
    found = checks.blocking(checks.line_parts(scene, work))
    assert [f.key for f in found] == ["parts:whole:c08:L13"]


def test_two_parts_of_one_line_on_the_same_setup_and_size_are_a_jump_cut():
    scene, stored = parted()
    work = Bin(edit=stored.edit, clips=stored.musts())
    c08, c09 = (next(c for c in work.clips if c.id == i) for i in ("c08", "c09"))
    c09.setup, c09.size = c08.setup, c08.size  # L15 cut to from L14 on the same MCU from setup B
    assert [f.key for f in checks.blocking(checks.line_parts(scene, work))] == ["parts:jump:c08:c09"]


def test_two_must_clips_on_one_setup_and_size_side_by_side_in_the_cut_are_only_reported():
    _, stored = parted()
    found = checks.cut_jump(Bin(edit=stored.edit, clips=stored.musts()))
    assert found and all(f.fix == "report" and f.code == "cut" for f in found)


def scene_rows(*, parts: bool) -> tuple[dict, list[dict]]:
    """E01-S04 as the database holds it: one script block per packet block, a dialogue block pointing at its line."""
    script, lines = [], []
    for b in packet()["E_blocks"]:
        if b["kind"] == "dialogue" and b.get("speaker"):
            lines.append({"id": b["id"], "production_id": "p", "scene_id": "s", "ord": len(lines),
                          "speaker": b["speaker"], "character_id": None, "text": b["text"], "delivery": ""})
            script.append({"kind": "dialogue", "line_id": b["id"]})
        else:
            script.append({"kind": "action", "text": b["text"], "by": "person"})
    scene = {"id": "s", "production_id": "p", "number": 4, "script": script, "script_version": 1, "status": "draft",
             "envelope_s": 45, **({"line_parts": True} if parts else {})}
    return scene, lines


def test_the_writer_binds_a_line_in_parts_to_the_clip_of_its_first_part():
    """Run 002 written as shot rows: the father's call is L13 and L14 on one clip (4B-3) and L15 on the next (4E-1).
    His line row is bound to 4B-3, where it starts; its overrun is what all three parts run over."""
    from contracts.raphael.packet import line_block_id
    from hiru_ai.steps.raphael.raphael_write import logic

    _, stored = run("002")
    stored = stored.model_copy(update={
        "line_parts": True, "line_ids": {k: line_block_id(v) for k, v in stored.line_ids.items()}})
    scene, lines = scene_rows(parts=True)
    shots, line_rows, facts = logic.rows_for(scene, lines, stored, [])
    slate = {s["id"]: s["slate"] for s in shots}
    carried = {s["slate"]: [lf["line_id"] for lf in f["lines"]] for s, f in zip(shots, facts, strict=True)}
    assert carried["4B-3"] == ["L13", "L14"] and carried["4E-1"] == ["L15"]
    father = next(r for r in line_rows if r["id"] == "E01-S04-B12")
    assert slate[father["shot_id"]] == "4B-3" and father["words"] == 14
    parts_over = sum(lf["overrun_s"] for f in facts for lf in f["lines"] if lf["line_id"] in ("L13", "L14", "L15"))
    assert father["overrun_s"] == pytest.approx(parts_over, abs=0.01)
    assert not any(k.startswith("_") for r in line_rows for k in r)


def test_a_plan_in_parts_saves_the_flag_with_the_shots_and_a_plan_without_does_not_name_it():
    """D9: `scenes.line_parts` goes in the same write as the shots. A plan without parts names the column only when the
    scene row has it (schema v28), so a database without it still saves."""
    from contracts.raphael.packet import line_block_id
    from hiru_ai.steps.raphael.raphael_write import logic

    _, stored = run("002")
    stored = stored.model_copy(update={"line_ids": {k: line_block_id(v) for k, v in stored.line_ids.items()}})
    production = {"id": "p", "title": "Api Denna", "orientation": "horizontal", "settings": {}}
    scene, lines = scene_rows(parts=False)
    _, _, fields = logic.write(scene, lines, stored.model_copy(update={"line_parts": True}), [], production)
    assert fields["line_parts"] is True and fields["raphael"]["line_parts"] is True
    parted_lines = {"L1", "L2", "L8", "L9", "L13", "L14", "L15"}
    whole = stored.model_copy(update={"line_parts": False,
                                      "clips": [c for c in stored.clips if not set(c.lines) & parted_lines]})
    _, _, fields = logic.write(scene, lines, whole, [], production)
    assert "line_parts" not in fields and "line_parts" not in fields["raphael"]
    _, _, fields = logic.write({**scene, "line_parts": True}, lines, whole, [], production)
    assert fields["line_parts"] is False  # the column is there: a plan without parts clears it
