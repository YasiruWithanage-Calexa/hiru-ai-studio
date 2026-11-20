"""Free: read every lab take's audio and compare the real speech time with the clock's estimate.

    .venv/Scripts/python.exe lab/sinhala_pace/measure.py

Writes runs/results.json and prints one row per take: words, syllables, the clock's seconds, the measured span (first to
last speech), voiced time (pauses over 0.3 s taken out), and the rates that span gives in words/s and syllables/s.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pace  # noqa: E402


def main() -> int:
    rows = []
    for folder in sorted((HERE / "runs").glob("*_*_*")):
        take = folder / "take.mp4"
        if not take.exists():
            continue
        line = json.loads((folder / "line.json").read_text(encoding="utf-8"))
        span = pace.speech_span(take, float(line["take_s"]))
        c, syl = line["clock"], line["syllables"]["total"]
        row = {"lab_id": line["lab_id"], "words": c["words"], "syllables": syl, "clock_said_s": c["said_s"],
               "clock_need_s": c["need_s"], "take_s": line["take_s"], "delivery": line["delivery"],
               "text": line["text"]}
        if span:
            row.update({"start_s": span.start_s, "end_s": span.end_s, "span_s": span.span_s,
                        "voiced_s": span.voiced_s, "pauses": span.pauses, "cut": span.cut,
                        "floor_db": span.floor_db, "threshold_db": span.threshold_db,
                        "words_per_s": round(c["words"] / span.span_s, 2) if span.span_s else None,
                        "syl_per_s": round(syl / span.span_s, 2) if span.span_s else None,
                        "vs_clock": round(span.span_s / c["said_s"], 2) if c["said_s"] else None})
        rows.append(row)
        if span:
            print(f"{row['lab_id']}: {row['words']:>2} w {syl:>3} syl | clock {c['said_s']:>5} s | heard "
                  f"{span.start_s:>5}-{span.end_s:<5} = {span.span_s:>5} s (voiced {span.voiced_s}, {span.pauses} "
                  f"pauses) | {row['words_per_s']} w/s, {row['syl_per_s']} syl/s | x{row['vs_clock']} the clock"
                  f"{'  CUT?' if span.cut else ''}")
        else:
            print(f"{row['lab_id']}: no speech found")
    (HERE / "runs" / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    spans = [r for r in rows if r.get("span_s")]
    if spans:
        w = sum(r["words"] for r in spans) / sum(r["span_s"] for r in spans)
        s = sum(r["syllables"] for r in spans) / sum(r["span_s"] for r in spans)
        print(f"overall: {w:.2f} words/s, {s:.2f} syllables/s over {len(spans)} take(s) (the clock uses 2.2 words/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
