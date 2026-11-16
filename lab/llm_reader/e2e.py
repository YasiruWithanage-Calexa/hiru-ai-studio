"""PDF to shots, one step at a time, each step checked before the next (2026-11-15). NOTHING is written to the database.

    python lab/llm_reader/e2e.py <step> [--yes]       steps: 1 text, 2 reading, 3 breakdown, 4 stager, 5 packets, 6 shots

    1 text       poppler `pdftotext -layout` in python:3.12-slim (Docker), as the server will run it         free
    2 reading    probe + reader (run.py's calls; cached) -> checks -> gates                                  free (cached)
    3 breakdown  contracts.breakdown.run.create(): split / continuity / episode answers REPLAYED from
                 runs/connect1 (no new call when the message is the same); the split's scene cuts replaced by
                 the reading's; FIX: lines the reading used as scene facts (place, length) are not story, so
                 the word check does not send them to repair                                                    free unless a call is new
    4 stager     breakdown_stager, one call per scene of episode 1                                            paid
    5 packets    contracts.breakdown.packet.assemble(); the reading's title and length put in the packet      free
    6 shots      Raphael on the packet path (as raphael_shot_planner with RAPHAEL_PACKET), per-scene cap        paid

Money: this test's own cap, E2E_CAP_USD ($1.50, the person's, 2026-11-15), ledger runs/e2e/ledger.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

E2E_CAP_USD = 1.50
SCENE_CAP_USD = 0.33  # Raphael's own per-scene meter for this test (4 scenes: at most $1.32)
EPISODE = 1
OUT = HERE / "runs" / "e2e"
LEDGER = OUT / "ledger.csv"
PDF = Path.home() / "Downloads" / "Api_Denna_Script_v2.pdf"
STEM = "B_v2_pdf"
PRICE = (2.00, 0.10, 10.00)
FIELDS = ["time", "step", "slot", "model", "input_tokens", "cached_tokens", "output_tokens", "dollars", "status"]
NL = "\n"


# ── money ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def enter(row: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def agent_call(step: str, slot: str, agent_id: str, message: str, worst_out: int) -> Any:
    from hiru_ai.core import agents
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.tokens import tokens_of

    agent = agents.build(agent_id)
    worst = (tokens_of(agent.prompt.text) + tokens_of(message)) * PRICE[0] / 1e6 + worst_out * PRICE[2] / 1e6
    if spent() + worst > E2E_CAP_USD + 1e-9:
        raise RuntimeError(f"refused {slot}: ${spent():.4f} spent, it could cost ${worst:.4f}, cap ${E2E_CAP_USD:.2f}")
    usage: list[dict[str, Any]] = []
    started = time.time()
    got = agent.run({"message": message}, RunContext(usage_sink=usage.append))
    i = sum(int(u.get("input_tokens") or 0) for u in usage)
    c = sum(int(u.get("cached_input_tokens") or 0) for u in usage)
    o = sum(int(u.get("output_tokens") or 0) for u in usage)
    dollars = (i - c) * PRICE[0] / 1e6 + c * PRICE[1] / 1e6 + o * PRICE[2] / 1e6 if usage else worst
    enter({"time": time.strftime("%H:%M:%S"), "step": step, "slot": slot, "input_tokens": i, "cached_tokens": c,
           "output_tokens": o, "model": str((usage[0] if usage else {}).get("model") or ""),
           "dollars": f"{dollars:.4f}", "status": "done"})
    print(f"    {slot}: {time.time() - started:.0f} s, in {i}, out {o}, ${dollars:.4f}", flush=True)
    return got


# ── shared state ───────────────────────────────────────────────────────────────────────────────────────────────────


def lines() -> list[str]:
    return (OUT / "01_text.txt").read_text(encoding="utf-8").rstrip(NL).split(NL)


def reading() -> Any:
    from schema import Answer

    return Answer.model_validate_json((OUT / "02_reading.json").read_text(encoding="utf-8"))


def memory() -> Any:
    from contracts.breakdown.schema import Breakdown

    return Breakdown.model_validate_json((OUT / "03_memory.json").read_text(encoding="utf-8"))


def save_memory(bd: Any, name: str = "03_memory.json") -> None:
    (OUT / name).write_text(bd.model_dump_json(indent=1), encoding="utf-8")


def fact_lines(a: Any) -> set[int]:
    """The lines the reading took a scene's place or stated length from, when no spoken words are on them."""
    spoken = {n for s in a.scenes for n in s.spoken_lines}
    got = {s.place_source.line for s in a.scenes} | {s.length.source.line for s in a.scenes if s.length.stated}
    return {n for n in got if n and n not in spoken}


