"""Phase 0 of plan/2026-11-06f: what does OpenAI accept as a PDF, and what does a page image cost?

    python scripts/reader_probe.py                        # says what it would send; no model call
    python scripts/reader_probe.py --yes                  # ONE call: Ekama's 4 pages as a PDF, read in pages mode
    python scripts/reader_probe.py --yes --pdf other.pdf --pages 1-6

It refuses to call the model without `--yes` (a person starts it). The call is the reader's own episode call
(`reader_episode`'s prompt and schema, the `reader` tier: OPENAI__MODEL_AUTHOR at OPENAI__EFFORT_READER) with the pages
attached as a Chat Completions `file` part and no text, the way a scrambled document is read. It prints the size sent,
the tokens the call used (the input tokens are the page images and their text), the time, whether the answer was cut,
and how many scenes, lines and transcribed pages came back, and keeps the answer in `tests/eval/reader/runs/probe.json`.
Those numbers go in IMPLEMENTED.md (costs never go in the interface). The limits to confirm: pages and bytes per
request (believed ~100 pages / 32 MB per file).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src" / "libs", ROOT / "src" / "services" / "doc_ingest"):
    sys.path.insert(0, str(p))

from contracts.doc_read import PieceRead, strict_schema  # noqa: E402
from contracts.doc_read_run import PieceAsk, piece_message  # noqa: E402

RUNS = ROOT / "tests" / "eval" / "reader" / "runs"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="make the one call (costs money)")
    ap.add_argument("--pdf", default=str(Path.home() / "Downloads" / "ekama_sakshiya_screenplay.pdf"))
    ap.add_argument("--pages", default="1-4", help="first-last, 1-based")
    args = ap.parse_args()

    from doc_ingest.engine import reader

    first, last = (int(x) for x in args.pages.split("-"))
    data = Path(args.pdf).read_bytes()
    piece = reader.pdf_slicer(lambda: data)(first, last)
    ask = PieceAsk(filename=Path(args.pdf).name, mode="pages", kind="whole", episode=0, title="", first_page=first,
                   last_page=last, first_line=1, last_line=1, text="", pdf_b64=base64.b64encode(piece).decode("ascii"),
                   roster="(none yet)")
    print(f"pages {first}-{last} of {Path(args.pdf).name}: {len(piece):,} bytes as a PDF")
    if not args.yes:
        print("not sent: add --yes to make the one call")
        return

    from doc_ingest.runtime.config import get_config
    from doc_ingest.runtime.llm import LLM

    rows: list[dict[str, Any]] = []
    llm = LLM(get_config(), on_usage=rows.append)
    if not llm.enabled:
        raise SystemExit("OPENAI__API_KEY is not set")
    started = time.monotonic()
    try:
        raw = llm.json(tier="reader", phase="doc_ingest.reader.probe", system=reader.system("reader_episode"),
                       user=piece_message(ask), schema_name="PieceRead", schema=strict_schema(PieceRead),
                       files=[(f"pages-{first}-{last}.pdf", ask.pdf_b64)])
    except Exception as exc:  # the limit or the refusal is the finding
        print(f"refused or failed after {time.monotonic() - started:.0f} s: {type(exc).__name__}: {exc}")
        print(json.dumps(rows))
        return
    answer = PieceRead.model_validate(raw)
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "probe.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    scenes = [s for e in answer.episodes for s in e.scenes]
    lines = sum(1 for s in scenes for b in s.blocks if b.kind == "dialogue")
    print(f"{time.monotonic() - started:.0f} s; usage {json.dumps(rows)}")
    print(f"{len(scenes)} scenes, {lines} spoken lines, {len(answer.canon.characters)} people, "
          f"{len(answer.transcription)} pages transcribed")


if __name__ == "__main__":
    main()
