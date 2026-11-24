"""Location views lab (2026-11-24): does ONE sheet of named views of a place keep the background the same from shot to
shot, when each board panel and first frame names the view it is seen from?

The person's method: like a location reference sheet (a locker room shown as a wide, a reverse, a corner, details),
paint the place once as named views; then every prompt says which view it is in, so the image model paints the same
place from the same side. The case: Love Hour scene 4 (de75bc31), "Colombo roadside" with the "Food three-wheeler";
board v12 part 1 drifted its three-wheeler (a stall, a van, a cart) and the wall from panel to panel.

    sheet   ONE picture, 6 views in a 3x2 grid, no people, painted from the two place plates (MEDIUM). Code cuts it
            into one picture per view (the product's `cell_boxes`) and draws the labels itself (the model draws no
            text).
    board   board part 1 again (shots 1-6, LOW) with the saved writer's words, the sheet attached instead of the
            single plate, and each panel told its view (`VIEWS`, picked by hand here; the writer would pick them).
    frame   shot 1's first frame again (MEDIUM) with its saved prompt and pictures, the two place plates replaced by
            view 1 of the sheet.

    .venv/Scripts/python.exe lab/location_views/run.py dry
    .venv/Scripts/python.exe lab/location_views/run.py sheet --yes
    .venv/Scripts/python.exe lab/location_views/run.py board --yes   (needs a sheet)
    .venv/Scripts/python.exe lab/location_views/run.py frame --yes   (needs a sheet)

Nothing under `src/` changes and nothing is written to the database. The ledger stops every call past the budget.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(HERE)]

from PIL import Image, ImageDraw  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 1.00  # the person's cap (2026-11-24)
MODEL = "gpt-image-2"
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the other board labs)
LEDGER = HERE / "runs" / "ledger.csv"
IN = HERE / "input"

# The views of the place: (name, what the camera sees). The front wide is the conversation's own view; the others are
# what a scene at this roadside can look at. Written once for the place, never for one shot.
SHEET_VIEWS = [
    ("1 Front wide", "Standing eye height on the road side of the pavement, looking straight across the pavement at "
                     "the frontage. The food three-wheeler stands side-on in its vending bay at frame left, its "
                     "serving hatch open toward the pavement; the pale weathered boundary wall runs across frame "
                     "right with the leaf-green building surface above and behind it; the wet pavement runs across "
                     "the frame and the open kerb drain along the bottom edge."),
    ("2 Looking left", "Standing on the pavement just right of the three-wheeler, looking left along the pavement: the "
                       "three-wheeler's back and hatch close at frame right, the shuttered shopfronts and the blue "
                       "shop awning receding beyond it, the road and kerb drain on frame left."),
    ("3 Looking right", "Standing on the pavement just right of the three-wheeler, looking right along the pavement: "
                        "the pale boundary wall running away on frame left with a utility pole, the green building "
                        "corner, the onward wet pavement and the kerb drain on frame right."),
    ("4 Reverse", "Standing at the wall beside the three-wheeler, looking out across the pavement and the kerb drain "
                  "to the wet road and the low buildings and trees on the far side of the street."),
    ("5 Hatch detail", "Close on the three-wheeler's open side hatch: the scratched stainless-steel serving ledge, "
                       "shallow food trays and the insulated tea flask, under its small hinged roof."),
    ("6 Ground detail", "Looking down at the wet concrete pavement edge, the open kerb drain and its grate at the foot "
                        "of the pale wall, rain on the ground."),
]
# board part 1: the view each panel is seen from (shots 1-5 face the frontage from the road side; shot 6 looks down
# at a hand over the pavement)
VIEWS = {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 6}
SHEET_LABEL = "the location sheet for Colombo roadside: six named views of the one place"


# ── money (as lab/board_grid) ─────────────────────────────────────────────────────────────────────────────

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


def worst(refs: list[Reference], prompt: str, quality: str) -> float:
    return dollars(1600 * len(refs) + len(prompt) // 3, 1500 if quality == "low" else 6500)


# ── the three prompts ────────────────────────────────────────────────────────────────────────────────────

def places() -> list[dict]:
    return json.loads((IN / "places.json").read_text(encoding="utf-8"))


def board_row() -> dict:
    return json.loads((IN / "board_part1.json").read_text(encoding="utf-8"))


def sheet_prompt() -> tuple[str, list[Reference]]:
    p = places()
    writer = board_row()["writer"]
    refs = [Reference(label=f"the location plate for {p[0]['name']}", data=(IN / p[0]["file"]).read_bytes()),
            Reference(label=f"the reference sheet for {p[1]['name']}", data=(IN / p[1]["file"]).read_bytes())]
    light = ("Soft early-morning overcast daylight with steady fine rain falling; wet concrete pavement and patched "
             "dark asphalt shine; restrained amber shop light deep inside the shopfronts.")
    views = "\n".join(f"VIEW {i} (row {(i - 1) // 3 + 1}, column {(i - 1) % 3 + 1}) — {name.split(' ', 1)[1]}: {text}"
                      for i, (name, text) in enumerate(SHEET_VIEWS, 1))
    prompt = "\n\n".join([
        "A location reference sheet for a Sri Lankan television drama: six photorealistic film stills of ONE real "
        "place, laid out in a grid 3 across and 2 down, read left to right, then top to bottom. Every still is a "
        "landscape 3:2 picture of the same size, separated by thin, even, plain white gutters. Nobody is in any "
        "view: no people, no figures.",
        f"Reference images, in order: image 1 is {refs[0].label}; image 2 is {refs[1].label}. Take from image 1 the "
        "street: the pavement, the kerb drain, the walls, the buildings, the poles and cables, their materials and "
        "colours. Take from image 2 the food three-wheeler exactly as shown: its maroon body, black vinyl roof, small "
        "cab and the side hatch with its serving ledge. It is parked in the vending bay of this street.",
        f"The place, one connected layout seen from six positions: {writer['geography']}",
        f"Light and weather (every view): {light}",
        views,
        "Every view shows the SAME place: the same three-wheeler, the same wall, the same green building, the same "
        "pavement and drain, each where the layout puts it. Draw NO text of any kind: no labels, no numbers, no "
        "captions, no arrows, no borders other than the gutters.",
    ])
    return prompt, refs


def view_crops(sheet: bytes) -> list[bytes]:
    boxes = pics.cell_boxes(sheet, len(SHEET_VIEWS))
    return [pics.crop(sheet, [int(v) for v in b]) for b in boxes]


def labelled(sheet: bytes) -> bytes:
    """The sheet with each view's name drawn by code under its cell, for people reading the lab."""
    im = Image.open(io.BytesIO(sheet)).convert("RGB")
    draw = ImageDraw.Draw(im)
    for (name, _), box in zip(SHEET_VIEWS, pics.cell_boxes(sheet, len(SHEET_VIEWS)), strict=False):
        x0, y0 = int(box[0]) + 8, int(box[1]) + 8
        draw.rectangle([x0 - 4, y0 - 4, x0 + 9 * len(name), y0 + 18], fill=(200, 16, 46))
        draw.text((x0, y0), name, fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def board_prompt(sheet: bytes) -> tuple[str, list[Reference]]:
    """The saved part-1 prompt with the single plate swapped for the sheet, and each panel told its view."""
    saved = board_row()["prompt"]
    old = re.search(r"Reference images, in order: .*?(?=\n\n)", saved, re.S)
    if old is None:
        raise SystemExit("the saved board prompt has no references paragraph; the product wording changed")
    names = "; ".join(f"view {n}" for n, _ in SHEET_VIEWS)
    new = (f"Reference images, in order: image 1 is {SHEET_LABEL}, numbered left to right, then top to bottom: "
           f"{names}. Take from image 1 the place itself: its buildings, the food three-wheeler, the wall, the "
           "pavement and the drain, their materials and where each one stands. Every panel below names the view its "
           "background comes from: paint that view's background, the same things on the same sides, seen from the "
           "panel's own camera (closer or tighter as the panel says). Never copy the sheet's gutters or layout.")
    out = saved[: old.start()] + new + saved[old.end():]
    for panel, view in VIEWS.items():
        name = SHEET_VIEWS[view - 1][0]
        m = re.search(rf"PANEL {panel} \(row \d, column \d\) — [^\n]*", out)
        if m is None:
            raise SystemExit(f"no PANEL {panel} line in the saved prompt")
        out = out[: m.end()] + f" Background view: view {name}." + out[m.end():]
    return out, [Reference(label=SHEET_LABEL, data=sheet)]


def frame_prompt(sheet: bytes) -> tuple[str, list[Reference]]:
    """Shot 1's saved frame prompt and pictures, the location plate (image 5) swapped for view 1 of the sheet."""
    saved = json.loads((IN / "frame_shot1.json").read_text(encoding="utf-8"))["prompt"]
    meta = json.loads((IN / "frame_refs.json").read_text(encoding="utf-8"))
    view = view_crops(sheet)[0]
    label = "view 1 (front wide) of the location sheet for Colombo roadside"
    refs = []
    for r in meta:
        if r["label"] == "the location plate for Colombo roadside":
            refs.append(Reference(label=label, data=view))
        else:
            refs.append(Reference(label=r["label"], data=(IN / r["file"]).read_bytes()))
    if "image 5 is the location plate for Colombo roadside" not in saved:
        raise SystemExit("the saved frame prompt has no image 5 location plate; fetch again")
    out = saved.replace("image 5 is the location plate for Colombo roadside", f"image 5 is {label}")
    out = out.replace("image 5: the place and its fixtures, not its light or time of day",
                      "image 5: the background exactly as this view shows it (the food three-wheeler at frame left, "
                      "the pale wall and the green building at frame right, the wet pavement and the kerb drain), "
                      "seen from this shot's own camera")
    return out, refs


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────

def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()), default=0)
    out = runs / f"run_{n:03d}"
    out.mkdir()
    return out


