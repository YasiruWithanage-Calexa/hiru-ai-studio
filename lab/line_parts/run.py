"""Line parts lab (2026-11-19): can Raphael cover a long line in parts, cut at sentence ends, on changing angles?

    .venv/Scripts/python.exe lab/line_parts/run.py              free: the split, and what Raphael would be told
    .venv/Scripts/python.exe lab/line_parts/run.py --yes        paid: Raphael plans the scene (cap $0.40)

Scene: Api Denna v2 (the Love Hour story) E01-S04, the saved packet of lab/llm_reader/runs/e2e. The saved Raphael plan
of the same scene (`12_raphael/E01-S04.txt`, old code) is the "before". NOTHING in src/ changes and nothing is written to
the database: every change below is made in this process only.

What the lab changes
  SPLIT  a dialogue block with two or more sentences becomes consecutive blocks, one per sentence ("Part k of n of ONE
         line"), the script's words unchanged; a sentence under 3 words joins its neighbour. Raphael may keep parts
         together in one clip or give each its own (the person's (c)).
  MUST   a line whose time, on the clock the Sinhala pace lab measured, runs past 8 s is marked "too long for one take":
         a lab check refuses any must clip that holds all of it (the person's (b)).
  CLOCK  lead-in 0.5 -> 1.0 s and the gap between two lines 0.3 -> 0.8 s (lab/sinhala_pace run 1: Omni starts near
         1 s and pauses 0.75 to 1 s at a sentence end); takes 4/6/8/10/15 (the person's steps).
  RULE   house rule H-91 (h91_line_parts.md) on the coverage topic.
  CHECK  consecutive parts in different must clips change size or setup (no jump cut).

Writes runs/<NNN>/: packet.json (the split packet), opening.txt (Raphael's first message), plan.txt (the breakdown),
parts.md (each long line: its parts and the clips that carry them), result.json, spend.txt.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

SID = "E01-S04"
E2E = ROOT / "lab" / "llm_reader" / "runs" / "e2e"
RULE_FILE = HERE / "h91_line_parts.md"
SCENE_CAP_USD = 0.40
TAKES = [4, 6, 8, 10, 15]
TAKE_SETS = {"steps15": [4, 6, 8, 10, 15], "steps10": [4, 6, 8, 10], "any15": list(range(3, 16))}
LEAD_IN_S, LINE_GAP_S, TAIL_S = 1.0, 0.8, 0.5  # lab/sinhala_pace run 1
MUST_PAST_S = 8.0  # the long-take soft cap
MIN_PART_WORDS = 3
NL = "\n"

_SENTENCE_END = re.compile(r"(?<=[.?!…])[\"'”]?\s+")


# ── the split (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────


def sentences(text: str) -> list[str]:
    """The line cut after each sentence end; a sentence under MIN_PART_WORDS joins the next (the last joins the one
    before). Joining the parts with single spaces gives the line back."""
    body = text.strip().strip("\"“”").strip()
    parts = [p.strip() for p in _SENTENCE_END.split(body) if p.strip()]
    merged: list[str] = []
    carry = ""
    for p in parts:
        p = f"{carry} {p}".strip() if carry else p
        carry = ""
        if len(p.split()) < MIN_PART_WORDS:
            carry = p
        else:
            merged.append(p)
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged


def line_need_s(text: str) -> float:
    """A whole line's take on the measured clock: lead-in, the words, a pause at every sentence end inside it, tail."""
    from contracts.timing import speech_seconds, words_in

    breaks = max(len([p for p in _SENTENCE_END.split(text.strip()) if p.strip()]) - 1, 0)
    return LEAD_IN_S + speech_seconds(words_in(text)) + LINE_GAP_S * breaks + TAIL_S