def ep1(bd: Any) -> list[Any]:
    return [s for s in bd.scenes if s.episode == EPISODE]


def report(step: str, ok: bool, rows: list[str]) -> None:
    text = NL.join([f"## Step {step}: {'PASSED' if ok else 'FAILED'}", "", *rows, "",
                    f"Spent so far in this test: ${spent():.4f} of ${E2E_CAP_USD:.2f}", ""])
    (OUT / f"step{step[0]}.md").write_text(text, encoding="utf-8")
    print(text)
    if not ok:
        sys.exit(1)


# ── the steps ──────────────────────────────────────────────────────────────────────────────────────────────────────


def step1() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["MSYS_NO_PATHCONV"] = "1"
    cmd = ["docker", "run", "--rm", "-v", f"{PDF.parent}:/pdfs:ro", "-v", f"{OUT}:/out", "python:3.12-slim", "sh", "-c",
           "apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends poppler-utils >/dev/null "
           f"2>&1; pdftotext -v 2>&1 | head -1; pdftotext -enc UTF-8 -layout '/pdfs/{PDF.name}' /out/01_poppler_raw.txt"]
    version = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    raw = (OUT / "01_poppler_raw.txt").read_text(encoding="utf-8").replace("\f", NL)
    text = [ln for ln in (" ".join(x.split()) for x in raw.split(NL)) if ln]
    (OUT / "01_text.txt").write_text(NL.join(text) + NL, encoding="utf-8")
    import checks

    bad = checks.misplaced_signs(NL.join(text))
    same = text == (HERE / "inputs" / f"{STEM}.txt").read_text(encoding="utf-8").rstrip(NL).split(NL)
    report("1 text", not bad and len(text) == 301, [
        f"- engine: {version}", f"- lines: {len(text)} (expected 301)",
        f"- Sinhala words with a vowel sign before its letter: {len(bad)} (expected 0)",
        f"- identical to the reading lab's input (so step 2 is cached): {same}",
        f"- first line: {text[0]}"])


def step2() -> None:
    import checks
    import run as lab
    from schema import Answer, Probe

    text = lines()
    user = lab.numbered(STEM, text)
    probe = Probe.model_validate_json(lab.call("e2e", f"{STEM}/probe", "probe", lab.prompt("probe.md"), user, Probe))
    a = Answer.model_validate_json(lab.call("e2e", f"{STEM}/read", "read", lab.prompt("system.md"), user, Answer))
    res = checks.Result(checks.check(a, text), checks.gates(a, text))
    (OUT / "02_reading.json").write_text(a.model_dump_json(indent=1), encoding="utf-8")
    rows = [f"- probe: {probe.kind}, text readable: {probe.text_quality.readable}",
            f"- episodes {len(a.episodes)}, scenes {len(a.scenes)}; checks: {len(res.findings)} findings; "
            f"gates: {', '.join(f'{g.level} {g.message}' for g in res.gates) or 'none'}; **verdict {res.verdict}**",
            "", "| scene | heading | title | place | length used | from |", "|---|---|---|---|---|---|"]
    rows += [f"| {checks.tag(s)} | {s.heading.quote} | {s.title} | {s.place} | {checks.envelope(s):g} s | "
             f"{s.length.source.quote} |" for s in a.scenes if s.episode == EPISODE]
    rows += [f"- scene-fact lines (not story): {sorted(fact_lines(a))[:8]} … ({len(fact_lines(a))} lines)"]
    report("2 reading", res.verdict == "go" and probe.text_quality.readable, rows)


