"""Board grid lab, paid half (2026-11-22): does the image model paint the grid we ask for, once the prompt stops
contradicting itself?

The case: Love Hour scene de75bc31, board part 2 of 2 (34683023), 6 tall panels. The code asked for 3 across and 2
down; the board writer's World paragraph said "a four-column, four-row grid ... fill the first fourteen cells" (it is
told the whole scene's grid, `writer_message` -> `grid_for(14)`); the model painted 3 across and 3 down, 2 rows of
panels and a row of empty cells. 15 of the 22 stored boards carry such a contradiction (`cut.py`).

Variants (same references, same panels, LOW, gpt-image-2 through the product's own painter):
  A  control   the saved prompt, unchanged
  B  no-leak   the writer's layout sentences removed from the World paragraph; the code still asks for 3x2
  C  square    B + a square grid: 3 across and 3 down, "the last 3 cells are left plain white"

Every result is cut by the product's `pictures.cell_boxes` and by the lab cutter (`grid.cut`), and judged by the same
checks (`grid.check`).

    .venv/Scripts/python.exe lab/board_grid/run.py dry
    .venv/Scripts/python.exe lab/board_grid/run.py paid --yes [--variants A,B,C] [--repeat 3]

Nothing under `src/` changes and nothing is written to the database.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(HERE)]

import grid  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from contracts.board import grid_for  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 0.60
MODEL, QUALITY, ASPECT = "gpt-image-2", "low", "9:16"
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the other board labs)
WORST_OUT = 1500  # a LOW picture used 158 output tokens (portrait_board run_001); guard only
LEDGER = HERE / "runs" / "ledger.csv"
INPUT = "love_p2"

LAYOUT = re.compile(r"grid|columns?\b|across|\bdown\b|cells?\b|panels? in shot order", re.I)
SHEETY = re.compile(r"storyboard|panel|cell|grid", re.I)


def no_leak(prompt: str) -> str:
    """B: the World paragraph without the writer's own layout sentences (the code's head sentence decides the grid)."""
    m = re.search(r"(World \(every panel\): )([^\n]*)", prompt)
    if not m:
        raise SystemExit("the saved prompt has no World paragraph; the product wording changed")
    kept = [s for s in re.split(r"(?<=\.)\s+", m.group(2)) if not (LAYOUT.search(s) and SHEETY.search(s))]
    return prompt[: m.start(2)] + " ".join(kept) + prompt[m.end(2):]


def square(prompt: str, n: int) -> str:
    """C: a square grid, the cells after the last panel left plain white. Columns stay `grid_for(n)`'s, so every
    PANEL's (row, column) is unchanged."""
    cols, rows = grid_for(n)
    old = f"laid out in a grid {cols} panels across and {rows} down"
    if old not in prompt:
        raise SystemExit("the saved prompt has no grid sentence; the product wording changed")
    out = prompt.replace(old, f"laid out in a grid {cols} panels across and {cols} down")
    empty = cols * cols - n
    if empty:
        out = out.replace("read left to right, then top to bottom.",
                          f"read left to right, then top to bottom. The first {n} cells hold the panels; the last "
                          f"{empty} cell{'s are' if empty > 1 else ' is'} left plain white, with nothing painted in "
                          f"{'them' if empty > 1 else 'it'}.", 1)
    return out


# ── money (as lab/portrait_board) ───────────────────────────────────────────────────────────────────────

def dollars(inp: int, out: int) -> float:
    return inp * PRICES[0] / 1e6 + out * PRICES[1] / 1e6


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def book(run: str, step: str, inp: int, out: int, note: str) -> float:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    usd = dollars(inp, out)
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "run", "step", "model", "input_tokens", "output_tokens", "usd", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), run, step, MODEL, inp, out, f"{usd:.5f}", note])
    return usd


