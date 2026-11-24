"""Vehicle role lab (2026-11-24): does a vehicle come out right when the scene says what ROLE it plays, instead of the
system finding it by name and painting it as clay?

The case: Love Hour scene 4 (de75bc31), "Colombo roadside" with Kasun's "Food three-wheeler" parked in it. The saved
board (part 1, shots 1-6) drew a white van in panels 1 and 3 and a lit shop in 2, 4 and 5, although its prompt already
said "Food three-wheeler ... never as clay". The saved first frame of shot 1 got a three-wheeler with a blue roof.

The three rules under test (theory, 2026-11-24):
    1. A vehicle is never a prop and never clay.
    2. The scene says where its vehicles are ("Vehicles in this scene: ... parked at the left of the pavement").
    3. The vehicle's own plate goes with every picture, with the job "this vehicle only, not its background".
Two roles: the vehicle STANDS IN the place (scene 4), or the vehicle IS the place (people inside it).

    board   the SAVED board prompt (part 1, LOW), changed only where vehicles are concerned: the three-wheeler plate
            attached as image 2 with the vehicle-only job, the clay-vehicle sentence replaced, one vehicles line.
    frame   shot 1's SAVED frame prompt (MEDIUM), changed only where vehicles are concerned: image 6 is the vehicle
            plate with the vehicle-only job, one vehicles line, and image 8 is panel 1 of this lab's board (the saved
            panel shows the white van).
    inside  role 2, made up for the lab (no such scene in Love Hour 4 yet): Kasun drives the three-wheeler home in
            evening rain; the three-wheeler plate is the place, the road only seen through the open sides (MEDIUM).

    .venv/Scripts/python.exe lab/vehicle_role/run.py dry
    .venv/Scripts/python.exe lab/vehicle_role/run.py board --yes
    .venv/Scripts/python.exe lab/vehicle_role/run.py frame --yes    (needs a board run)
    .venv/Scripts/python.exe lab/vehicle_role/run.py inside --yes

Nothing under `src/` changes and nothing is read from or written to the database: the inputs are copies of the saved
scene 4 data (lab/location_views/input). `src/` is only imported, read-only, for the image call and the panel cutter.
The ledger stops every call past the budget.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(HERE)]

from PIL import Image  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 1.00  # $0.60 asked first, raised to $1.00 with the person's yes (2026-11-24)
MODEL = "gpt-image-2"
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the other board labs)
LEDGER = HERE / "runs" / "ledger.csv"
IN = HERE / "input"
PANELS = 6

# ── the vehicle parts (the only words this lab changes) ─────────────────────────────────────────────────────

VEHICLE = "Food three-wheeler"
VEHICLE_JOB = ("ONLY the vehicle itself, exactly as shown: its body shape and colour, its roof, cab and windscreen, "
               "its side hatch, serving ledge and what stands on it. Ignore everything around the vehicle in that "
               "picture (its street, shop, tree, ground and light): the vehicle stands in this scene's place, in "
               "this scene's light")
WHERE = ("the Food three-wheeler is parked side-on in the vending bay at the left of the pavement, its serving hatch "
         "open toward the pavement. It is the same real vehicle in every picture and it does not move. The food "
         "business, its serving hatch, opening and shelter that the words mention are this three-wheeler")

BOARD_REFS_OLD = ("Reference images, in order: image 1 is the location plate for Colombo roadside. Take from image 1: "
                  "the kind of place: its ground, water, plants, structures and materials. It is ONE view of the "
                  "place; each panel has its own camera position, so do not repeat this view in every panel.")
BOARD_REFS_NEW = ("Reference images, in order: image 1 is the location plate for Colombo roadside; image 2 is the "
                  f"vehicle plate for {VEHICLE}. Take from image 1: the kind of place: its ground, water, plants, "
                  "structures and materials. It is ONE view of the place; each panel has its own camera position, so "
                  f"do not repeat this view in every panel. Take from image 2: {VEHICLE_JOB}.")
CLAY_OLD = " A vehicle that is a prop is a full-size white clay vehicle with its doors, windows and seats as shapes."
CLAY_NEW = (" A vehicle is never a clay stand-in: every vehicle is painted real, exactly as its vehicle plate shows "
            "it, with its real colours.")
BOARD_ANCHOR = "\n\nGeography: "
BOARD_VEHICLES = f"\n\nVehicles in this scene (every panel): {WHERE} (image 2)."

FRAME_LABEL_OLD = "image 6 is the location plate for Food three-wheeler"
FRAME_LABEL_NEW = "image 6 is the vehicle plate for Food three-wheeler"
FRAME_JOB_OLD = "image 6: the place and its fixtures, not its light or time of day"
FRAME_JOB_NEW = f"image 6: {VEHICLE_JOB}"
FRAME_ANCHOR = "The food three-wheeler, its serving hatch and shelter remain real parts of the location."
FRAME_VEHICLES = f" Vehicles in this scene: {WHERE} (image 6)."


# ── money (as lab/location_views) ────────────────────────────────────────────────────────────────────────────

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


# ── the prompts ──────────────────────────────────────────────────────────────────────────────────────────────

def swap(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{what}: expected the saved words once, found {text.count(old)}; the input changed")
    return text.replace(old, new)


def board_prompt() -> tuple[str, list[Reference]]:
    saved = json.loads((IN / "board_part1.json").read_text(encoding="utf-8"))["prompt"]
    out = swap(saved, BOARD_REFS_OLD, BOARD_REFS_NEW, "board references")
    out = swap(out, CLAY_OLD, CLAY_NEW, "board clay vehicle")
    out = swap(out, BOARD_ANCHOR, BOARD_VEHICLES + BOARD_ANCHOR, "board vehicles line")
    refs = [Reference(label="the location plate for Colombo roadside", data=(IN / "place_1.png").read_bytes()),
            Reference(label=f"the vehicle plate for {VEHICLE}", data=(IN / "place_2.png").read_bytes())]
    return out, refs


def panel(board: bytes, n: int) -> bytes:
    boxes = pics.cell_boxes(board, PANELS)
    return pics.crop(board, [int(v) for v in boxes[n - 1]])


def frame_prompt(board: bytes) -> tuple[str, list[Reference]]:
    saved = json.loads((IN / "frame_shot1.json").read_text(encoding="utf-8"))["prompt"]
    meta = json.loads((IN / "frame_refs.json").read_text(encoding="utf-8"))
    out = swap(saved, FRAME_LABEL_OLD, FRAME_LABEL_NEW, "frame image 6 label")
    out = swap(out, FRAME_JOB_OLD, FRAME_JOB_NEW, "frame image 6 job")
    out = swap(out, FRAME_ANCHOR, FRAME_ANCHOR + FRAME_VEHICLES, "frame vehicles line")
    refs = []
    for r in meta:
        if r["label"] == "the approved scene board panel of this shot":
            refs.append(Reference(label=r["label"], data=panel(board, 1)))
        elif r["label"] == f"the location plate for {VEHICLE}":
            refs.append(Reference(label=f"the vehicle plate for {VEHICLE}", data=(IN / r["file"]).read_bytes()))
        else:
            refs.append(Reference(label=r["label"], data=(IN / r["file"]).read_bytes()))
    return out, refs


# Role 2: the vehicle IS the place. Written in the saved frame prompt's own pattern; Kasun's words are the saved ones.
INSIDE = (
    "Photorealistic still frame from a Sri Lankan romance and drama, shot on a cinema camera with real optics and "
    "natural imperfections. Reference images, in order: image 1 is the face sheet for Kasun; image 2 is the look sheet "
    f"for Kasun; image 3 is the vehicle plate for {VEHICLE}. Match them exactly: the same face, hair, skin tone and "
    "build, the same vehicle. Do not redesign anyone. Take from image 1: Kasun's face and age at every angle and "
    "expression: Kasun's face comes ONLY from this sheet; image 2: Kasun's clothes, shoes and accessories and hair in "
    "this scene, not the face, light or backdrop; image 3: the vehicle this scene happens in: ONLY the vehicle itself, "
    "exactly as shown: its maroon body, black vinyl roof, small front cab, windscreen and the food counter behind the "
    "driver. Ignore everything around the vehicle in that picture (its street, shop, tree, ground and light). "
    "The place: this scene happens INSIDE the Food three-wheeler while Kasun drives it home. The three-wheeler is the "
    "place: its cab, the black vinyl roof over his head, the windscreen in front of him, the handlebar in his hands. "
    "The world outside is seen only through the open sides and the windscreen: a wet Colombo road in light evening "
    "rain, low shopfronts with amber lights sliding past, softly out of focus. It is not a set of its own and nothing "
    "of it comes from a picture. "
    "This shot: a vehicle-mounted camera low inside the front of the cab, just behind the windscreen, looking back at "
    "Kasun in a medium close-up. A natural 35mm lens look at f/2.8. Kasun sits squarely on the driver's seat, centred "
    "behind the handlebar, both hands on its grips, back upright, eyes on the road just past the lens, a tired, quiet "
    "face. Behind him the back of the cab and the edge of the food counter; through the open sides at frame left and "
    "right the wet road and the shop lights pass by. "
    "Who he is: Kasun: Medium height, lean wiry build, deep warm-brown skin, a narrow oval face with pronounced "
    "cheekbones, dark-brown eyes and a small rounded chin. Short black wavy hair with close-cut sides and a consistent "
    "side sweep; neat short stubble and a faint moustache; as in his look sheet: outfit Faded teal short-sleeved "
    "cotton shirt, charcoal straight-leg trousers, plain dark sandals and a clean dark-brown waist apron tied at the "
    "back; in this scene: hair and shirt shoulders lightly damp. "
    "Lighting: cool blue evening daylight from the open sides, warm amber shop light passing across his face from "
    "frame left. Weather: light rain outside; the cab is dry. Colour: naturalistic warm skin, muted greens and "
    "maroon. Scene mood: tired, thoughtful. Nobody looks into the lens. The people, place and everyday details are "
    "Sri Lankan. 9:16 vertical framing. A single still frame: no watermark, no captions, no collage, no split panels. "
    "Draw no text."
)


def inside_prompt() -> tuple[str, list[Reference]]:
    meta = {r["label"]: r["file"] for r in json.loads((IN / "frame_refs.json").read_text(encoding="utf-8"))}
    refs = [Reference(label="the face sheet for Kasun", data=(IN / meta["the face sheet for Kasun"]).read_bytes()),
            Reference(label="the look sheet for Kasun", data=(IN / meta["the look sheet for Kasun"]).read_bytes()),
            Reference(label=f"the vehicle plate for {VEHICLE}", data=(IN / "place_2.png").read_bytes())]
    return INSIDE, refs


# ── side-by-side pictures for reading the result ────────────────────────────────────────────────────────────

def side_by_side(left: bytes, right: bytes, height: int = 900) -> bytes:
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in (left, right)]
    ims = [im.resize((round(im.width * height / im.height), height)) for im in ims]
    out = Image.new("RGB", (sum(im.width for im in ims) + 16, height), (255, 255, 255))
    out.paste(ims[0], (0, 0))
    out.paste(ims[1], (ims[0].width + 16, 0))
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────

def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()), default=0)
    out = runs / f"run_{n:03d}"
    out.mkdir()
    return out


def latest_board() -> bytes | None:
    found = sorted((HERE / "runs").glob("run_*/board.png")) if (HERE / "runs").exists() else []
    return found[-1].read_bytes() if found else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "board", "frame", "inside"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()
    board = latest_board()

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        stand_in = board or (IN / "board_part1.png").read_bytes()  # any board, to build the frame prompt
        for name, (prompt, refs), quality in (("board", board_prompt(), "low"),
                                              ("frame", frame_prompt(stand_in), "medium"),
                                              ("inside", inside_prompt(), "medium")):
            (d / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
            blocked = safe_depiction.blocking(prompt)
            print(f"{name}: {len(prompt)} chars, {len(refs)} pictures ({'; '.join(r.label for r in refs)}); worst "
                  f"${worst(refs, prompt, quality):.3f}{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; prompts in {d}")
        return 0

    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode == "frame" and board is None:
        print("paint the board first")
        return 2
    if args.mode == "board":
        prompt, refs = board_prompt()
        quality = "low"
    elif args.mode == "frame":
        assert board is not None
        prompt, refs = frame_prompt(board)
        quality = "medium"
    else:
        prompt, refs = inside_prompt()
        quality = "medium"
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
    pic = painter(prompt, "9:16", refs, quality=quality)
    usd = book(out.name, args.mode, pic.input_tokens, pic.output_tokens, f"{args.mode} {quality}")
    (out / f"{args.mode}.png").write_bytes(pic.data)
    if args.mode == "board":
        problems = pics.cut_problems(pic.data, pics.cell_boxes(pic.data, PANELS))
        print(f"cut: {'ok' if not problems else '; '.join(problems)}")
        (out / "compare_board.jpg").write_bytes(side_by_side((IN / "board_part1.png").read_bytes(), pic.data))
    elif args.mode == "frame":
        (out / "compare_frame.jpg").write_bytes(side_by_side((IN / "frame_shot1.png").read_bytes(), pic.data))
    print(f"{args.mode}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; "
          f"files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
