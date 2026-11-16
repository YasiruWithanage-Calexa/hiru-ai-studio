"""Portrait Scene board + no mannequins in the first frame (lab for interface fixes 2 and 3, 2026-11-16).

Questions
  Q2  Painted at 1024x1536 with "portrait 9:16" panels, does the board come out as clean tall panels that the
      product's own gutter finder (`pictures.cell_boxes`) cuts into one picture per shot?
  Q3  When the frame prompt calls unnamed board figures what they are (people, not "grey mannequins") and says the
      draft's mannequins are stand-ins, is the first frame free of mannequins?

Calls (all LOW, gpt-image-2, through the product's own painter `hiru_ai.adapters.images.OpenAIImages`)
  r1  board   the saved board prompt with the portrait wording, 9:16, the saved board's own reference picture
  r2  frame   shot 1 from r1's panel 1 + the fixed frame prompt, 9:16                 (fix 2 + fix 3 together)
  r3  frame   shot 1 from the OLD landscape panel 1 + the fixed frame prompt, 9:16    (fix 3 alone: the control)

    .venv/Scripts/python.exe lab/portrait_board/run.py dry  --input scene1           # prompts + worst case, no call
    .venv/Scripts/python.exe lab/portrait_board/run.py paid --input scene1 --yes     # the person's yes, every time

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
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab")]

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 0.40
MODEL, QUALITY = "gpt-image-2", "low"
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the storyboard lab)
WORST_OUT = 1500  # a LOW picture used 158 output tokens in the storyboard lab; guard only
LEDGER = HERE / "runs" / "ledger.csv"

# ── the two proposed product changes, as text transforms of what the product saved ─────────────────────────

LANDSCAPE = "Every panel is a landscape 16:9 still"
PORTRAIT = "Every panel is a tall portrait 9:16 still"


def portrait_board_prompt(saved: str) -> str:
    """Fix 2: `contracts.board.board_prompt` names the production's shape instead of always 'landscape 16:9'."""
    if LANDSCAPE not in saved:
        raise SystemExit("the saved board prompt has no landscape sentence; the product wording changed")
    return saved.replace(LANDSCAPE, PORTRAIT)


# An unnamed board figure: "two small neutral-grey pedestrian mannequins" → "two pedestrians".
_EXTRA = re.compile(r"\b(?:(?:small|tiny|distant|faceless|plain|neutral[- ]gr[ae]y|gr[ae]y|pedestrian|background)"
                    r"[ -])+(mannequin)(s?)\b", re.I)
STAND_INS = ("The approved draft shows people as plain mannequins: they are stand-ins for where people stand and how "
             "they hold themselves, nothing more. Every figure in it, named or not, including small grey figures in "
             "the background, is a real, clothed Sri Lankan person in this frame. Draw no mannequins, dummies, "
             "statues or faceless figures.")
ANCHOR = "The sheets still decide faces, hair and the place."


def realize(saved: str) -> str:
    """Fix 3: the panel's words call background figures people, and the stand-in rule follows the draft line."""
    text = _EXTRA.sub(lambda m: "pedestrians" if m.group(2) else "pedestrian", saved)
    if ANCHOR not in text:
        raise SystemExit("the saved frame prompt has no draft anchor; the product wording changed")
    return text.replace(ANCHOR, f"{ANCHOR} {STAND_INS}", 1)


# ── money ────────────────────────────────────────────────────────────────────────────────────────────────

def dollars(inp: int, out: int) -> float:
    return inp * PRICES[0] / 1e6 + out * PRICES[1] / 1e6


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def book(run: str, step: str, inp: int, out: int, status: str, note: str) -> float:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    usd = dollars(inp, out)
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "run", "step", "model", "input_tokens", "output_tokens", "usd", "status", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), run, step, MODEL, inp, out, f"{usd:.5f}", status, note])
    return usd


