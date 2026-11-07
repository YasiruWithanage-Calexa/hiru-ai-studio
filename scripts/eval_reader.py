"""The document reader's accuracy test (plan/2026-11-06f §5, Phase 5): the reader against the rules, on the gold.

    python scripts/eval_reader.py                       # offline: the rules, and the gold replayed through the reader
                                                        # (checks the scoring and the plumbing; no model call)
    python scripts/eval_reader.py --yes                 # live: the reader on each gold file's PDF (costs money)
    python scripts/eval_reader.py --yes --gold ekama-sakshiya --pdf-dir ~/Downloads

It refuses to call the model without `--yes` (a person starts it: the plan's rule and the project's). For each gold file
in `tests/eval/reader/gold/` it extracts the PDF with the doc_ingest function's own code, reads it with the rules (the
baseline) and, live, with the reader (`READER` tier: OPENAI__MODEL_AUTHOR at OPENAI__EFFORT_READER), and prints a table
of scores (`tests/eval/reader/score.py`) with the tokens each live run used. It writes the reading it got to
`tests/eval/reader/runs/<gold>.json` so a person can read it. Nothing is written to a database.

The gold is a draft until a Hiru writer has checked it (§5); Avasana's three episodes wait for a person to type their
Sinhala (plan Q4).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src" / "libs", ROOT / "src" / "services" / "doc_ingest", ROOT):
    sys.path.insert(0, str(p))

from tests.eval.reader import score  # noqa: E402

from contracts.doc_read import PieceRead, Reading, to_parsed  # noqa: E402
from contracts.doc_read_run import Calls, read_document  # noqa: E402
from contracts.screenplay import parse_document  # noqa: E402

GOLD = ROOT / "tests" / "eval" / "reader" / "gold"
RUNS = ROOT / "tests" / "eval" / "reader" / "runs"


def extract(pdf: Path) -> str:
    from doc_ingest.engine.extract import extract as run_extract
    from doc_ingest.engine.pipeline import paged_text

    return paged_text(run_extract(pdf.read_bytes(), pdf.name, "application/pdf"))


def replay(answer: dict[str, Any]) -> Calls:
    """The gold answer as the model's: checks that the run, the checks and the mapping keep a correct answer whole."""
    def no(ask: Any) -> Any:
        raise RuntimeError("the replay has no answer for this call")

    return Calls(canon=no, piece=lambda ask: PieceRead.model_validate(answer), repair=no)


def live(rows: list[dict[str, Any]]) -> Calls:
    from doc_ingest.engine import reader
    from doc_ingest.runtime.config import get_config
    from doc_ingest.runtime.llm import LLM

    llm = LLM(get_config(), on_usage=rows.append)
    if not llm.enabled:
        raise SystemExit("OPENAI__API_KEY is not set")
    return reader.calls(llm, None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="call the real model (costs money)")
    ap.add_argument("--gold", help="one gold file (its name without .json)")
    ap.add_argument("--pdf-dir", default=str(Path.home() / "Downloads"), help="where the gold files' PDFs are")
    args = ap.parse_args()
    results: dict[str, dict[str, float]] = {}
    for path in sorted(GOLD.glob("*.json")):
        if args.gold and path.stem != args.gold:
            continue
        gold = json.loads(path.read_text(encoding="utf-8"))
        pdf = Path(os.path.expanduser(args.pdf_dir)) / gold["file"]
        if not pdf.exists():
            print(f"{path.stem}: {pdf} not found; skipped")
            continue
        text = extract(pdf)
        want = to_parsed(Reading(episodes=gold["answer"]["episodes"]))
        names, aliases = score.gold_names(gold["answer"])

        def scored(got: Any, canon: list[str], names: list[str] = names,
                   aliases: dict[str, set[str]] = aliases, want: Any = want) -> dict[str, float]:
            return score.score(want, got, aliases=aliases, gold_canon=names, got_canon=canon)

        rules_doc = parse_document(text, pdf.name)
        speakers = sorted({sp for s in rules_doc.scenes for sp in s.speakers})
        places = sorted({s.heading.location for s in rules_doc.scenes if s.heading.location})
        results[f"{path.stem} rules"] = scored(rules_doc, speakers + places)
        rows: list[dict[str, Any]] = []
        calls = live(rows) if args.yes else replay(gold["answer"])
        started = time.monotonic()
        out = read_document(pdf.name, "script", text, calls)
        arm = "reader" if args.yes else "gold replayed"
        if out.reading is None:
            print(f"{path.stem} {arm}: no reading ({out.reason})")
            continue
        r = out.reading
        canon = [n for e in [*r.canon.characters, *r.canon.locations, *r.canon.props] for n in [e.name, *e.aliases]]
        results[f"{path.stem} {arm}"] = scored(to_parsed(r), canon)
        if args.yes:
            RUNS.mkdir(parents=True, exist_ok=True)
            (RUNS / f"{path.stem}.json").write_text(r.dumps(), encoding="utf-8")
            tokens = {k: sum(int(x.get(k, 0)) for x in rows) for k in ("input_tokens", "cached_input_tokens",
                                                                         "output_tokens")}
            print(f"{path.stem}: {out.calls} calls, {time.monotonic() - started:.0f} s, {tokens}, "
                  f"{len(r.unresolved)} problems left, {len(r.notes)} notes")
    print(score.table(results))


if __name__ == "__main__":
    main()