def latest_sheet() -> bytes | None:
    found = sorted((HERE / "runs").glob("run_*/sheet.png")) if (HERE / "runs").exists() else []
    return found[-1].read_bytes() if found else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "sheet", "board", "frame"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()
    sheet = latest_sheet()

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        stand_in = sheet or (IN / "board_part1.png").read_bytes()  # any picture, to build the later prompts
        for name, (prompt, refs), quality in (("sheet", sheet_prompt(), "medium"), ("board", board_prompt(stand_in),
                                                                                     "low"),
                                              ("frame", frame_prompt(stand_in), "medium")):
            (d / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
            blocked = safe_depiction.blocking(prompt)
            print(f"{name}: {len(prompt)} chars, {len(refs)} pictures ({', '.join(r.label for r in refs)}); worst "
                  f"${worst(refs, prompt, quality):.3f}{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; prompts in {d}")
        return 0

    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode in ("board", "frame") and sheet is None:
        print("paint the sheet first")
        return 2
    if args.mode == "sheet":
        prompt, refs = sheet_prompt()
        aspect, quality = "16:9", "medium"
    elif args.mode == "board":
        assert sheet is not None
        prompt, refs = board_prompt(sheet)
        aspect, quality = "9:16", "low"
    else:
        assert sheet is not None
        prompt, refs = frame_prompt(sheet)
        aspect, quality = "9:16", "medium"
    w = worst(refs, prompt, quality)
    if spent() + w > LAB_BUDGET_USD:
        print(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
        return 3
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    out = next_run()
    (out / f"{args.mode}_prompt.txt").write_text(prompt, encoding="utf-8")
    painter = OpenAIImages(client(), model=MODEL, quality=quality)
    t = time.time()
    pic = painter(prompt, aspect, refs, quality=quality)
    usd = book(out.name, args.mode, pic.input_tokens, pic.output_tokens, f"{args.mode} {quality}")
    (out / f"{args.mode}.png").write_bytes(pic.data)
    if args.mode == "sheet":
        (out / "sheet_labelled.png").write_bytes(labelled(pic.data))
        for i, crop in enumerate(view_crops(pic.data), 1):
            (out / f"view_{i}.png").write_bytes(crop)
        problems = pics.cut_problems(pic.data, pics.cell_boxes(pic.data, len(SHEET_VIEWS)))
        print(f"cut: {'ok' if not problems else '; '.join(problems)}")
    elif args.mode == "board":
        boxes = pics.cell_boxes(pic.data, len(VIEWS))
        (out / "board_cells.png").write_bytes(pic.data)
        problems = pics.cut_problems(pic.data, boxes)
        print(f"cut: {'ok' if not problems else '; '.join(problems)}")
    print(f"{args.mode}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; "
          f"files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
