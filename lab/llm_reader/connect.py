"""Point 5 (2026-11-15): does the new reading feed the build steps that exist today? NOTHING is written to the database.

    poppler text (what the server will run)
      -> the new reading: probe + read (run.py's calls, cached) -> checks -> gates; only "go" goes on
      -> contracts.breakdown.run.create(), the REAL pipeline with the REAL agents:
           split      breakdown_split runs as today (people, places, things, direction rules); its scene cuts are
                      REPLACED by the new reading's (heading line, last line), as the product change would do
           continuity breakdown_continuity, as today
           episode    breakdown_episode, as today: blocks, dialogue, speakers, places
      -> the new reading's heading text, document title and length (top of a range) put on the scenes, in place of
         build.py:97's whole line and fill.py's `_MINUTES` pattern (the product change, simulated here)
      -> fill.structure() and structure_build's write.plan(): the scene and dialogue rows the database would get
      -> code checks the rows: 13 scenes, headings, titles, lengths, and every spoken line copied exactly from the PDF

    python lab/llm_reader/connect.py dry
    python lab/llm_reader/connect.py live <run> --yes      # PAID: the lab's $2.00 cap (runs/ledger.csv)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "structure_build"),
                str(ROOT / "lab")]

import checks  # noqa: E402
import run as lab  # noqa: E402
from contracts.breakdown import fill  # noqa: E402
from contracts.breakdown import run as brun  # noqa: E402
from contracts.breakdown.schema import EpisodeCutW, SceneCutW, SplitW  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402
from schema import Answer, Probe  # noqa: E402

STEM = "B_v2_pdf"  # the reading's cache key: the same document name and text as run.py's B
POPPLER = HERE / "runs" / "readers" / "poppler_Api_Denna_Script_v2.txt"
WORST_OUT = {"split": 16_000, "continuity": 16_000, "episode": 32_000, "repair": 10_000}


def poppler_lines() -> list[str]:
    """One entry per printed line, spacing collapsed: exactly what the product's extractor would hand on."""
    raw = POPPLER.read_text(encoding="utf-8").replace("\f", "\n")
    return [ln for ln in (" ".join(x.split()) for x in raw.split("\n")) if ln]


