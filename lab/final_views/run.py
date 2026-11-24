"""Final views + vehicles lab (2026-11-24): plan/2026-11-24c (place views by type) and plan/2026-11-24b (vehicles)
together, on four shots of ONE scene, the product's way: a board first, then each shot's first frame from its panel.

The case: Love Hour scene 2 "Anudi arrives" (6de06ab0). The sheets are the labs' own:
    roadside   lab/place_views r2 (outside template, the three-wheeler bay kept EMPTY)
    BMW        lab/place_views r1 (vehicle template: front 3/4, side, rear 3/4, inside from the rear, inside from the
               front, dashboard)
    three-wheeler  its canon plate (lab/vehicle_role input/place_2.png): no vehicle sheet was painted for it

    shot 1  inside the moving BMW          role inside: BMW view 5 "Inside from the front" is the place, no roadside
    shot 2  the car stops at the kerb      role at: roadside view 4 "Reverse" + BMW view 2 "Side"
    shot 4  Anudi beside the open door     role at: roadside view 4 "Reverse" + BMW view 2 "Side"
    shot 7  Anudi under the umbrella, the three-wheeler ahead   role at: roadside view 1 "Wide" + the three-wheeler
            plate, parked in the empty bay

The words follow the product's board and frame prompts (the saved scene 2 and 4 prompts) with the lab-proven vehicle
words (`lab/vehicle_role`) and view words (`lab/location_views`, `lab/place_views`). One change, said here as the
plans ask: a view's job adds "not its light, weather or wet ground" (the roadside sheet is wet; shots 1-5 are dry).

    .venv/Scripts/python.exe lab/final_views/run.py dry
    .venv/Scripts/python.exe lab/final_views/run.py board --yes
    .venv/Scripts/python.exe lab/final_views/run.py frame <1|2|4|7|all> --yes   (needs the board)

Nothing under `src/` changes and nothing is read from or written to the database (inputs are the other labs' copies).
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parent
sys.path[:0] = [str(ROOT / "src" / "libs"), str(LAB)]

from PIL import Image  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 1.30  # the person's yes (2026-11-24): about $0.80 expected, $1.30 for the worst-case check
MODEL = "gpt-image-2"
PRICES = (10.00, 40.00)
LEDGER = HERE / "runs" / "ledger.csv"

ROADSIDE_SHEET = LAB / "place_views" / "runs" / "r2" / "sheets" / "roadside" / "sheet.png"
CAR_SHEET = LAB / "place_views" / "runs" / "r1" / "sheets" / "car" / "sheet.png"
TUK_PLATE = LAB / "vehicle_role" / "input" / "place_2.png"
PHONE = LAB / "vehicle_role" / "input" / "frame_ref_7.png"
PEOPLE = LAB / "vehicle_role" / "input_bmw"

ROAD_VIEWS = ["Wide", "Looking left", "Looking right", "Reverse", "Detail 1", "Detail 2"]
CAR_VIEWS = ["Front three-quarter", "Side", "Rear three-quarter", "Inside from the rear", "Inside from the front",
             "Detail"]
CAR = "Family car (a pearl-silver 2019 BMW 520d four-door sedan)"
TUK = "Food three-wheeler (an older maroon three-wheeler with a black vinyl roof and a food counter hatch)"
BAY = ("the compact vending bay beside the lit shop under the blue awning, at the edge of the pavement, which the "
       "location sheet shows empty")

VEHICLE_JOB = ("ONLY the vehicle itself, exactly as shown: its make and model, body shape and colour, wheels, lights "
               "and windows{inside}. Ignore everything around the vehicle in that picture (its floor, walls and light)")
VIEW_JOB = ("the background exactly as this view shows it, the same things on the same sides, seen from this shot's "
            "own camera, not its light, weather or wet ground")

# shot -> (panel, role, road view (1-based or 0), car view (1-based or 0), three-wheeler, people on screen)
SHOTS = {
    1: (1, "inside", 0, 5, False, ["Anudi", "driver"]),
    2: (2, "at", 4, 2, False, ["Anudi", "driver"]),
    4: (3, "at", 4, 2, False, ["Anudi"]),
    7: (4, "at", 1, 0, True, ["Anudi"]),
}

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


# ── pictures ──────────────────────────────────────────────────────────────────────────────────────────────────


def crop(sheet: Path | bytes, n: int, cells: int = 6) -> bytes:
    data = sheet.read_bytes() if isinstance(sheet, Path) else sheet
    return pics.crop(data, [int(v) for v in pics.cell_boxes(data, cells)[n - 1]])


def board_png() -> bytes | None:
    p = HERE / "runs" / "board" / "board.png"
    return p.read_bytes() if p.exists() else None


# ── the board (the product's board prompt pattern, scene 2 board v3's world, the new sheets) ──────────────────────

PANELS = {
    1: ("Seated eye height from the front-passenger side of the moving car, looking back at the rear seat; 40mm "
        "medium shot. Background view: view 5 (Inside from the front) of the vehicle sheet for the Family car.",
        "The red mannequin sits on the pavement-side end of the rear bench, chest facing the front of the car, head "
        "tilted down toward the clay phone in its right hand above its lap; the clay handbag on its left shoulder and "
        "the folded clay umbrella upright in its left hand. At one edge of the frame, soft in depth, the blue "
        "mannequin sits in the front right-hand driving seat behind the steering wheel, both hands on the rim. "
        "Through the side windows, softly out of focus, Colombo traffic and damp frontages pass."),
    2: ("Standing at eye height on the pavement, looking across the kerb at the stopped car; 35mm wide. Background "
        "view: view 4 (Reverse) of the location sheet for Colombo roadside.",
        "The family car stands at the kerb in a side three-quarter view, nose toward screen right, its pavement-side "
        "rear door closed and fully visible. Through the rear side window the red mannequin sits looking down at the "
        "clay phone; through the front window the blue mannequin sits at the wheel. The dry pavement and kerb run "
        "across the lower frame; the route continues screen right."),
    3: ("Standing on the pavement at a forward three-quarter angle, 50mm; waist-up. Background view: view 4 "
        "(Reverse) of the location sheet for Colombo roadside.",
        "The red mannequin stands on the dry pavement beside the fully open rear door of the family car, its right "
        "forearm near the door's outer edge, the clay phone in its right hand, the clay handbag on its left shoulder "
        "and the folded clay umbrella in its left hand; the edge of the open door and the silver car body behind "
        "it."),
    4: ("Eye level from the streetward side of the pavement; 35mm wide. Background view: view 1 (Wide) of the "
        "location sheet for Colombo roadside.",
        "The red mannequin stands at frame left under the open clay umbrella held in its left hand, the clay phone in "
        "its right hand, the clay handbag on its left shoulder. The food three-wheeler is parked at centre-right in "
        "the vending bay beside the lit shop, its plain outer side toward camera, nobody in it. Light rain falls; "
        "the pavement is wet and the route continues screen right."),
}


def board_prompt() -> tuple[str, list[Reference]]:
    refs = [Reference(label="the location sheet for Colombo roadside: six named views of the one place",
                      data=ROADSIDE_SHEET.read_bytes()),
            Reference(label=f"the vehicle sheet for {CAR}: six named views of the one car",
                      data=CAR_SHEET.read_bytes()),
            Reference(label=f"the vehicle plate for {TUK}", data=TUK_PLATE.read_bytes())]
    road = "; ".join(f"view {i} {n}" for i, n in enumerate(ROAD_VIEWS, 1))
    car = "; ".join(f"view {i} {n}" for i, n in enumerate(CAR_VIEWS, 1))
    panels = "\n".join(f"PANEL {n} (row {(n - 1) // 2 + 1}, column {(n - 1) % 2 + 1}) — {cam} {pic}"
                       for n, (cam, pic) in PANELS.items())
    prompt = "\n\n".join([
        "A cinematic storyboard sheet for a Sri Lankan television drama: 4 photorealistic film stills of ONE scene, "
        "laid out in a grid 2 panels across and 2 down, read left to right, then top to bottom. Every panel is a tall "
        "portrait 9:16 still of the same size, separated by thin, even, plain white gutters. All panels are the same "
        "moment's world, painted together: the same people, props, light and colour grade in every panel.",
        f"Reference images, in order: image 1 is {refs[0].label}, numbered left to right, then top to bottom: {road}. "
        "Take from image 1 the place itself: its buildings, its fixed things, the pavement and the drain, their "
        "materials and where each one stands. Every panel below names the view its background comes from: paint that "
        "view's background, the same things on the same sides, seen from the panel's own camera (closer or tighter as "
        "the panel says). Never copy the sheet's gutters or layout. "
        f"Image 2 is {refs[1].label}, numbered the same way: {car}. Take from image 2: "
        + VEHICLE_JOB.format(inside=", and its inside: the charcoal dashboard, the right-hand steering wheel, "
                             "the beige seats") + f". Image 3 is {refs[2].label}. Take from image 3: "
        + VEHICLE_JOB.format(inside=", its side hatch and serving ledge") + ".",
        "People (every panel): every person is a smooth, matte, faceless artist's mannequin in one solid colour, with "
        "jointed limbs and simple hands: Anudi is the red mannequin; driver is the blue mannequin. A small raised "
        "ridge on the front of the head, where a nose would be, shows which way the head faces. Each mannequin has the "
        "person's real height and build and sits, stands and holds things exactly as a real person would. No faces, "
        "no hair, no clothes, no skin: only the mannequin colour. Everything else (the place, the vehicles, the light, "
        "the weather) is a real, photorealistic film still.",
        "Props (every panel): every prop (phone, handbag, umbrella) and every small thing a person holds or carries is "
        "a plain, smooth, matte white clay stand-in of the real object: its real size and outline, and nothing else. "
        "A vehicle is never a clay stand-in: every vehicle is painted real, exactly as its vehicle sheet or plate "
        "shows it, with its real colours. The place itself is real, painted as a real photograph, never as clay.",
        "World (every panel): soft overcast early-morning daylight with a neutral, restrained grade, grey asphalt, "
        "dusty concrete and muted green surfaces. The ground is DRY in panels 1 to 3; light rain begins only in "
        "panel 4, wetting the pavement.",
        f"Vehicles (every panel): the family car is image 2 ({CAR}); the food three-wheeler is image 3. Where each "
        "one is, panel by panel: PANEL 1 is INSIDE the moving family car: the car is the place, its inside exactly as "
        "image 2's view 5 shows it; the street is seen only through the windows. PANELS 2 and 3: the family car is "
        "stopped at the kerb of the roadside, nose toward screen right, the same car as image 2. PANEL 4: the food "
        f"three-wheeler is parked in {BAY}; the family car has driven on and is not in the panel.",
        "Geography: one narrow Colombo pavement beside patched asphalt and an open kerb drain; the shuttered "
        "frontages, the two-storey building with the balcony and its lit shop under the blue awning stand along the "
        "pavement, with the vending bay beside the shop. The car stops at the kerb before the vending bay; Anudi's "
        "route runs screen left to right toward the bay.",
        panels,
        "Bodies (every panel): each person sits or stands the way a real person does the task in front of them, never "
        "posed for the camera. Someone at a steering wheel sits squarely behind it, the wheel centred in front of the "
        "chest, both hands on the rim. Nobody looks into or faces the lens.",
        "Draw NO text of any kind: no panel numbers, no captions, no titles, no arrows, no labels, no borders other "
        "than the gutters. The people, place and everyday details are Sri Lankan.",
    ])
    return prompt, refs


# ── the frames (the product's frame prompt pattern, as run_bmw.py FRAME) ──────────────────────────────────────────

PERSON = {
    "Anudi": ("Anudi: 25, average height, slender build, medium warm-brown skin, a heart-shaped face, wide dark-brown "
              "eyes, gently arched eyebrows. Long lightly wavy black hair, side-parted and gathered into a low "
              "ponytail; as in her look sheet: dusty-rose three-quarter-sleeved blouse, navy ankle-length tailored "
              "trousers, tan low-heeled closed shoes, small gold stud earrings, a tan structured handbag and a navy "
              "folding umbrella."),
    "driver": ("driver: 46, slim straight-backed build, dark-brown skin, a long rectangular face, clean-shaven, short "
               "tightly curled black hair lightly silvered at the temples; plain pale-grey short-sleeved collared "
               "shirt."),
}
SHOT_WORDS = {
    1: ("Each person at the opening of this shot: Anudi sits on the rear seat on the pavement side, three-quarter face "
        "to camera, studying the smartphone in her right hand, eyes lowered to the screen, lips closed; her handbag "
        "on her left shoulder and the folded umbrella in her left hand. The driver sits in the front right-hand "
        "driving seat behind the steering wheel, both hands on the wheel, eyes on the road, soft at the edge of the "
        "frame in depth. This shot: a vehicle-mounted camera at eye level from the front passenger side, looking back "
        "at Anudi in a medium shot, 40mm lens look at f/4. Lighting: overcast daylight enters from the pavement side. "
        "Weather outside: dry, overcast. Scene mood: absorbed and sheltered."),
    2: ("Each person at the opening of this shot: Anudi is seen seated behind the closed rear window, head lowered to "
        "her phone; the driver sits at the wheel behind the front window. This shot: tripod at pavement-side eye "
        "level, 35mm at f/5.6, a wide shot: the car in side three-quarter view facing screen right, its pavement-side "
        "rear door fully visible, the office route continuing screen right. Lighting: overcast daylight from the "
        "street side, restrained highlights on the car. Weather: dry, overcast; the pavement is dry. Scene mood: "
        "arrival, ordinary morning."),
    4: ("Each person at the opening of this shot: Anudi stands beside the fully open rear door, her right forearm near "
        "its outer edge, the smartphone in her right hand, the handbag on her left shoulder and the folded umbrella "
        "in her left hand, looking ahead along the pavement. This shot: tripod at a pavement-side forward "
        "three-quarter angle, 50mm at f/4, a medium shot from the waist up with the edge of the rear door visible. "
        "Lighting: overcast daylight from the street side, gentle face shadows. Weather: dry, overcast; the pavement "
        "is dry. Scene mood: composed, starting her day."),
    7: ("Each person at the opening of this shot: Anudi stands at frame left under the open umbrella held in her left "
        "hand, the smartphone in her right hand, the handbag on her left shoulder, facing screen right along the "
        "pavement. This shot: tripod at eye level from the streetward side of the pavement, 35mm at f/5.6, a wide "
        "shot showing Anudi, the open umbrella and the food three-wheeler at centre-right, the office route "
        "continuing screen right. Lighting: overcast daylight from the street side, restrained rain highlights. "
        "Weather: light rain is beginning; the pavement is turning wet. Scene mood: calm, a little hurried."),
}


def frame_prompt(shot: int, board: bytes) -> tuple[str, list[Reference]]:
    panel, role, road, car, tuk, people = SHOTS[shot]
    refs: list[Reference] = []
    jobs: list[str] = []
    for name in people:
        short = name.lower()
        refs.append(Reference(label=f"the face sheet for {name}", data=(PEOPLE / f"{short}_face.png").read_bytes()))
        jobs.append(f"{name}'s face and age at every angle and expression: {name}'s face comes ONLY from this sheet")
    for name in people:
        short = name.lower()
        refs.append(Reference(label=f"the look sheet for {name}", data=(PEOPLE / f"{short}_look.png").read_bytes()))
        jobs.append(f"{name}'s clothes, shoes and accessories and hair in this scene, not the face, light or backdrop")
    if road:
        refs.append(Reference(label=f"view {road} ({ROAD_VIEWS[road - 1]}) of the location sheet for Colombo roadside",
                              data=crop(ROADSIDE_SHEET, road)))
        jobs.append(VIEW_JOB)
    if car:
        refs.append(Reference(label=f"view {car} ({CAR_VIEWS[car - 1]}) of the vehicle sheet for {CAR}",
                              data=crop(CAR_SHEET, car)))
        jobs.append(("the car this shot happens in, its inside exactly as shown: the beige seats and door panels, the "
                     "charcoal dashboard and the right-hand steering wheel; ignore its light") if role == "inside" else
                    VEHICLE_JOB.format(inside=""))
    if tuk:
        refs.append(Reference(label=f"the vehicle plate for {TUK}", data=TUK_PLATE.read_bytes()))
        jobs.append(VEHICLE_JOB.format(inside=", its side hatch and serving ledge"))
    refs.append(Reference(label="the reference sheet for phone (held by Anudi)", data=PHONE.read_bytes()))
    jobs.append("phone exactly as shown")
    refs.append(Reference(label="the approved scene board panel of this shot", data=crop(board, panel, 4)))
    labels = "; ".join(f"image {i} is {r.label}" for i, r in enumerate(refs, 1))
    takes = "; ".join(f"image {i}: {j}" for i, j in enumerate(jobs, 1))
    colours = "Anudi is the red mannequin" + ("; the driver is the blue mannequin" if "driver" in people else "")
    if role == "inside":
        place = (f"The place: this shot happens INSIDE the moving family car, {CAR}. The car is the place: its beige "
                 "rear bench, beige door panels, the charcoal dashboard and the right-hand steering wheel, exactly as "
                 "its vehicle sheet shows its inside. The street is NOT a place of its own here: contemporary Colombo "
                 "traffic and damp roadside frontages are seen only through the side windows, softly out of focus.")
    elif tuk:
        place = (f"The place: Colombo roadside, as its view shows it. Vehicles in this shot: the food three-wheeler is "
                 f"parked in {BAY}, its plain outer side toward camera, nobody in it; it is the same real vehicle as "
                 "its plate. No other vehicle is parked here.")
    else:
        place = (f"The place: Colombo roadside, as its view shows it. Vehicles in this shot: the family car, {CAR}, is "
                 "stopped at the kerb, nose toward screen right, the same car as its vehicle sheet shows.")
    prompt = " ".join([
        "Photorealistic still frame from a Sri Lankan romance and drama, shot on a cinema camera with real optics and "
        f"natural imperfections. Reference images, in order: {labels}. Match them exactly: the same faces, hair, skin "
        f"tone and build, the same place and vehicles. Do not redesign anyone. Take from {takes}.",
        "The approved scene board panel shows this moment with the people as coloured mannequins and the props as "
        "white clay stand-ins: take from it where each person stands or sits and which way they face, their posture, "
        "what each hand holds, where each vehicle is and the place behind them. Its camera, lens and framing are only "
        f"a sketch: this shot's words decide the camera. {colours}. Replace each mannequin with that real person and "
        "each clay stand-in with the real prop. No mannequin, no plastic, no white clay shape and none of the "
        "mannequin's colour remains anywhere in the frame. Nobody looks into the lens.",
        place,
        SHOT_WORDS[shot],
        "Who they are: " + " | ".join(PERSON[p] for p in people),
        "Colour: naturalistic neutral colour, gentle highlights and restrained saturation, 5600K overcast daylight. "
        "The people, place and everyday details are Sri Lankan. 9:16 vertical framing. A single still frame: no "
        "watermark, no captions, no collage, no split panels. Draw no text.",
    ])
    return prompt, refs


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────


def side_by_side(images: list[bytes], height: int = 900) -> bytes:
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    ims = [im.resize((round(im.width * height / im.height), height)) for im in ims]
    out = Image.new("RGB", (sum(im.width for im in ims) + 16 * (len(ims) - 1), height), (255, 255, 255))
    x = 0
    for im in ims:
        out.paste(im, (x, 0))
        x += im.width + 16
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def paint(step: str, prompt: str, refs: list[Reference], quality: str, out: Path) -> bytes:
    w = worst(refs, prompt, quality)
    if spent() + w > LAB_BUDGET_USD:
        raise SystemExit(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    t = time.time()
    pic = OpenAIImages(client(), model=MODEL, quality=quality)(prompt, "9:16", refs, quality=quality)
    usd = book(step, pic.input_tokens, pic.output_tokens, f"{step} {quality}")
    print(f"{step}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
    return pic.data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "board", "frame"])
    ap.add_argument("shot", nargs="?", default="all")
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()
    shots = list(SHOTS) if args.shot == "all" else [int(args.shot)]

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        stand_in = board_png() or (PEOPLE / "board_0_v3_p1.png").read_bytes()
        items = [("board", *board_prompt(), "low")] + [(f"frame_{s}", *frame_prompt(s, stand_in), "medium")
                                                         for s in SHOTS]
        total = 0.0
        for name, prompt, refs, quality in items:
            (d / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
            blocked = safe_depiction.blocking(prompt)
            total += worst(refs, prompt, quality)
            print(f"{name}: {len(prompt)} chars, {len(refs)} pictures ({'; '.join(r.label for r in refs)}); worst "
                  f"${worst(refs, prompt, quality):.3f}{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"worst in all ${total:.3f}; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; prompts in {d}")
        return 0
    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode == "board":
        prompt, refs = board_prompt()
        data = paint("board", prompt, refs, "low", HERE / "runs" / "board")
        (HERE / "runs" / "board" / "board.png").write_bytes(data)
        problems = pics.cut_problems(data, pics.cell_boxes(data, 4))
        print(f"cut: {'ok' if not problems else '; '.join(problems)}")
        return 0
    board = board_png()
    if board is None:
        print("paint the board first")
        return 2
    for s in shots:
        prompt, refs = frame_prompt(s, board)
        out = HERE / "runs" / f"frame_{s}"
        data = paint(f"frame_{s}", prompt, refs, "medium", out)
        (out / "frame.png").write_bytes(data)
        (out / "compare.jpg").write_bytes(side_by_side([crop(board, SHOTS[s][0], 4), data]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