def step3() -> None:
    from connect import cuts
    from contracts.breakdown import checks as bchecks
    from contracts.breakdown import run as brun
    from contracts.breakdown.schema import ContinuityW, EpisodeW, SplitW

    a, text = reading(), lines()
    facts = fact_lines(a)
    saved = {}
    for f in sorted((HERE / "runs" / "connect1" / "calls").glob("*.json")):
        slot = f.stem.split("_", 1)[1]
        if slot in ("split", "continuity", "episode"):
            d = json.loads(f.read_text(encoding="utf-8"))
            saved[d["message"]] = (slot, d["answer"])
    used = {"replayed": 0, "new": 0, "repairs": 0}

    def replay(slot: str, agent_id: str, model: Any, worst_out: int) -> Any:
        def call(m: str) -> Any:
            if slot == "repair":
                used["repairs"] += 1
                raise RuntimeError("repair refused: step 3 must pass without repair (the person sees why first)")
            if m in saved and saved[m][0] == slot:
                used["replayed"] += 1
                print(f"    {slot}: replayed from connect1 (no cost)", flush=True)
                return model.model_validate(saved[m][1])
            used["new"] += 1
            return agent_call("3", slot, agent_id, m, worst_out)
        return call

    orig_words = bchecks.words

    class FactsAreNotStory:  # the product fix, simulated: a scene-fact line has no story words to place in a block
        def __init__(self, doc: Any) -> None:
            self._doc = doc

        def words(self, n: int) -> list[str]:
            return [] if n in facts else self._doc.words(n)

        def __getattr__(self, k: str) -> Any:
            return getattr(self._doc, k)

    def words_fixed(bd: Any, doc: Any) -> list[Any]:
        """The product fixes, simulated. (1) scene-fact lines hold no story words; (2) on a dialogue block's first line,
        the words BEFORE the model's span are the speaker's label, in any style ("Kasun:", "KASUN", "Kasun -"), where
        checks.py:95 accepts only "ARUNI -". The rest of the check is unchanged: its findings, minus the words these
        two account for."""
        cue = {}
        for sc in bd.scenes:
            for b in sc.blocks:
                if b["kind"] == "dialogue" and b["spans"] and b["spans"][0][1] > 0:
                    line, a, _ = b["spans"][0]
                    cue[line] = max(cue.get(line, 0), a)

        class Doc2(FactsAreNotStory):
            def words(self, n: int) -> list[str]:
                ws = super().words(n)
                return ws if n not in cue else [""] * 0 + ws  # positions kept; the cue is marked as seen below

        found = orig_words(bd, Doc2(doc))
        keep = []
        for f in found:
            if f.code == "words" and "in no block" in f.message and "in two blocks" not in f.message:
                sc = bd.scene(f.scene)
                left = [(ln, w) for ln in range(sc.first, sc.last + 1) if ln not in facts
                        for w in range(cue.get(ln, 0), len(doc.words(ln)))
                        if not any(sp[0] == ln and sp[1] <= w < sp[2] for b in sc.blocks for sp in b["spans"])]
                if not left:
                    continue  # every word "in no block" was a speaker's label
            keep.append(f)
        return keep

    bchecks.words = words_fixed
    split_call = replay("split", "breakdown_split", SplitW, 16_000)
    calls = brun.Calls(split=lambda m: split_call(m).model_copy(update={"episodes": cuts(a)}),
                       continuity=replay("continuity", "breakdown_continuity", ContinuityW, 16_000),
                       episode=replay("episode", "breakdown_episode", EpisodeW, 32_000),
                       repair=replay("repair", "breakdown_repair", EpisodeW, 10_000))
    upload = brun.Upload(document_id="lab-v2", filename=PDF.name, text=NL.join(text))
    res = brun.create([upload], calls, production="lab", workers=1, progress=lambda t: print(f"    > {t}", flush=True))
    bd = res.memory
    by_key = {(s.episode, s.number): s for s in a.scenes}
    for sc in bd.scenes:  # the product fix, simulated: the reading's heading words (build.py:97 copies the whole line)
        sc.heading = by_key[(sc.episode, sc.number)].heading.quote
    save_memory(bd)
    blocking = [f for f in bd.findings if f.blocking]
    leaks = [(sc.id, b["text"][:50]) for sc in bd.scenes for b in sc.blocks
             if any(k in b["text"] for k in ("Location:", "Duration:"))]
    rows = [f"- calls: {used['replayed']} replayed from connect1, {used['new']} new, {used['repairs']} repair calls "
            "(expected 0)", f"- breakdown notes: {'; '.join(res.notes) or 'none'}",
            f"- blocking findings: {len(blocking)} (expected 0)" + "".join(f"{NL}  - {f.scene} {f.code}: "
                                                                          f"{f.message[:140]}" for f in blocking[:6]),
            f"- 'Location:' or 'Duration:' inside any filmable block: {len(leaks)} (expected 0) {leaks[:3]}",
            "", "| scene | heading | blocks | dialogue blocks | first dialogue (cut from the PDF by code) |",
            "|---|---|---|---|---|"]
    for sc in ep1(bd):
        dl = [b for b in sc.blocks if b["kind"] == "dialogue"]
        rows.append(f"| {sc.id} | {sc.heading} | {len(sc.blocks)} | {len(dl)} | {dl[0]['text'] if dl else '—'} |")
    report("3 breakdown", not blocking and not leaks and used["repairs"] == 0, rows)