def worst(refs: list[Reference], prompt: str) -> float:
    return dollars(1500 * len(refs) + len(prompt) // 3, WORST_OUT)


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────

def load() -> tuple[dict, list[Reference]]:
    d = HERE / "input" / INPUT
    board = json.loads((d / "board.json").read_text(encoding="utf-8"))
    refs = json.loads((d / "refs.json").read_text(encoding="utf-8"))
    return board, [Reference(label=r["label"], data=(d / f"ref_{i}.png").read_bytes()) for i, r in enumerate(refs, 1)]


def variants(board: dict) -> dict[str, str]:
    saved = board["prompt"]
    n = len([c for c in board["cells"] if c.get("panel")])
    return {"A": saved, "B": no_leak(saved), "C": square(no_leak(saved), n)}


def judge(data: bytes, n: int) -> dict:
    asked = grid_for(n)
    found = grid.found_grid(data, asked)
    product = [tuple(b) for b in pics.cell_boxes(data, n)]
    lab, how = grid.cut(data, n, asked)
    p_cut, _ = grid.check(data, product)
    l_cut, shape = grid.check(data, lab)
    return {"painted": f"{found['cols']}x{found['rows']} ({len(found['panels'])} panels)", "lab_how": how,
            "product_ok": not p_cut, "lab_ok": not l_cut, "product": p_cut, "lab": l_cut, "shape": shape,
            "product_boxes": product, "lab_boxes": lab}


def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()), default=0)
    out = runs / f"run_{n:03d}"
    out.mkdir()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "paid"])
    ap.add_argument("--variants", default="A,B,C")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--yes", action="store_true", help="the person said yes to these calls")
    args = ap.parse_args()
    board, refs = load()
    n = len([c for c in board["cells"] if c.get("panel")])
    prompts = variants(board)
    chosen = [v.strip() for v in args.variants.split(",") if v.strip()]
    calls = [(v, r) for v in chosen for r in range(1, args.repeat + 1)]
    est = sum(worst(refs, prompts[v]) for v, _ in calls)

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        for v, p in prompts.items():
            (d / f"{v}_prompt.txt").write_text(p, encoding="utf-8")
            blocked = safe_depiction.blocking(p)
            print(f"{v}: {len(p)} chars{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"refs: {[r.label for r in refs]}")
        saved = judge((HERE / "input" / INPUT / "board_old.png").read_bytes(), n)
        print(f"the saved board, judged: {json.dumps({k: v for k, v in saved.items() if 'boxes' not in k})}")
        print(f"{len(calls)} calls; worst case ${est:.3f}; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
        print(f"prompts written to {d}")
        return 0

    if not args.yes:
        print("paid needs --yes: the person's yes for these LOW image calls")
        return 2
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    painter = OpenAIImages(client(), model=MODEL, quality=QUALITY)
    out = next_run()
    print(f"=== {out.name}: {len(calls)} calls, worst ${est:.3f} ===")
    for v in chosen:
        (out / f"{v}_prompt.txt").write_text(prompts[v], encoding="utf-8")
    results = []
    for v, r in calls:
        step = f"{v}{r}"
        w = worst(refs, prompts[v])
        if spent() + w > LAB_BUDGET_USD:  # checked before every call: the run stops at the cap
            print(f"[{step}] NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
            break
        t = time.time()
        try:
            pic = painter(prompts[v], ASPECT, refs, quality=QUALITY)
        except Exception as exc:  # a refusal or a failure is a result too
            print(f"[{step}] failed: {exc}")
            results.append({"step": step, "variant": v, "error": str(exc)})
            continue
        usd = book(out.name, step, pic.input_tokens, pic.output_tokens, f"variant {v} repeat {r}")
        (out / f"{step}.png").write_bytes(pic.data)
        j = judge(pic.data, n)
        (out / f"{step}_product.png").write_bytes(grid.contact(pic.data, j["product_boxes"]))
        (out / f"{step}_lab.png").write_bytes(grid.contact(pic.data, j["lab_boxes"]))
        row = {"step": step, "variant": v, "usd": round(usd, 4), "secs": round(time.time() - t),
               **{k: x for k, x in j.items() if "boxes" not in k}}
        results.append(row)
        print(f"[{step}] painted {j['painted']}; product cut {'ok' if j['product_ok'] else 'BAD'}; "
              f"lab cut {'ok' if j['lab_ok'] else 'BAD'} ({j['lab_how']}); shape {'ok' if not j['shape'] else 'off'}; "
              f"${usd:.4f}")
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
