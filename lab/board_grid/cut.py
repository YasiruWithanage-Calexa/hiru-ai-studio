"""Free sweep: every finished board the product has stored, cut two ways. No model call.

  product  the boxes the product saved (`pictures.cell_boxes` at paint time), judged by the fix-3 checks
  lab      `grid.cut`: the grid really painted, empty cells skipped (fix 2), judged by the same checks

and, per board, whether the board writer's own words (the World paragraph) name a layout that contradicts the grid
the code asks for.

    .venv/Scripts/python.exe lab/board_grid/cut.py

Writes `runs/sweep/report.md` and, for every board either cutter gets wrong, `runs/sweep/<id>_product.png` and
`<id>_lab.png` (the crops side by side, in shot order).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(HERE)]

import grid  # noqa: E402

from contracts.board import grid_for  # noqa: E402

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16}
_N = r"(\d+|" + "|".join(WORDS) + r")"
COLS = [rf"{_N}[- ]columns?", rf"{_N} (?:\w+ )?(?:panels |cells )?across", rf"columns? by {_N}"]
ROWS = [rf"{_N}[- ]rows?", rf"{_N} down", rf"by {_N} rows"]
COUNT = [rf"{_N} (?:equal |painted |portrait |landscape |vertical |tall |wide )*panels",
         rf"first {_N} cells", rf"placing {_N} panels"]


def _num(text: str, patterns: list[str]) -> int | None:
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            v = m.group(1).lower()
            return int(v) if v.isdigit() else WORDS[v]
    return None


def writer_layout(prompt: str) -> dict:
    """The writer's own layout words in the World paragraph: the sentence, its columns, rows and panel count."""
    m = re.search(r"World \(every panel\): ([^\n]*)", prompt or "")
    world = m.group(1) if m else ""
    sentences = [s for s in re.split(r"(?<=\.)\s+", world)
                 if re.search(r"grid|columns?\b|across|\bdown\b|cells?\b|panels? in shot order", s, re.I)
                 and re.search(r"storyboard|panel|cell|grid", s, re.I)]
    text = " ".join(sentences[:2])
    return {"text": text, "cols": _num(text, COLS), "rows": _num(text, ROWS), "count": _num(text, COUNT)}


def contradicts(says: dict, n: int, cols: int, rows: int) -> str:
    bad = [f"{k} {says[k]} (code: {v})" for k, v in (("cols", cols), ("rows", rows), ("count", n))
           if says[k] is not None and says[k] != v]
    return ", ".join(bad)


def main() -> int:
    src = HERE / "input" / "boards"
    out = HERE / "runs" / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    lines = ["| board | part | n | asked | lab found | writer contradicts | product cut | lab cut | shape |",
             "|---|---|---|---|---|---|---|---|---|"]
    c = {"boards": 0, "skipped": 0, "product_bad": 0, "lab_bad": 0, "mended": 0, "broke": 0, "contradicts": 0,
         "contradicts_bad": 0, "shape": 0}
    for jf in sorted(src.glob("*.json")):
        b = json.loads(jf.read_text(encoding="utf-8"))
        png = jf.with_suffix(".png")
        cells = [x for x in b.get("cells") or [] if x.get("panel")]
        if not png.exists() or not cells:
            continue
        if any(not x.get("box") for x in cells):
            c["skipped"] += 1  # an Update board painted some panels alone: they have no box on this sheet
            lines.append(f"| {b['id'][:8]} | {b['part']}/{b['parts']} | {len(cells)} | | | | skipped: panels painted "
                         "alone by Update board | | |")
            continue
        c["boards"] += 1
        data = png.read_bytes()
        cells.sort(key=lambda x: x["panel"])
        boxes = [x["box"] for x in cells]
        n = len(boxes)
        cols, rows = grid_for(n)
        product_cut, _ = grid.check(data, boxes)
        lab_boxes, how = grid.cut(data, n, (cols, rows))
        lab_cut, shape = grid.check(data, lab_boxes)
        says = writer_layout(b.get("prompt") or "")
        contra = contradicts(says, n, cols, rows)
        c["contradicts"] += bool(contra)
        c["contradicts_bad"] += bool(contra) and bool(product_cut)
        c["product_bad"] += bool(product_cut)
        c["lab_bad"] += bool(lab_cut)
        c["mended"] += bool(product_cut) and not lab_cut
        c["broke"] += not product_cut and bool(lab_cut)
        c["shape"] += bool(shape)
        if product_cut or lab_cut:
            (out / f"{b['id'][:8]}_product.png").write_bytes(grid.contact(data, boxes))
            (out / f"{b['id'][:8]}_lab.png").write_bytes(grid.contact(data, lab_boxes))
        lines.append(f"| {b['id'][:8]} | {b['part']}/{b['parts']} | {n} | {cols}x{rows} | {how} | {contra or '-'} | "
                     f"{'; '.join(product_cut) or 'ok'} | {'; '.join(lab_cut) or 'ok'} | {'; '.join(shape) or 'ok'} |")
    head = (f"# Board grid sweep\n\n{c['boards']} boards cut ({c['skipped']} skipped: panels painted alone).\n\n"
            f"- product cut bad: {c['product_bad']}; lab cut bad: {c['lab_bad']}; "
            f"mended by the lab cutter: {c['mended']}; broken by it: {c['broke']}\n"
            f"- writer's layout words contradict the code's grid: {c['contradicts']} "
            f"(of them with a bad product cut: {c['contradicts_bad']})\n"
            f"- panels the wrong shape for the sheet: {c['shape']} boards\n\n")
    (out / "report.md").write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    print(head.strip())
    print(f"report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
