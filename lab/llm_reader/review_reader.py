"""A side-by-side review of a PDF reader's Sinhala against today's extractor (free, no model).

    python lab/llm_reader/review_reader.py <reader name> <out.md> <pdf>=<reader output .txt> [...]

Lists every line holding Sinhala: today's pypdf text, the reader's text, what changed (letters compared after Unicode
decomposition), and an empty column for the person to mark.
"""

from __future__ import annotations

import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "doc_ingest")]

import checks  # noqa: E402
from doc_ingest.engine.extract import extract  # noqa: E402


def letters(s: str) -> Counter[str]:
    return Counter(c for c in unicodedata.normalize("NFD", s) if 0x0D80 <= ord(c) <= 0x0DFF)


def has_sinhala(s: str) -> bool:
    return any(0x0D80 <= ord(c) <= 0x0DFF for c in s)


def main() -> None:
    name, out_path, pairs = sys.argv[1], Path(sys.argv[2]), [a.split("=", 1) for a in sys.argv[3:]]
    out = [f"# Sinhala check: {name} vs today's extractor (pypdf)", "",
           f"{name} is a PDF engine that honours the text the PDF stores for each Sinhala cluster (`/ActualText`). "
           "No model is involved.",
           "Every line holding Sinhala is listed, for each PDF. Please compare the **" + name + "** column with the PDF "
           "as you see it and mark the last column.", "",
           "`what changed` compares the letters after Unicode decomposition (NFD): *reordered only* = the same letters "
           "in the right order; *letters restored* = letters today's extractor lost.", ""]
    for pdf, txt in pairs:
        old = [ln.text for ln in extract(Path(pdf).read_bytes(), Path(pdf).name, "application/pdf").lines]
        new = [" ".join(ln.split()) for ln in Path(txt).read_text(encoding="utf-8").split("\n")
               if ln.strip() and ln.strip() != "\f"]
        rows, counts = [], Counter()
        for i, (x, y) in enumerate(zip(old, new, strict=False), 1):
            if not (has_sinhala(x) or has_sinhala(y)):
                continue
            if " ".join(x.split()) == y:
                kind = "unchanged"
            elif letters(x) == letters(y):
                kind = "reordered only"
            else:
                added, lost = letters(y) - letters(x), letters(x) - letters(y)
                kind = "letters restored: +" + ("".join(sorted(added.elements())) or "-") + (
                    " / -" + "".join(sorted(lost.elements())) if lost else "")
            counts[kind.split(":")[0]] += 1
            rows.append(f"| {i} | {x.strip()} | {y} | {kind} | |")
        out += [f"## {Path(pdf).name}", "",
                f"Lines: today {len(old)}, {name} {len(new)}. Lines with Sinhala: {len(rows)} "
                f"({counts['unchanged']} unchanged, {counts['reordered only']} reordered only, "
                f"{counts['letters restored']} with letters restored). Words with a vowel sign before its letter: "
                f"today {len(checks.misplaced_signs(chr(10).join(old)))}, {name} "
                f"{len(checks.misplaced_signs(chr(10).join(new)))}.", "",
                f"| line | today (pypdf) | **{name}** | what changed | correct? |", "|---|---|---|---|---|", *rows, ""]
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