def agent_call(run: str, slot: str, agent_id: str, message: str) -> Any:
    """A product agent, run as the product runs it, under the lab's cap and ledger."""
    from hiru_ai.core import agents
    from hiru_ai.core.context import RunContext

    agent = agents.build(agent_id)
    worst = (tokens_of(agent.prompt.text) + tokens_of(message)) * lab.PRICE[0] / 1e6 + WORST_OUT[slot] * lab.PRICE[2] / 1e6
    if lab.spent() + worst > lab.LAB_CAP_USD + 1e-9:
        raise lab.CapError(f"Refused {slot}: ${lab.spent():.4f} spent; it could cost ${worst:.4f}; cap ${lab.LAB_CAP_USD:.2f}")
    usage: list[dict[str, Any]] = []
    started = time.time()
    base = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run, "slot": f"connect/{slot}", "effort": "agent"}
    try:
        got = agent.run({"message": message}, RunContext(usage_sink=usage.append))
    except Exception as exc:
        lab._enter({**base, "dollars": f"{worst:.4f}", "status": f"failed, worst case entered: {type(exc).__name__}"})
        raise
    i = sum(int(u.get("input_tokens") or 0) for u in usage)
    c = sum(int(u.get("cached_input_tokens") or 0) for u in usage)
    o = sum(int(u.get("output_tokens") or 0) for u in usage)
    dollars = (i - c) * lab.PRICE[0] / 1e6 + c * lab.PRICE[1] / 1e6 + o * lab.PRICE[2] / 1e6 if usage else worst
    model = str((usage[0] if usage else {}).get("model") or "")
    lab._enter({**base, "model": model, "input_tokens": i, "cached_tokens": c, "output_tokens": o,
                "dollars": f"{dollars:.4f}", "status": "done"})
    print(f"  {slot:<10} {model:<14} {time.time() - started:5.0f} s  in {i:>6}  out {o:>6}  ${dollars:.4f}", flush=True)
    out = HERE / "runs" / run / "calls"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{len(list(out.iterdir())):02d}_{slot}.json").write_text(
        json.dumps({"message": message, "answer": got.model_dump(mode="json")}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return got


def cuts(a: Answer) -> list[EpisodeCutW]:
    """The new reading's scenes as the split's cuts: heading line and last line (word-level ends become lines here;
    a boundary inside a line would need that line split first, which this text does not have)."""
    eps: dict[int, EpisodeCutW] = {}
    heads = {e.number: e.heading.line for e in a.episodes}
    for s in a.scenes:
        if s.heading.line == s.end.line or any(o.end.line == s.heading.line for o in a.scenes if o is not s):
            raise SystemExit(f"{checks.tag(s)}: a boundary inside a line; split the line first (not in this text)")
        ep = eps.setdefault(s.episode, EpisodeCutW(number=s.episode, heading=heads.get(s.episode, s.heading.line),
                                                   scenes=[]))
        ep.scenes.append(SceneCutW(number=s.number, heading=s.heading.line, last=s.end.line))
    return [eps[k] for k in sorted(eps)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "live"])
    ap.add_argument("run", nargs="?", default="connect_dry")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()

    lines = poppler_lines()
    user = lab.numbered(STEM, lines)
    from hiru_ai.core import agents

    split_msg = brun.split_message("Api_Denna_Script_v2.pdf", brun.Doc(lines))
    split_in = tokens_of(agents.build("breakdown_split").prompt.text) + tokens_of(split_msg)
    print(f"{len(lines)} poppler lines; split ~{split_in} tokens in; lab spent ${lab.spent():.4f} of ${lab.LAB_CAP_USD:.2f}")
    if a.mode == "dry":
        return
    if not a.yes:
        raise SystemExit("A live run is paid: add --yes only after the person said yes.")
    out = HERE / "runs" / a.run
    out.mkdir(parents=True, exist_ok=True)

    # 1. the new reading and its gates
    probe = Probe.model_validate_json(lab.call(a.run, f"{STEM}/probe", "probe", lab.prompt("probe.md"), user, Probe))
    reading = Answer.model_validate_json(lab.call(a.run, f"{STEM}/read", "read", lab.prompt("system.md"), user, Answer))
    result = checks.Result(checks.check(reading, lines), checks.gates(reading, lines))
    print(f"reading: {len(reading.scenes)} scenes, probe readable={probe.text_quality.readable}, verdict {result.verdict}")
    if result.verdict != "go":
        raise SystemExit(f"the gates hold the build: {[g.message for g in result.gates]}")

    # 2. the real pipeline, the split's scene cuts replaced by the reading's
    def split(m: str) -> SplitW:
        got = agent_call(a.run, "split", "breakdown_split", m)
        (out / "split_own_cuts.json").write_text(json.dumps([e.model_dump() for e in got.episodes], indent=1),
                                                 encoding="utf-8")
        return got.model_copy(update={"episodes": cuts(reading)})

    calls = brun.Calls(split=split,
                       continuity=lambda m: agent_call(a.run, "continuity", "breakdown_continuity", m),
                       episode=lambda m: agent_call(a.run, "episode", "breakdown_episode", m),
                       repair=lambda m: agent_call(a.run, "repair", "breakdown_repair", m))
    upload = brun.Upload(document_id="lab-v2", filename="Api_Denna_Script_v2.pdf", text="\n".join(lines))
    res = brun.create([upload], calls, production="lab", workers=1, progress=lambda t: print(f"  > {t}", flush=True))
    if res.memory is None:
        raise SystemExit(f"no memory: {res.failed} {res.notes}")
    bd = res.memory

    # 3. the reading's heading, title and length on the scenes (the product change, simulated)
    by_key = {(s.episode, s.number): s for s in reading.scenes}
    structure = fill.structure(bd)
    for ep in structure["episodes"]:
        for row in ep["scenes"]:
            r = by_key[(ep["number"], row["number"])]
            row["heading"]["raw"] = r.heading.quote
            row["title"] = r.title
            row["envelope_s"] = round(checks.envelope(r))
    from structure_build.engine import write

    wp = write.plan(structure, production_id="lab", canon=[], existing_episodes=[], existing_scenes=[], envelope_s=60,
                    aspect_ratio="16:9", actor=None)

    # 4. code checks the rows
    whole = " ".join(lines)
    rows, problems = [], []
    for scene, dl in wp.scenes:
        key = next(k for k, v in by_key.items() if v.heading.quote == scene["heading"])
        exp = round(checks.envelope(by_key[key]))
        if scene["envelope_s"] != exp:
            problems.append(f"E{key[0]:02d} S{key[1]:02d}: envelope {scene['envelope_s']} s, expected {exp}")
        for d in dl:
            if " ".join(d["text"].split()) not in whole:
                problems.append(f"E{key[0]:02d} S{key[1]:02d}: spoken line not in the PDF text: {d['text']!r}")
            if checks.misplaced_signs(d["text"]):
                problems.append(f"E{key[0]:02d} S{key[1]:02d}: damaged Sinhala in {d['text']!r}")
        rows.append((key, scene, dl))
    if len(wp.scenes) != len(reading.scenes):
        problems.append(f"{len(wp.scenes)} scene rows for {len(reading.scenes)} scenes read")
    (out / "rows.json").write_text(json.dumps([{"scene": s, "dialogue_lines": d} for _, s, d in rows],
                                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "findings.json").write_text(json.dumps([f.model_dump() for f in bd.findings], indent=1), encoding="utf-8")

    rep = [f"# Point 5: the new reading through today's build · {a.run} · {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"Text: poppler ({len(lines)} lines). Reading verdict: {result.verdict}. Breakdown notes: "
           f"{'; '.join(res.notes) or 'none'}. Blocking findings: {sum(f.blocking for f in bd.findings)}.", "",
           f"**Checks on the rows: {'all passed' if not problems else f'{len(problems)} problems'}**", ""]
    rep += [f"- {p}" for p in problems]
    rep += ["", "| scene | heading (row) | title (row) | envelope_s | blocks | spoken lines | first spoken line |",
            "|---|---|---|---|---|---|---|"]
    for (e, n), s, dl in rows:
        first = f"{dl[0]['speaker']}: {dl[0]['text']}" if dl else "—"
        rep.append(f"| E{e:02d} S{n:02d} | {s['heading']} | {s['title']} | {s['envelope_s']} | {len(s['script'])} | "
                   f"{len(dl)} | {first} |")
    rep += ["", "## Every spoken line, as the database would store it", ""]
    for (e, n), _s, dl in rows:
        rep += [f"**E{e:02d} S{n:02d}**", ""] + [f"- {d['speaker']}: {d['text']}" for d in dl] + [""]
    rep.append(f"Lab spent ${lab.spent():.4f} of ${lab.LAB_CAP_USD:.2f}.")
    (out / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"report: {out / 'report.md'}; {len(problems)} problems; lab spent ${lab.spent():.4f}")


if __name__ == "__main__":
    main()
