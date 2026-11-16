"""LLM reader lab (2026-11-15): the model reads every fact from an uploaded document; code only checks its answers and
applies the gates. NOTHING is written to the database: the result is files and a report.

Per document:
  0+1 probe      one cheap call: what it is, and is the text damaged?        -> Stop when it is not a story
  0b  transcribe damaged text + a PDF: the model reads the printed pages     -> checked; Stop when damaged and no PDF
  2-4 read       one call: episodes, scenes (word-level start/end), lengths, places, people -> checked, one repair
      gates      Stop / Needs input / Warn; any scene's problem holds the whole build

    python lab/llm_reader/make_inputs.py                       # free: documents + expected answers
    python lab/llm_reader/run.py dry  [run]                    # free: request sizes
    python lab/llm_reader/run.py live <run> --yes [--only A,B] # PAID, cap $2.00 (runs/ledger.csv)
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import checks  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402
from make_inputs import DOWNLOADS, PDFS  # noqa: E402
from schema import Answer, Probe, Transcription, json_schema  # noqa: E402

LAB_CAP_USD = 2.00
MODEL = "gpt-6.1-sol"
PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output (as lab/two_memories/paid.py)
PAGE_TOKENS = 3000  # worst-case input tokens per attached PDF page
PAGES_PER_CALL = 7
STEPS = {  # step: (effort, max output tokens)
    "probe": ("low", 6000),
    "transcribe": ("low", 24000),
    "read": ("medium", 20000),
}
RUNS = HERE / "runs"
INPUTS = HERE / "inputs"
LEDGER = RUNS / "ledger.csv"
FIELDS = ["time", "run", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "dollars", "status"]


class CapError(Exception):
    pass


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def _enter(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def call(run: str, slot: str, step: str, system: str, user: str, out: type[BaseModel],
         pdf: tuple[str, bytes, int] | None = None) -> str:
    """One model call, cached by its request. `pdf`: (filename, bytes, pages) attached as a file."""
    effort, max_out = STEPS[step]
    schema = json_schema(out)
    pdf_hash = hashlib.sha256(pdf[1]).hexdigest() if pdf else ""
    key = hashlib.sha256(json.dumps([system, user, schema, MODEL, effort, pdf_hash], sort_keys=True).encode()).hexdigest()[:24]
    cached = RUNS / "cache" / f"{key}.json"
    if cached.exists():
        print(f"  {slot}: from the cache (no cost)")
        return cached.read_text(encoding="utf-8")
    tin = tokens_of(system) + tokens_of(user) + (pdf[2] * PAGE_TOKENS if pdf else 0)
    worst = tin * PRICE[0] / 1e6 + max_out * PRICE[2] / 1e6
    if spent() + worst > LAB_CAP_USD + 1e-9:
        raise CapError(f"Refused: ${spent():.4f} spent; this call could cost ${worst:.4f}; the cap is ${LAB_CAP_USD:.2f}.")
    from cinematic.run import client  # the only place a client is built; it reads .env

    content: Any = user
    if pdf:
        content = [{"role": "user", "content": [
            {"type": "input_text", "text": user},
            {"type": "input_file", "filename": pdf[0],
             "file_data": "data:application/pdf;base64," + base64.b64encode(pdf[1]).decode()}]}]
    base = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run, "slot": slot, "model": MODEL, "effort": effort}
    print(f"  {slot}: calling {MODEL} ({effort}), worst case ${worst:.4f} ...", flush=True)
    started = time.time()
    try:
        resp = client().responses.create(
            model=MODEL, instructions=system, input=content, max_output_tokens=max_out, reasoning={"effort": effort},
            text={"format": {"type": "json_schema", "name": out.__name__.lower(), "schema": schema, "strict": True}})
    except Exception as exc:
        _enter({**base, "dollars": f"{worst:.4f}", "status": f"failed, worst case entered: {type(exc).__name__}"})
        raise
    u = getattr(resp, "usage", None)
    if u is None:
        dollars, usage = worst, {}
    else:
        c = int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0)
        i, o = int(u.input_tokens or 0), int(u.output_tokens or 0)
        dollars = (i - c) * PRICE[0] / 1e6 + c * PRICE[1] / 1e6 + o * PRICE[2] / 1e6
        usage = {"input_tokens": i, "cached_tokens": c, "output_tokens": o}
    status = "done" if getattr(resp, "status", "completed") == "completed" else f"cut off ({resp.status})"
    _enter({**base, "dollars": f"{dollars:.4f}", "status": status, **usage})
    print(f"  {slot}: {status} in {time.time() - started:.0f} s, ${dollars:.4f} {usage}")
    text = str(getattr(resp, "output_text", "") or "")
    if status != "done":
        raise CapError(f"The answer was {status}; not cached. ${dollars:.4f} entered.")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


def prompt(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8").strip()


def numbered(name: str, lines: list[str]) -> str:
    body = "\n".join(f"L{i:04d} | {ln}" for i, ln in enumerate(lines, 1))
    return f"DOCUMENT: {name} ({len(lines)} lines)\n\n{body}\n"


def pdf_pages(path: Path, first: int, last: int) -> bytes:
    from pypdf import PdfReader, PdfWriter  # as hiru_ai.core.doc_reader cuts pages

    src, w = PdfReader(str(path)), PdfWriter()
    for n in range(first, last + 1):
        w.add_page(src.pages[n - 1])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def transcribe(run: str, stem: str, notes: list[str]) -> list[str] | None:
    """The printed pages, read by the model, checked by code. None when it cannot be trusted (the build stops)."""
    pdf = DOWNLOADS / PDFS[stem]
    layer = {int(k): v for k, v in json.loads((INPUTS / f"{stem}.pages.json").read_text(encoding="utf-8")).items()}
    pages = sorted(layer)
    lines: list[str] = []
    for i in range(0, len(pages), PAGES_PER_CALL):
        first, last = pages[i], pages[min(i + PAGES_PER_CALL, len(pages)) - 1]
        user = (f"The attached file holds pages {first} to {last} of {PDFS[stem]}. Number them {first} to {last}. "
                "Transcribe every printed line.")
        part = {n: layer[n] for n in range(first, last + 1)}
        blob = pdf_pages(pdf, first, last)
        t = Transcription.model_validate_json(call(run, f"{stem}/transcribe p{first}-{last}", "transcribe",
                                                   prompt("transcribe.md"), user, Transcription, (PDFS[stem], blob, len(part))))
        found = checks.transcription_check(t, part, first)
        if found:
            for f in found:
                print(f"    - {f.message}")
            retry = user + "\n\nAN EARLIER TRANSCRIPTION OF THESE PAGES FAILED CODE'S CHECKS:\n" + "\n".join(
                f"- {f.message}" for f in found) + "\nTranscribe them again, fixing exactly that."
            t = Transcription.model_validate_json(call(run, f"{stem}/transcribe p{first}-{last} again", "transcribe",
                                                       prompt("transcribe.md"), retry, Transcription,
                                                       (PDFS[stem], blob, len(part))))
            found = checks.transcription_check(t, part, first)
        notes += [f"transcription p{first}-{last}: {f.message}" for f in found]
        if found:
            return None
        lines += [ln for p in sorted(t.pages, key=lambda p: p.page) for ln in p.lines]
    return lines


def report(name: str, gold: dict, a: Answer | None, probe: Probe, result: checks.Result, repaired: bool,
           notes: list[str], read_from: str) -> str:
    out = [f"## {name}", "", f"_{gold['note']}_", ""]
    rows = checks.score(a, gold, result.verdict) if a else [
        ("kind", (probe.kind in ("story_script", "story_prose")) == gold["story"], probe.kind),
        ("verdict", result.verdict == gold["verdict"], f"{result.verdict} (expected {gold['verdict']})")]
    rows.insert(2, ("damaged text seen", (not probe.text_quality.readable) == gold["damaged_text"],
                    f"readable={probe.text_quality.readable}"))
    passed = sum(ok for _, ok, _ in rows)
    out += [f"**Verdict: {result.verdict.upper()}** (expected {gold['verdict']}) · scored {passed}/{len(rows)} · read "
            f"from: {read_from} · findings left: {len(result.findings)}{' after one repair' if repaired else ''}", "",
            "| what | ok | detail |", "|---|---|---|"]
    out += [f"| {w} | {'yes' if ok else '**NO**'} | {d} |" for w, ok, d in rows]
    out += ["", "**Gates**", ""] + ([f"- `{g.level}` gate {g.gate}: {g.message}" for g in result.gates] or ["- none"])
    if result.findings:
        out += ["", "**Check findings left**", ""] + [f"- `{f.code}` {f.message}" for f in result.findings]
    if notes:
        out += ["", "**Notes**", ""] + [f"- {n}" for n in notes]
    out += ["", f"**Probe:** {probe.kind}; readable={probe.text_quality.readable}"]
    out += [f"- L{p.where.line} `{p.where.quote}`: {p.what}" for p in probe.text_quality.problems]
    if a and a.scenes:
        out += ["", "| scene | starts (model's quote) | ends | title | place | envelope | from the words |",
                "|---|---|---|---|---|---|---|"]
        for s in a.scenes:
            env = checks.envelope(s)
            place = f"{s.place}{' (← ' + s.place_source.quote + ')' if s.place_refers_back else ''}"
            out.append(f"| {checks.tag(s)} | {s.heading.quote} (L{s.heading.line}) | …{s.end.quote[-30:]} (L{s.end.line}) | "
                       f"{s.title} | {place} | {f'{env:g} s' if env else '—'} | {s.length.source.quote or '—'} |")
        out += ["", "**People:** " + "; ".join(f"{p.name} ({p.role})" for p in a.people)]
        out += ["", "**Doubts:**"] + ([f"- {d}" for d in a.doubts] or ["- none"])
    return "\n".join(out) + "\n"


def run_doc(run: str, d: Path, *, repair: bool) -> tuple[str, dict]:
    stem = d.stem
    lines = d.read_text(encoding="utf-8").rstrip("\n").split("\n")
    gold = json.loads((HERE / "gold" / f"{stem}.json").read_text(encoding="utf-8"))
    print(f"{stem}:")
    notes: list[str] = []
    probe = Probe.model_validate_json(call(run, f"{stem}/probe", "probe", prompt("probe.md"), numbered(stem, lines), Probe))
    print(f"  probe: {probe.kind}, readable={probe.text_quality.readable}")
    result = checks.Result()
    if probe.kind not in ("story_script", "story_prose"):
        result.gates.append(checks.Gate("stop", "1 kind", f"not a story to build from: {probe.kind} ({probe.kind_why})"))
        return report(stem, gold, None, probe, result, False, notes, "—"), {"verdict": result.verdict}
    read_from = "text layer"
    if not probe.text_quality.readable:
        if stem not in PDFS:
            result.gates.append(checks.Gate("stop", "0 file", "the text is damaged and there is no PDF to read the "
                                                              "printed pages from"))
            return report(stem, gold, None, probe, result, False, notes, "—"), {"verdict": result.verdict}
        clean = transcribe(run, stem, notes)
        if clean is None:
            result.gates.append(checks.Gate("stop", "0 file", "the printed pages could not be transcribed reliably"))
            return report(stem, gold, None, probe, result, False, notes, "—"), {"verdict": result.verdict}
        (INPUTS / f"{stem}.clean.txt").write_text("\n".join(clean) + "\n", encoding="utf-8")
        lines, read_from = clean, f"printed pages ({len(clean)} lines)"
        result.gates.append(checks.Gate("warn", "0 file", "the text layer is damaged; read from the printed pages"))
    user = numbered(stem, lines)
    a = Answer.model_validate_json(call(run, f"{stem}/read", "read", prompt("system.md"), user, Answer))
    found = checks.check(a, lines)
    print(f"  checks: {len(found)} findings")
    repaired = False
    if found and repair:
        for f in found[:8]:
            print(f"    - {f.message}")
        fix = (f"{user}\n\nYOUR EARLIER ANSWER\n{a.model_dump_json()}\n\nCODE CHECKED IT AND FOUND\n"
               + "\n".join(f"- {f.message}" for f in found)
               + "\n\nAnswer again, whole. Fix what the checks say if they are right; if a check is wrong about the "
                 "document, keep your reading and say why in `doubts`.")
        a = Answer.model_validate_json(call(run, f"{stem}/repair", "read", prompt("system.md"), fix, Answer))
        found, repaired = checks.check(a, lines), True
        print(f"  after repair: {len(found)} findings")
    result.findings = found
    result.gates += checks.gates(a, lines)
    (RUNS / run / f"{stem}.answer.json").write_text(a.model_dump_json(indent=1), encoding="utf-8")
    return report(stem, gold, a, probe, result, repaired, notes, read_from), {"verdict": result.verdict}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "live"])
    ap.add_argument("run", nargs="?", default="dry")
    ap.add_argument("--only", default="", help="comma-separated document letters, e.g. A,B")
    ap.add_argument("--yes", action="store_true", help="the person said yes to this paid run")
    ap.add_argument("--no-repair", action="store_true")
    a = ap.parse_args()

    docs = sorted(p for p in INPUTS.glob("*.txt") if p.stem.count(".") == 0)
    if a.only:
        docs = [d for d in docs if d.stem.split("_")[0] in a.only.split(",")]
    for d in docs:
        n = tokens_of(d.read_text(encoding="utf-8"))
        print(f"{d.stem}: ~{n} document tokens{' + PDF pages if damaged' if d.stem in PDFS else ''}")
    print(f"lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")
    if a.mode == "dry":
        return
    if not a.yes:
        raise SystemExit("A live run is paid: add --yes only after the person said yes.")
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    parts, summary = [], ["| document | verdict | expected |", "|---|---|---|"]
    for d in docs:
        try:
            text, res = run_doc(a.run, d, repair=not a.no_repair)
        except CapError as exc:
            print(f"  stopped: {exc}")
            break
        gold = json.loads((HERE / "gold" / f"{d.stem}.json").read_text(encoding="utf-8"))
        summary.append(f"| {d.stem} | {res['verdict']} | {gold['verdict']} |")
        parts.append(text)
    head = [f"# LLM reader lab · {a.run} · {time.strftime('%Y-%m-%d %H:%M')}", "",
            f"Model {MODEL}: probe ({STEPS['probe'][0]}), transcribe ({STEPS['transcribe'][0]}), read "
            f"({STEPS['read'][0]}). Code reads only the answers.", ""]
    text = "\n".join(head + summary + [""] + parts) + f"\nLab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}.\n"
    (RUNS / a.run / "report.md").write_text(text, encoding="utf-8")
    print(f"report: {RUNS / a.run / 'report.md'}; lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")


if __name__ == "__main__":
    main()