def step4() -> None:
    from contracts.breakdown import run as brun
    from contracts.breakdown import stage

    bd = memory()
    rows = ["| scene | zones | marks | props | findings |", "|---|---|---|---|---|"]
    ok = True
    for sc in ep1(bd):
        got = agent_call("4", f"stager {sc.id}", "breakdown_stager", brun.stage_message(bd, sc.id), 6_000)
        found = stage.apply(bd, sc, got)
        bd.findings += found
        st = sc.stage or {}
        ok &= bool(sc.stage) and not any(f.blocking for f in found)
        rows.append(f"| {sc.id} | {len(st.get('zones') or [])} | {len(st.get('marks') or [])} | "
                    f"{len(st.get('props') or [])} | {'; '.join(f.message[:80] for f in found) or 'none'} |")
    save_memory(bd)
    report("4 stager", ok, rows)


def step5() -> None:
    from contracts.breakdown import packet, render

    bd, a = memory(), reading()
    by_key = {(s.episode, s.number): s for s in a.scenes}
    packets, rows, ok = {}, ["| scene | title | target s | spoken s | blocks | waiting on |", "|---|---|---|---|---|---|"], True
    texts = []
    for sc in ep1(bd):
        p = packet.assemble(bd, sc.id)
        r = by_key[(sc.episode, sc.number)]
        # the product fix, simulated: the reading's title and stated length (packet.py:236 reads `_MINUTES`)
        p["A_scene"]["title"] = r.title
        p["H_length"]["stated_seconds"] = round(r.length.high_seconds)
        waits = packet.incomplete(bd, p)
        ok &= not waits
        packets[sc.id] = p
        texts.append(render.render(p))
        rows.append(f"| {sc.id} | {r.title} | {p['H_length']['stated_seconds']} | {p['H_length']['spoken_seconds']} | "
                    f"{len(p['E_blocks'])} | {'; '.join(waits) or 'nothing'} |")
    (OUT / "05_packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "05_packets.txt").write_text(("\n\n" + "=" * 100 + "\n\n").join(texts), encoding="utf-8")
    report("5 packets", ok, rows)


def step6() -> None:
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    from cinematic.run import load_env
    from hiru_ai.core.settings import get_settings

    load_env()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    get_settings.cache_clear()
    from two_memories.live import raphael_one

    packets = json.loads((OUT / "05_packets.json").read_text(encoding="utf-8"))
    (OUT / "12_raphael").mkdir(parents=True, exist_ok=True)
    rows = ["| scene | status | clips | takes s | target s | dialogue lines used | calls | $ |",
            "|---|---|---|---|---|---|---|---|"]
    ok = True
    for sid, p in packets.items():
        if spent() + SCENE_CAP_USD > E2E_CAP_USD + 1e-9:
            rows.append(f"| {sid} | not run: the test's cap | | | | | | |")
            ok = False
            continue
        print(f"  Raphael {sid} (cap ${SCENE_CAP_USD}) ...", flush=True)
        s = raphael_one(OUT, sid, p, int(sid[-2:]))
        enter({"time": time.strftime("%H:%M:%S"), "step": "6", "slot": f"raphael {sid}", "model": "raphael",
               "dollars": f"{s['dollars']:.4f}", "status": s["status"]})
        r = json.loads((OUT / "12_raphael" / f"{sid}.json").read_text(encoding="utf-8"))
        res = r.get("result") or {}
        clips = res.get("clips") or []
        line_ids = {k for k in r.get("ids", {}) if k.startswith("L")}
        used_lines = {str(x) for c in clips for x in (c.get("lines") or [])}
        takes = sum(float(c.get("take_s") or 0) for c in clips)
        ok &= s["status"] == "done"
        rows.append(f"| {sid} | {s['status']} | {len(clips)} | {takes:g} | {p['H_length']['stated_seconds']} | "
                    f"{len(used_lines & line_ids)} of {len(line_ids)} | {s['calls']} | {s['dollars']:.4f} |")
    rows += ["", "Each scene's shots, readable: `runs/e2e/12_raphael/<scene>.txt`."]
    report("6 shots", ok, rows)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Sinhala in the console
    ap = argparse.ArgumentParser()
    ap.add_argument("step", type=int, choices=range(1, 7))
    ap.add_argument("--yes", action="store_true", help="the person said yes to the paid steps (4, 6)")
    a = ap.parse_args()
    if a.step in (4, 6) and not a.yes:
        raise SystemExit("steps 4 and 6 are paid: add --yes (the person's yes, cap $1.50)")
    [step1, step2, step3, step4, step5, step6][a.step - 1]()


if __name__ == "__main__":
    main()