def worst(refs: list[Reference], prompt: str) -> float:
    # ~1,500 input tokens per reference picture at low detail + the prompt's words; over-stated on purpose
    return dollars(1500 * len(refs) + len(prompt) // 3, WORST_OUT)


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────

def load(name: str) -> dict:
    d = HERE / "input" / name
    board = json.loads((d / "board.json").read_text(encoding="utf-8"))
    frame = json.loads((d / "frame.json").read_text(encoding="utf-8"))
    refs = json.loads((d / "refs.json").read_text(encoding="utf-8"))
    return {"dir": d, "board": board, "frame": frame, "refs": refs}


def board_refs(inp: dict) -> list[Reference]:
    """The saved board cited one picture: the location plate of its first reference (its own prompt says which)."""
    cite = re.search(r"image 1 is the location plate for ([^.;]+)", inp["board"]["prompt"])
    name = cite.group(1).strip() if cite else ""
    ref = next(r for r in inp["refs"] if r["name"] == name)
    return [Reference(label=f"the location plate for {name}",
                      data=(inp["dir"] / f"ref_{ref['id']}.png").read_bytes())]


def frame_refs(inp: dict, panel: bytes) -> list[Reference]:
    out = [Reference(label=f"the location plate for {r['name']}", data=(inp["dir"] / f"ref_{r['id']}.png").read_bytes())
           for r in inp["refs"]]
    return [*out, Reference(label="the approved draft of this frame", data=panel)]


def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()), default=0)
    out = runs / f"run_{n:03d}"
    out.mkdir()
    return out


def paint(painter, out: Path, step: str, prompt: str, refs: list[Reference], note: str) -> bytes | None:
    found = safe_depiction.blocking(prompt)
    if found:
        print(f"[{step}] stopped by safe depiction: {found}")
        return None
    w = worst(refs, prompt)
    if spent() + w > LAB_BUDGET_USD:
        print(f"[{step}] NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
        return None
    (out / f"{step}_prompt.txt").write_text(prompt, encoding="utf-8")
    t = time.time()
    pic = painter(prompt, "9:16", refs, quality=QUALITY)
    usd = book(out.name, step, pic.input_tokens, pic.output_tokens, "done", note)
    (out / f"{step}.png").write_bytes(pic.data)
    print(f"[{step}] {pics.image_size(pic.data)} in {time.time() - t:.0f} s, ${usd:.4f} "
          f"(ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f})")
    return pic.data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "paid"])
    ap.add_argument("--input", required=True)
    ap.add_argument("--shot", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="the person said yes to these calls")
    args = ap.parse_args()
    inp = load(args.input)
    n = len(inp["board"]["cells"])

    b_prompt = portrait_board_prompt(inp["board"]["prompt"])
    f_prompt = realize(inp["frame"]["prompt"])
    old_panel = (inp["dir"] / f"cell_old_{args.shot:03d}.png").read_bytes()
    b_refs, f_refs = board_refs(inp), frame_refs(inp, old_panel)
    est = worst(b_refs, b_prompt) + 2 * worst(f_refs, f_prompt)

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        (d / "r1_board_prompt.txt").write_text(b_prompt, encoding="utf-8")
        (d / "r2_frame_prompt.txt").write_text(f_prompt, encoding="utf-8")
        print(f"board: {n} panels, refs {[r.label for r in b_refs]}")
        print(f"frame refs: {[r.label for r in f_refs]}")
        print("mannequin words left in the frame prompt:",
              re.findall(r"[^.]*mannequin[^.]*\.", f_prompt) or "none")
        print(f"worst case for r1+r2+r3: ${est:.3f}; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
        print(f"prompts written to {d}")
        return 0

    if not args.yes:
        print("paid needs --yes: the person's yes for these three LOW image calls")
        return 2
    from hiru_ai.adapters.images import OpenAIImages
    from cinematic.run import client  # the only place a client is built; it reads .env

    painter = OpenAIImages(client(), model=MODEL, quality=QUALITY)
    out = next_run()
    print(f"=== {out.name} ===")

    board = paint(painter, out, "r1_board", b_prompt, b_refs, "portrait board: 9:16 sheet, portrait panel wording")
    panel = None
    if board:
        boxes = pics.cell_boxes(board, n)
        (out / "panels").mkdir()
        for i, box in enumerate(boxes, 1):
            (out / "panels" / f"panel_{i:03d}.png").write_bytes(pics.crop(board, box))
        sizes = [(b[2] - b[0], b[3] - b[1]) for b in boxes]
        print(f"[r1_board] panels found by cell_boxes: {sizes}")
        panel = pics.crop(board, boxes[args.shot - 1])
    if panel:
        paint(painter, out, "r2_frame_portrait_panel", f_prompt, frame_refs(inp, panel),
              "fix 2+3: frame from the portrait panel, mannequins named as stand-ins")
    paint(painter, out, "r3_frame_old_panel", f_prompt, frame_refs(inp, old_panel),
          "fix 3 alone: frame from the old landscape panel, mannequins named as stand-ins")
    (out / "summary.json").write_text(json.dumps({"input": args.input, "shot": args.shot, "quality": QUALITY,
                                                  "spent_total": round(spent(), 4)}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