def split_packet(packet: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The packet with every multi-sentence line as consecutive part blocks, and one row per split line."""
    p = copy.deepcopy(packet)
    blocks, groups = [], []
    changes = (p.get("stage") or {}).get("changes_at", {})
    turns = p["F_feeling"].get("turns", [])
    for b in p["E_blocks"]:
        parts = sentences(b["text"]) if b["kind"] == "dialogue" and b.get("speaker") else []
        if len(parts) < 2:
            blocks.append(b)
            continue
        need = line_need_s(b["text"])
        must = need > MUST_PAST_S
        ids = [f"{b['id']}-P{k}" for k in range(1, len(parts) + 1)]
        for k, (pid, text) in enumerate(zip(ids, parts, strict=True), start=1):
            nb = copy.deepcopy(b)
            nb["id"], nb["text"] = pid, text
            head = (f"Part {k} of {len(parts)} of ONE line (cut at a sentence end; the words are the script's, "
                    "unchanged)." + (f" This line is too long for one take ({need:.1f} s): its parts go in at least "
                                     "two different must clips." if must else ""))
            nb["intent"] = f"{head} {b.get('intent') or ''}".strip()
            if k > 1:
                nb["events"] = []  # the events belong to the line once
            blocks.append(nb)
        if b["id"] in changes:  # the state change lands when the line is done
            changes[ids[-1]] = changes.pop(b["id"])
        if b["id"] in turns:  # the turn in feeling comes with the line's first words
            turns[turns.index(b["id"])] = ids[0]
        groups.append({"line": b["id"], "text": b["text"], "need_s": round(need, 1), "must": must, "parts": ids,
                       "part_text": parts})
    p["E_blocks"] = blocks
    return p, groups


# ── the lab's own checks, added to stage 1 in this process ───────────────────────────────────────────────────────────


def parts_faults(groups: list[dict[str, Any]], ids: dict[str, str]):  # noqa: ANN201
    from contracts.raphael import checks

    line_of = {v: k for k, v in ids.items() if k.startswith("L")}  # block id -> L7

    def check(work: Any) -> list[Any]:
        out = []
        musts = work.musts()
        for g in groups:
            lids = [line_of[pid] for pid in g["parts"]]
            if g["must"]:
                for c in musts:
                    if all(lid in c.lines for lid in lids):  # lips or a heard voice: one take carries it all
                        out.append(checks._fault(
                            "parts",
                            f"{c.id} holds all of {', '.join(lids)}, one line too long for one take "
                            f"({g['need_s']} s): spread its parts over at least two must clips, cut at a sentence end.",
                            [c.id], key=f"parts:whole:{c.id}:{g['line']}"))
            carrier = [next((c for c in musts if lid in c.lines), None) for lid in lids]
            for a, b, la, lb in zip(carrier, carrier[1:], lids, lids[1:]):
                if a is None or b is None or a.id == b.id:
                    continue
                if a.setup == b.setup and a.size == b.size:
                    out.append(checks._fault(
                        "parts",
                        f"{la} ({a.id}) and {lb} ({b.id}) are consecutive parts of one line on the same setup "
                        f"{a.setup} and size {a.size}: a jump cut. Change the size or the setup at the cut.",
                        [a.id, b.id], key=f"parts:jump:{a.id}:{b.id}"))
        return out

    return check


def patch(groups: list[dict[str, Any]], ids: dict[str, str]) -> None:
    """The clock, the rule and the checks, in this process only."""
    from contracts import shotplan
    from contracts.raphael import checks
    from contracts.raphael import scene as rscene
    from hiru_ai.core import house_rules

    shotplan.LEAD_IN_S, shotplan.LINE_GAP_S, shotplan.TAIL_S = LEAD_IN_S, LINE_GAP_S, TAIL_S
    rscene.LEAD_IN_S, rscene.TAIL_S = LEAD_IN_S, TAIL_S
    deployed = house_rules.load()
    extra = house_rules.parse(RULE_FILE)
    house_rules.rules = lambda: tuple(sorted((*deployed, extra), key=lambda r: r.id))
    assert any(r.id == extra.id for r in house_rules.select(["coverage"]))
    original = checks.check_stage1
    lab = parts_faults(groups, ids)

    def check_stage1(brief: Any, work: Any, *args: Any, **kw: Any) -> list[Any]:
        return [*original(brief, work, *args, **kw), *lab(work)]

    checks.check_stage1 = check_stage1


# ── reports ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def parts_report(groups: list[dict[str, Any]], ids: dict[str, str], result: dict[str, Any]) -> str:
    line_of = {v: k for k, v in ids.items() if k.startswith("L")}
    clips = result.get("clips") or []
    out = [f"# {SID}: long lines in parts", ""]
    for g in groups:
        out += [f"## {g['line']}: {g['need_s']} s on the measured clock, "
                + ("MUST split (past 8 s)" if g["must"] else "may split"), "", f"> {g['text']}", ""]
        for pid, text in zip(g["parts"], g["part_text"], strict=True):
            lid = line_of[pid]
            out.append(f"- **{lid}** «{text}»")
            for c in clips:
                if lid in (c.get("lines") or []):
                    who = "lips" if c.get("speaks") else f"voice over {c.get('over') or 'picture'}"
                    out.append(f"  - {c.get('slate')} [{c.get('id')}] stage {c.get('stage')} {c.get('priority')}: "
                               f"{c.get('role')} · {c.get('size')} · setup {c.get('setup')} · {c.get('angle')} · "
                               f"take {c.get('take_s')} s · {who}")
        out.append("")
    return NL.join(out)


def next_dir() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[:3]) for p in runs.iterdir() if p.name[:3].isdigit()), default=0)
    out = runs / f"{n:03d}"
    out.mkdir()
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="the person said yes: Raphael plans the scene (paid)")
    ap.add_argument("--takes", choices=sorted(TAKE_SETS), default="steps15", help="the production's take lengths")
    a = ap.parse_args()
    takes = TAKE_SETS[a.takes]

    packet = json.loads((E2E / "05_packets.json").read_text(encoding="utf-8"))[SID]
    split, groups = split_packet(packet)
    from contracts.raphael.packet import opening

    out = next_dir() if a.yes else HERE / "runs" / "dry"
    out.mkdir(parents=True, exist_ok=True)
    (out / "packet.json").write_text(json.dumps(split, indent=1, ensure_ascii=False), encoding="utf-8")
    text, script, ids = opening(split, takes=takes)
    patch(groups, ids)
    text, script, ids = opening(split, takes=takes)  # again, on the patched clock
    (out / "opening.txt").write_text(text, encoding="utf-8")
    for g in groups:
        print(f"{g['line']}: {g['need_s']} s, {'MUST' if g['must'] else 'may'} split -> {len(g['parts'])} parts: "
              + " | ".join(g["part_text"]))
    print(f"opening: {len(text)} chars -> {out.relative_to(ROOT)}")
    if not a.yes:
        print("dry run: Raphael not called. Add --yes after the person's yes (cap $%.2f)." % SCENE_CAP_USD)
        return

    from cinematic.run import load_env

    from hiru_ai.core.context import RunContext
    from hiru_ai.core.settings import get_settings
    from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael
    from two_memories.live import clip_text

    load_env()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    get_settings.cache_clear()
    line_ids = {k: v for k, v in ids.items() if k.startswith("L")}
    planner = raphael.Planner(RunContext(), script, number=int(SID[-2:]), line_ids=line_ids, production={},
                              context={}, opening=text)
    started = time.monotonic()
    try:
        result = planner.plan(previous={}, job_id=f"lab-parts-{SID}").stored.model_dump(mode="json")
        status = "done"
    except raphael.Failed as exc:
        result, status = {}, f"failed: {exc}"
    spend = (f"{status}, {planner.meter.calls} calls, {time.monotonic() - started:.0f} s, "
             f"${planner.meter.spent:.4f}")
    spend += f", takes {a.takes}"
    (out / "spend.txt").write_text(spend + NL, encoding="utf-8")
    (out / "result.json").write_text(json.dumps({"ids": ids, "log": planner.log, "warnings": planner.warnings,
                                                 "result": result}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "plan.txt").write_text(clip_text(SID, result, split, ids, status), encoding="utf-8")
    (out / "parts.md").write_text(parts_report(groups, ids, result), encoding="utf-8")
    print(spend)
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
