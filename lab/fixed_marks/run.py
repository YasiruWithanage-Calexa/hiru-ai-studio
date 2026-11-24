"""Fixed marks lab (2026-11-24): a person who does not travel stays on ONE spot on the ground for every shot.

The person's rule (2026-11-24): "if people didn't walk they should stay on the same position for the entire shots; if
they walk or travel, only then the position changes"; the position is the GROUND position (the spot in the place, its
landmarks and the gap to the other person), not the side of the picture; small steps keep the mark, within a small
radius. Plans 2026-11-24 / 24b / 24c fixed the PLACE (the views sheet) and the VEHICLES; nothing fixes where a person
stands in the place. The staging map's mark is a `zone` ("roadside") and a `frame_side`, both too coarse or relative to
the camera, so each panel re-decides where people stand, and the image model fills it in: on v18 part 1 (the board the
person showed) Kasun has the three-wheeler behind him two metres from Anudi in panels 1 and 3, a counter under the
awning almost touching her in panels 2, 4 and 5.

The case: Love Hour scene 4, board v18 part 1 (shots 1-6), its SAVED prompt and its pictures (`fetch.py`). Nobody moves
in shots 1-6. Every arm is the saved prompt plus the same MARKS words (a "Ground marks" paragraph, and a marks line on
each panel); they differ only in the picture that carries the marks:

    A  words only
    B  words + a floor plan seen from above (drawn by code, `plan`: no text, coloured dots, the radius ring)
    C  words + a blocking plate: ONE wide still of the two mannequins on their marks from the views sheet's anchor
       camera, painted first (`plate`), then attached to the board

Judge each board on: (1) the same thing behind each person in panels 1-5 (the three-wheeler's hatch behind Kasun, the
green building and pale wall behind Anudi); (2) the same gap between them (a closer camera makes them bigger, never
closer); (3) nobody's feet move; (4) what v18 already got right is kept (sides, hands, umbrella, bag, the insert).

    .venv/Scripts/python.exe lab/fixed_marks/run.py dry
    .venv/Scripts/python.exe lab/fixed_marks/run.py plan                 (free: draws the floor plan)
    .venv/Scripts/python.exe lab/fixed_marks/run.py plate --yes          (for C; `plate T --yes` the tall one, for T)
    .venv/Scripts/python.exe lab/fixed_marks/run.py board <A|B|C> --yes
    .venv/Scripts/python.exe lab/fixed_marks/run.py compare              (free: v18 and every board, cut by panel)

Nothing under `src/` changes and nothing is read from or written to the database (inputs are `fetch.py`'s copies).
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
LAB = HERE.parent
ROOT = LAB.parent
sys.path[:0] = [str(ROOT / "src" / "libs"), str(LAB)]

from PIL import Image, ImageDraw  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 0.92  # the person's yes: $0.60, $0.75 for the tall plate, + phase 0 of plan/2026-11-24d (about $0.30), 2026-11-24
MODEL = "gpt-image-2"
PRICES = (10.00, 40.00)
IN = HERE / "input"
RUNS = HERE / "runs"
LEDGER = RUNS / "ledger.csv"
PANELS = 6
ASPECT = "9:16"  # the product's: Love Hour is vertical, the board is tall (contracts.board.TALL)
RADIUS_M = 0.5  # the person's "small radius": a half step, a turn, a lean stay inside it

# ── the marks (the method under test) ─────────────────────────────────────────────────────────────────────────────

MARKS = (
    "Ground marks (every panel): nobody walks in panels 1 to 6, so each person stands on ONE spot on the ground for "
    "the whole sheet, and every panel shows them on that same spot, seen from its own camera. Small movements (a turn "
    "of the head or body, a lean, a shift of weight, half a step) stay within half a metre of the mark; the feet never "
    "travel further. Kasun (the red mannequin) stands on the concrete pavement half a metre in from the kerb drain, one "
    "step to the right of the rear of the food three-wheeler, whose open service hatch and the blue awning above it "
    "are directly behind him and to his left. Anudi (the blue mannequin) stands on the same pavement, the same half "
    "metre in from the drain, about 1.2 metres to Kasun's right, in front of the green building, with the pale "
    "boundary wall beginning just to her right. The gap between them is the same in every panel, about an arm's "
    "length and a little more between their chests, never touching: a closer camera makes them larger, never closer "
    "together. What is behind each of them follows from these spots and the panel's camera.")

PANEL_MARKS = {
    1: "Marks: both on their ground marks, the full gap between them; the three-wheeler's hatch behind Kasun.",
    2: "Marks: both on their ground marks, the same gap as panel 1; behind Kasun the upper part of the three-wheeler "
       "and its raised hatch, behind Anudi the green building.",
    3: "Marks: both on their ground marks, exactly as panel 1.",
    4: "Marks: both on their ground marks, the same gap as panel 1; behind Kasun the three-wheeler's raised hatch, "
       "behind Anudi the green building.",
    5: "Marks: both on their ground marks, the same gap as panel 1, seen closer: behind Kasun the soft maroon body "
       "and raised hatch of the three-wheeler, behind Anudi the soft green building.",
    6: "Marks: Anudi on her ground mark; the camera looks down at her hand, so only the pavement is behind it.",
}

PLAN_WORDS = (
    "Image 3 is a FLOOR PLAN of the place seen from directly above: a map, NOT a picture to paint or copy. Its top "
    "edge is the buildings (the blue outline is the awning over the vending bay, green the green building, beige the "
    "pale boundary wall, grey the shutters); the light-grey band is the pavement, the dark line the kerb drain, the "
    "dark band at the bottom the road. The maroon shape is the food three-wheeler, its cab to the left and its hatch "
    "(the light strip) at its right end. The red dot is Kasun's ground mark and the blue dot Anudi's; the small "
    "triangle on each dot points the way that person's chest faces; the ring around each dot is as far as a small "
    "movement may take them. The black triangle on the road is where the cameras of panels 1 to 5 stand, pointing "
    "the way they look. Take from image 3 only where each person stands and how far apart; never paint dots, rings, "
    "triangles or the map.")

PLATE_WORDS = (
    "Image 3 is the BLOCKING PLATE: one wide still of this very moment from view 1's anchor camera, the two "
    "mannequins standing on their ground marks. Take from image 3 only where each person stands on the ground, what "
    "stands behind each of them and the gap between them; every panel keeps them on exactly these spots, seen from "
    "its own camera. Not its framing, its light or its poses.")

# ── money ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def dollars(inp: int, out: int) -> float:
    return inp * PRICES[0] / 1e6 + out * PRICES[1] / 1e6


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def book(step: str, inp: int, out: int, note: str) -> float:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    usd = dollars(inp, out)
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "step", "model", "input_tokens", "output_tokens", "usd", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), step, MODEL, inp, out, f"{usd:.5f}", note])
    return usd


def worst(refs: list[Reference], prompt: str, quality: str) -> float:
    return dollars(1600 * len(refs) + len(prompt) // 3, 1500 if quality == "low" else 6500)


# ── inputs ────────────────────────────────────────────────────────────────────────────────────────────────────


def saved_prompt() -> str:
    return (IN / "board_part1_prompt.txt").read_text(encoding="utf-8")


def saved_refs() -> list[Reference]:
    meta = json.loads((IN / "refs.json").read_text(encoding="utf-8"))
    return [Reference(label=r["label"], data=(IN / r["file"]).read_bytes()) for r in meta]


def paragraph(prompt: str, head: str) -> str:
    m = re.search(rf"^{re.escape(head)}.*?(?=\n\n|\Z)", prompt, re.S | re.M)
    if m is None:
        raise SystemExit(f"the saved prompt has no paragraph starting {head!r}; fetch again")
    return m.group(0)


# ── the floor plan (B): drawn by code, no text ───────────────────────────────────────────────────────────────────

PX_PER_M = 120  # the pavement band is 3 m deep


def floor_plan() -> bytes:
    w, h = 1536, 1024
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    top, kerb = 200, 560  # pavement from the buildings (y=200) to the drain (y=560)
    # buildings along the top edge, left to right as the views sheet's Wide shows them
    d.rectangle([0, 0, 150, top], fill=(150, 150, 150))                   # shutters at the far left
    d.rectangle([150, 0, 500, top], fill=(200, 200, 200))                 # the building over the vending bay
    d.rectangle([500, 0, 900, top], fill=(70, 150, 70))                   # the green building
    d.rectangle([900, 0, 1300, top], fill=(225, 210, 175))                # the pale boundary wall
    d.rectangle([1300, 0, w, top], fill=(150, 150, 150))                  # shutters
    d.rectangle([0, top, w, kerb], fill=(215, 215, 215))                  # the pavement
    d.rectangle([0, kerb, w, kerb + 40], fill=(60, 60, 60))               # the kerb drain
    d.rectangle([0, kerb + 40, w, h], fill=(100, 100, 100))               # the road
    # the food three-wheeler in the bay: cab left, hatch at its right end
    d.rectangle([200, 250, 460, 420], fill=(110, 20, 30))
    d.rectangle([200, 250, 290, 420], fill=(25, 25, 25))                  # the black roof over the cab
    d.rectangle([440, 255, 460, 415], fill=(225, 225, 225))               # the hatch
    d.rectangle([150, top, 500, 440], outline=(30, 80, 200), width=8)     # the blue awning over the bay
    y = kerb - int(0.5 * PX_PER_M)                                        # half a metre in from the drain
    kasun, anudi = (530, y), (530 + int(1.2 * PX_PER_M), y)
    r = int(RADIUS_M * PX_PER_M)
    for (x, yy), colour, facing in ((kasun, (210, 30, 30), 1), (anudi, (30, 70, 210), -1)):
        d.ellipse([x - r, yy - r, x + r, yy + r], outline=colour, width=4)
        d.ellipse([x - 22, yy - 22, x + 22, yy + 22], fill=colour)
        tip = x + facing * 50
        d.polygon([(tip, yy), (x + facing * 24, yy - 16), (x + facing * 24, yy + 16)], fill=colour)
    cx = (kasun[0] + anudi[0]) // 2                                       # the road-facing cameras of panels 1-5
    d.polygon([(cx, 800), (cx - 30, 860), (cx + 30, 860)], fill=(0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ── the prompts ─────────────────────────────────────────────────────────────────────────────────────────────────


def with_marks(prompt: str) -> str:
    """The saved board prompt with the MARKS paragraph after Geography and a marks line on each panel."""
    geo = paragraph(prompt, "Geography:")
    out = prompt.replace(geo, geo + "\n\n" + MARKS, 1)
    for n, line in PANEL_MARKS.items():
        m = re.search(rf"^PANEL {n} \(row \d, column \d\) — ", out, re.M)
        if m is None:
            raise SystemExit(f"no PANEL {n} line in the saved prompt")
        out = out[: m.end()] + line + " " + out[m.end():]
    return out


def add_picture(prompt: str, words: str) -> str:
    refs = paragraph(prompt, "Reference images, in order:")
    return prompt.replace(refs, refs + " " + words, 1)


def board_prompt(arm: str) -> tuple[str, list[Reference]]:
    prompt, refs = with_marks(saved_prompt()), saved_refs()
    if arm == "B":
        prompt = add_picture(prompt, PLAN_WORDS)
        refs.append(Reference(label="the floor plan of the ground marks", data=floor_plan()))
    elif arm in ("C", "T"):
        plate = RUNS / ("plate" if arm == "C" else "plate_tall") / "plate.png"
        data = plate.read_bytes() if plate.exists() else floor_plan()  # a stand-in for `dry` before the plate
        prompt = add_picture(prompt, PLATE_WORDS)
        refs.append(Reference(label="the blocking plate of the ground marks", data=data))
    return prompt, refs


# ── phase 0 of plan/2026-11-24d: the next parts of the same chain (R, W) ─────────────────────────────────────────
#
# T_001 is scene 4's part 1 painted against the tall plate. R and W paint the board's parts 2 and 3 (v19's saved
# prompts) the way the product chains them: each gets the previous part's last panel (OUR T_001 / R_001, not v19's),
# the SAME tall plate, and the plan's own code words (`stretch_marks`, `PANEL_LINE`), not hand-written panel lines.
#   R  part 2 (shots 6-11): Anudi's singles from Kasun's end look obliquely along the pavement (view 3's side), then
#      shot 11's two-shot: does a camera that is not the plate's keep her spot, and part 2 the gap of part 1?
#   W  part 3 (shots 11-14) + two panels from the script's own block 18 ("Anudi walks toward her destination. Kasun
#      watches her leave. After a moment, he returns to his small business"): shot 15 opens the walk, shot 16 is
#      Kasun at his business. Stretch 1 = shots 1-15 (plate), stretch 2 = shot 16 (one shot: words only, no plate).
#      Does the plate let people LEAVE their marks?

STRETCH_1 = "shots 1 to 15"
SPOTS_1 = (
    "Kasun (the red mannequin) stands on the concrete pavement half a metre in from the kerb drain, one step to the "
    "right of the rear of the food three-wheeler, whose open service hatch and the blue awning above it are directly "
    "behind him and to his left. Anudi (the blue mannequin) stands on the same pavement, the same half metre in from "
    "the drain, about 1.2 metres to Kasun's right, in front of the green building, with the pale boundary wall "
    "beginning just to her right.")
SPOTS_2 = ("Kasun (the red mannequin) stands at the food three-wheeler's open service hatch, chest square to its "
           "serving counter, on the concrete of the vending bay. Anudi has gone.")


def stretch_marks(shots: str, spots: str, still: bool = True) -> str:
    """The plan's §3.3 paragraph: the lab's MARKS with the stretch's shots named and the writer's spots in it."""
    head = (f"Ground marks ({shots}): nobody walks in these shots, so each person stands on ONE spot on the ground "
            "for all of them, and every panel of them shows them on that same spot, seen from its own camera. "
            if still else f"Ground marks ({shots}): ")
    return (head + "Small movements (a turn of the head or body, a lean, a shift of weight, half a step) stay within "
            "half a metre of the mark; the feet never travel further. " + spots + " The gap between them is the same "
            "in every panel, about an arm's length and a little more between their chests, never touching: a closer "
            "camera makes them larger, never closer together. What is behind each of them follows from these spots "
            "and the panel's camera.")


PANEL_LINE = "Marks: on the ground marks of {shots}, the same gap as in every panel of them."
PLATE_CHAIN = (
    "Image {n} is the blocking plate for {shots}: one still of this place from view 1's anchor camera, the people "
    "standing on their ground marks. Take from image {n} only where each person stands on the ground, what stands "
    "behind each of them and the gap between them; every panel of {shots} keeps them on exactly these spots, seen "
    "from its own camera. Not its framing, its light or its poses.")

WALK_PANELS = {
    5: (15, "Return to shot 1's road-facing position at standing head height, approximately 1.6 metres; 35mm wide "
            "with both full figures and the onward pavement to frame right. Background view: view 1 (Wide).",
        "Marks: Kasun stays on his ground mark of shots 1 to 15; Anudi has left hers and walks away along the "
        "pavement toward screen right, about two metres beyond it.",
        "The blue mannequin has turned from the red mannequin and walks screen right along the wet concrete "
        "pavement, side-on and mid-stride, toward the pale boundary wall and the recessed shutters; the clay "
        "umbrella open in her left hand on the far side, the clay handbag on her left shoulder, the clay phone in her "
        "right hand at her side. The red mannequin stays on his mark beside the rear of the three-wheeler, chest "
        "angled right, head turned after her, both hands empty at his sides. Hands: the red mannequin: left hand "
        "empty, at his side; right hand empty, at his side. the blue mannequin: left hand grips the clay umbrella "
        "shaft on her far side; the clay handbag hangs from her left shoulder; right hand holds the clay phone at her "
        "side."),
    6: (16, "Standing head height on the road-facing side, square to the vending bay; 40mm medium-wide. Background "
            "view: view 1 (Wide).",
        "Marks: the ground mark of shot 16: Kasun at the three-wheeler's serving counter; nobody stands on the old "
        "marks.",
        "The red mannequin now stands at the food three-wheeler's open service hatch, chest square to the "
        "stainless-steel serving counter, both hands on its ledge, seen three-quarter from behind. The pavement to "
        "the right, where the two stood, is empty. Hands: the red mannequin: left hand flat on the counter's ledge; "
        "right hand flat on the counter's ledge."),
}


def chain_inputs(case: str) -> tuple[str, list[Reference]]:
    d = HERE / f"input_{case}"
    meta = json.loads((d / "refs.json").read_text(encoding="utf-8"))
    prev = RUNS / ("T_001" if case == "reverse" else "R_001") / "board.png"
    refs = []
    for r in meta:
        if r["label"].startswith("the approved last panel"):
            data = prev.read_bytes() if prev.exists() else (d / r["file"]).read_bytes()  # dry before the chain
            last = cells(data)[-1] if prev.exists() else Image.open(d / r["file"])
            buf = io.BytesIO()
            last.save(buf, format="PNG")
            refs.append(Reference(label=r["label"], data=buf.getvalue()))
        else:
            refs.append(Reference(label=r["label"], data=(d / r["file"]).read_bytes()))
    return (d / "board_part1_prompt.txt").read_text(encoding="utf-8"), refs


def chain_prompt(arm: str) -> tuple[str, list[Reference]]:
    prompt, refs = chain_inputs("reverse" if arm == "R" else "walkoff")
    n_old = len(re.findall(r"^PANEL \d+ \(row", prompt, re.M))
    if arm == "W":  # 4 panels in 2x2 become 6 in 3x2: the header, each panel's cell, the two walk panels
        prompt = prompt.replace("4 photorealistic film stills of ONE scene, laid out in a grid 2 panels across and 2 "
                                "down", "6 photorealistic film stills of ONE scene, laid out in a grid 3 panels "
                                "across and 2 down", 1)
        for k in range(1, n_old + 1):
            prompt = re.sub(rf"^PANEL {k} \(row \d, column \d\)", f"PANEL {k} (row {(k - 1) // 3 + 1}, column "
                            f"{(k - 1) % 3 + 1})", prompt, count=1, flags=re.M)
        last = list(re.finditer(r"^PANEL \d+ \(row.*$", prompt, re.M))[-1]
        extra = "".join(f"\nPANEL {k} (row {(k - 1) // 3 + 1}, column {(k - 1) % 3 + 1}) — {cam} {pic}"
                        for k, (_, cam, _, pic) in WALK_PANELS.items())
        prompt = prompt[: last.end()] + extra + prompt[last.end():]
        veh = paragraph(prompt, "Vehicles (every panel):")
        prompt = prompt.replace(veh, veh + " PANEL 5: the Food three-wheeler is in the vending bay, the same vehicle "
                                "as image 2. PANEL 6: the Food three-wheeler is in the vending bay, its hatch open, "
                                "the same vehicle as image 2.", 1)
    geo = paragraph(prompt, "Geography:")
    words = stretch_marks(STRETCH_1, SPOTS_1)
    if arm == "W":
        words += "\n\n" + stretch_marks("shot 16", SPOTS_2, still=False).replace(
            " The gap between them is the same in every panel, about an arm's length and a little more between their "
            "chests, never touching: a closer camera makes them larger, never closer together.", "")
    prompt = prompt.replace(geo, geo + "\n\n" + words, 1)
    for k in range(1, n_old + 1):  # the plan's generic line on each of the saved panels
        m = re.search(rf"^PANEL {k} \(row \d, column \d\) — ", prompt, re.M)
        prompt = prompt[: m.end()] + PANEL_LINE.format(shots=STRETCH_1) + " " + prompt[m.end():]
    if arm == "W":
        for k, (_, _, line, _) in WALK_PANELS.items():
            m = re.search(rf"^PANEL {k} \(row \d, column \d\) — ", prompt, re.M)
            prompt = prompt[: m.end()] + line + " " + prompt[m.end():]
    plate = RUNS / "plate_tall" / "plate.png"
    n = len(refs) + 1
    prompt = add_picture(prompt, PLATE_CHAIN.format(n=n, shots=STRETCH_1))
    refs.append(Reference(label=f"the blocking plate for {STRETCH_1}", data=plate.read_bytes()))
    return prompt, refs


def plate_prompt(tall: bool = False) -> tuple[str, list[Reference]]:
    """C's plate: ONE still from view 1's anchor camera, the board's own People/Props/World/Vehicles words. `tall`
    (arm T, after C_002's broken grid): painted at the panels' 9:16 shape instead of 16:9."""
    saved = saved_prompt()
    refs = saved_refs()
    head = paragraph(saved, "Reference images, in order:").replace(
        "Every panel below names the view its background comes from: paint that view's background, the same things "
        "on the same sides, seen from the panel's own camera (closer or tighter as the panel says). Never copy the "
        "sheet's gutters or layout.",
        "This still is painted from view 1 (Wide)'s camera: paint that view's place, the same things on the same "
        "sides. Never copy the sheet's gutters or layout.")
    keep = [paragraph(saved, h) for h in ("People (every panel):", "Props (every panel):", "World (every panel):")]
    keep = [k.replace(" (every panel)", "") for k in keep]
    prompt = "\n\n".join([
        "One photorealistic film still for a Sri Lankan television drama, "
        + ("a tall portrait 9:16 frame" if tall else "a wide 16:9 frame")
        + ": the blocking plate of a scene, which shows where each person stands. A single picture, no panels, no "
        "gutters.",
        head, *keep,
        "Vehicles: every vehicle is real, never clay, exactly as its vehicle sheet shows it: the Food three-wheeler "
        "is image 2, parked in the vending bay under the blue awning, its cab to the left and its open service hatch "
        "at its right end, all three wheels on the concrete of the bay.",
        MARKS.replace("Ground marks (every panel): nobody walks in panels 1 to 6, so each person stands on ONE spot "
                      "on the ground for the whole sheet, and every panel shows them on that same spot, seen from "
                      "its own camera.", "Ground marks:"),
        "The camera: view 1's anchor spot on the road, about two metres out from the drain, at standing eye height, "
        "square on to the pavement; a 28mm wide, both mannequins full length with their feet on the pavement, the "
        "whole three-wheeler, the awning, the green building and the start of the pale wall in frame. Kasun stands "
        "with his chest toward Anudi (screen right), both hands empty at his sides; Anudi stands with her chest "
        "toward Kasun (screen left), the clay umbrella open in her left hand, the clay handbag on her left shoulder, "
        "the clay phone in her right hand at her waist.",
        "Draw NO text of any kind. The people, place and everyday details are Sri Lankan.",
    ])
    return prompt, refs


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────


def paint(step: str, prompt: str, refs: list[Reference], aspect: str, quality: str, out: Path) -> bytes:
    w = worst(refs, prompt, quality)
    if spent() + w > LAB_BUDGET_USD:
        raise SystemExit(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
    blocked = safe_depiction.blocking(prompt)
    if blocked:
        raise SystemExit(f"NOT SENT: safe depiction blocks {blocked}")
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    t = time.time()
    pic = OpenAIImages(client(), model=MODEL, quality=quality)(prompt, aspect, refs, quality=quality)
    usd = book(step, pic.input_tokens, pic.output_tokens, f"{step} {quality}")
    print(f"{step}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
    return pic.data


def next_dir(arm: str) -> Path:
    n = 1 + max((int(p.name.split("_")[1]) for p in RUNS.glob(f"{arm}_*") if p.name.split("_")[1].isdigit()),
                default=0)
    return RUNS / f"{arm}_{n:03d}"


def cells(board: bytes) -> list[Image.Image]:
    return [Image.open(io.BytesIO(pics.crop(board, [int(v) for v in b]))).convert("RGB")
            for b in pics.cell_boxes(board, PANELS)]


def compare() -> Path:
    """One row per board (v18 first, then every arm's run), its six panels side by side, cut along the grid."""
    rows = [("v18", (IN / "board_part1.png").read_bytes())]
    rows += [(p.parent.name, p.read_bytes()) for p in sorted(RUNS.glob("[ABCTRW]_*/board.png"))]
    h, gap = 420, 10
    strips = []
    for _, data in rows:
        ims = [im.resize((round(im.width * h / im.height), h)) for im in cells(data)]
        strip = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), h), (255, 255, 255))
        x = 0
        for im in ims:
            strip.paste(im, (x, 0))
            x += im.width + gap
        strips.append(strip)
    out = Image.new("RGB", (max(s.width for s in strips), sum(s.height for s in strips) + gap * (len(strips) - 1)),
                    (255, 255, 255))
    y = 0
    for s in strips:
        out.paste(s, (0, y))
        y += s.height + gap
    path = RUNS / "compare.jpg"
    RUNS.mkdir(exist_ok=True)
    out.save(path, format="JPEG", quality=85)
    print("rows, top to bottom: " + ", ".join(name for name, _ in rows))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "plan", "plate", "board", "compare"])
    ap.add_argument("arm", nargs="?", choices=["A", "B", "C", "T", "R", "W"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()

    if args.mode == "plan":
        RUNS.mkdir(exist_ok=True)
        (RUNS / "floor_plan.png").write_bytes(floor_plan())
        print(RUNS / "floor_plan.png")
        return 0
    if args.mode == "compare":
        print(compare())
        return 0
    if args.mode == "dry":
        d = RUNS / "dry"
        d.mkdir(parents=True, exist_ok=True)
        items = ([("plate", *plate_prompt(), "16:9")] + [(f"board_{a}", *board_prompt(a), ASPECT) for a in "ABC"]
                 + [(f"board_{a}", *chain_prompt(a), ASPECT) for a in "RW"])
        total = 0.0
        for name, prompt, refs, _ in items:
            (d / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
            blocked = safe_depiction.blocking(prompt)
            total += worst(refs, prompt, "low")
            print(f"{name}: {len(prompt)} chars, {len(refs)} pictures; worst ${worst(refs, prompt, 'low'):.3f}"
                  f"{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"worst in all ${total:.3f}; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; prompts in {d}")
        return 0
    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode == "plate":
        tall = args.arm == "T"
        prompt, refs = plate_prompt(tall)
        out = RUNS / ("plate_tall" if tall else "plate")
        (out / "plate.png").parent.mkdir(parents=True, exist_ok=True)
        (out / "plate.png").write_bytes(paint("plate_tall" if tall else "plate", prompt, refs,
                                              ASPECT if tall else "16:9", "low", out))
        return 0
    if args.arm is None:
        print("board needs an arm: A, B, C or T")
        return 2
    if args.arm in ("C", "T") and not (RUNS / ("plate" if args.arm == "C" else "plate_tall") / "plate.png").exists():
        print("paint the plate first")
        return 2
    if args.arm == "R" and not (RUNS / "T_001" / "board.png").exists():
        print("R chains on T_001: paint T first")
        return 2
    if args.arm == "W" and not (RUNS / "R_001" / "board.png").exists():
        print("W chains on R_001: paint R first")
        return 2
    prompt, refs = chain_prompt(args.arm) if args.arm in ("R", "W") else board_prompt(args.arm)
    out = next_dir(args.arm)
    data = paint(f"board_{args.arm}", prompt, refs, ASPECT, "low", out)
    (out / "board.png").write_bytes(data)
    if args.arm == "B":
        (out / "floor_plan.png").write_bytes(refs[-1].data)
    count = {"R": 6, "W": 6}.get(args.arm, PANELS)
    problems = pics.cut_problems(data, pics.cell_boxes(data, count))
    print(f"cut: {'ok' if not problems else '; '.join(problems)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
