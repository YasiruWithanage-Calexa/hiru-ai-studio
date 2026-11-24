"""Vehicle role lab, case 2 (2026-11-24): Love Hour scene 2 "Anudi arrives" (6de06ab0) and the canon "Family car"
(L04, a BMW 520d). The vehicle's role CHANGES inside the scene: shot 1 is inside the moving car (the car IS the place),
the car then stops at the roadside (it STANDS IN the place), and later panels show the food three-wheeler there.

The saved approved board (v3, 2026-11-16) got only the roadside plate: a generic silver hatchback with a dark interior,
the driver in the back seat, a green three-wheeler.

    board   the SAVED v3 prompt (4 panels, LOW), changed only where vehicles are concerned: both vehicle plates attached
            with the vehicle-only job, the role of each vehicle in each panel, and the writer's two vehicle words that
            came from no picture ("silver-grey ... family car with a dark neutral interior", "muted-green food
            three-wheeler") replaced by the cards' own (in the product the writer would read the plates and the card).
    frame   shot 1 (1fc8a283) first frame, MEDIUM, written from the shot's own plan in the saved frame prompts'
            pattern (no frame was ever painted for it). Role "inside": the BMW plate is the place, the roadside plate is
            NOT attached, the street only through the windows; image 6 is panel 1 of this lab's board.

    .venv/Scripts/python.exe lab/vehicle_role/run_bmw.py dry
    .venv/Scripts/python.exe lab/vehicle_role/run_bmw.py board --yes
    .venv/Scripts/python.exe lab/vehicle_role/run_bmw.py frame --yes   (needs a board_bmw run)

Inputs are read-only copies (fetch_bmw.py, fetch_bmw_people.py: GET requests only). Nothing under `src/` changes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import run as lab  # noqa: E402  (the money, ledger and run folders of this lab)
from run import MODEL, Reference, book, next_run, pics, safe_depiction, side_by_side, spent, worst  # noqa: E402

LAB_BUDGET_USD = 1.00  # raised from $0.60 with the person's yes (2026-11-24)
IN = HERE / "input_bmw"
PANELS = 4

CAR = "Family car"
CAR_WORDS = "a pearl-silver 2019 BMW 520d four-door sedan"
JOB = ("ONLY the vehicle itself, exactly as shown: its make and model, body shape and colour, wheels, lights and "
       "windows{inside}. Ignore everything around the vehicle in that picture (its street, gate, trees, ground and "
       "light)")
CAR_JOB = JOB.format(inside=", and its inside: the charcoal dashboard, the right-hand steering wheel, the beige seats")
TUK_JOB = JOB.format(inside=", its side hatch and serving ledge")

REFS_OLD = ("Reference images, in order: image 1 is the location plate for Colombo roadside; image 2 is the reference "
            "sheet for phone. Take from image 1: the kind of place: its ground, water, plants, structures and "
            "materials. It is ONE view of the place; each panel has its own camera position, so do not repeat this "
            "view in every panel; image 2: phone exactly as shown.")
REFS_NEW = ("Reference images, in order: image 1 is the location plate for Colombo roadside; image 2 is the vehicle "
            f"plate for {CAR} ({CAR_WORDS}); image 3 is the vehicle plate for Food three-wheeler; image 4 is the "
            "reference sheet for phone. Take from image 1: the kind of place: its ground, water, plants, structures "
            "and materials. It is ONE view of the place; each panel has its own camera position, so do not repeat "
            f"this view in every panel; image 2: {CAR_JOB}; image 3: {TUK_JOB}; image 4: phone exactly as shown.")
WRITER_FIXES = [
    ("a silver-grey right-hand-drive family car with a dark neutral interior",
     f"the family car ({CAR_WORDS} with a beige interior, image 2)"),
    ("The muted-green food three-wheeler", "The maroon food three-wheeler (image 3)"),
]
ANCHOR = "\n\nGeography: "
VEHICLES = (
    "\n\nVehicles (every panel): every vehicle is real, never clay, exactly as its vehicle plate shows it: the family "
    f"car is image 2 ({CAR_WORDS}), the food three-wheeler is image 3. Where each one is, panel by panel: PANEL 1 is "
    "INSIDE the moving family car: the car is the place, with the beige rear bench, the charcoal dashboard and the "
    "right-hand steering wheel of image 2; the driver sits in the FRONT RIGHT-HAND seat behind the wheel, and Anudi "
    "sits alone on the rear bench; the street is seen only through the windows. PANEL 2: the family car is stopped "
    "at the kerb of the roadside, nose toward screen right, the same car as image 2. PANELS 3 and 4: the food "
    "three-wheeler is parked in the vending bay of the roadside, ahead along the pavement.")


def board_prompt() -> tuple[str, list[Reference]]:
    saved = json.loads((IN / "boards.json").read_text(encoding="utf-8"))[0]["prompt"]
    out = lab.swap(saved, REFS_OLD, REFS_NEW, "board references")
    for old, new in WRITER_FIXES:
        out = lab.swap(out, old, new, f"writer words {old[:30]!r}")
    out = lab.swap(out, ANCHOR, VEHICLES + ANCHOR, "vehicles line")
    refs = [Reference(label="the location plate for Colombo roadside",
                      data=(IN / "plate_Colombo_roadside.png").read_bytes()),
            Reference(label=f"the vehicle plate for {CAR}", data=(IN / "plate_Family_car.png").read_bytes()),
            Reference(label="the vehicle plate for Food three-wheeler",
                      data=(IN / "plate_Food_three_wheeler.png").read_bytes()),
            Reference(label="the reference sheet for phone", data=(lab.IN / "frame_ref_7.png").read_bytes())]
    return out, refs


# Shot 1, role "inside": written from the shot's own plan (ir: setting, subjects, first_frame, cinematography) in the
# pattern of the saved scene 4 frame prompt; the people's words are their cards and the scene look.
FRAME = (
    "Photorealistic still frame from a Sri Lankan romance and drama, shot on a cinema camera with real optics and "
    "natural imperfections. Reference images, in order: image 1 is the face sheet for Anudi; image 2 is the face "
    "sheet for driver; image 3 is the look sheet for Anudi; image 4 is the look sheet for driver; image 5 is the "
    f"vehicle plate for {CAR} ({CAR_WORDS}); image 6 is the approved scene board panel of this shot. Match them "
    "exactly: the same faces, hair, skin tone and build, the same car. Do not redesign anyone. Take from image 1: "
    "Anudi's face and age at every angle and expression: Anudi's face comes ONLY from this sheet; image 2: the "
    "driver's face and age: his face comes ONLY from this sheet; image 3: Anudi's clothes, shoes and accessories and "
    "hair in this scene, not the face, light or backdrop; image 4: the driver's clothes and hair, not the face, light "
    f"or backdrop; image 5: the car this shot happens in: {CAR_JOB}. "
    "The approved scene board panel shows this moment with the people as coloured mannequins: take from it where each "
    "person sits and which way they face, their posture and what each hand holds. Its camera, lens and framing are "
    "only a sketch: this shot's words decide the camera. Anudi is the red mannequin; the driver is the blue "
    "mannequin. Replace each mannequin with that real person. No mannequin, no plastic and none of the mannequin's "
    "colour remains anywhere in the frame. Nobody looks into the lens. "
    f"The place: this shot happens INSIDE the moving family car, {CAR_WORDS}. The car is the place: its beige rear "
    "bench, beige door panels, the charcoal dashboard and the right-hand steering wheel, exactly as image 5 shows its "
    "inside. The street is NOT a place of its own here: contemporary Colombo traffic and damp roadside frontages are "
    "seen only through the side windows, softly out of focus. "
    "Each person at the opening of this shot, as planned: Anudi sits on the rear seat on the pavement side, three-"
    "quarter face to camera, studying the smartphone in her right hand, eyes lowered to the screen, lips closed; her "
    "handbag on her left shoulder and the folded umbrella in her left hand. The driver sits in the front right-hand "
    "driving seat behind the steering wheel, both hands on the wheel, eyes on the road, soft at the edge of the frame "
    "in depth. "
    "This shot: a vehicle-mounted camera at eye level from the front passenger side, looking back at Anudi in a "
    "medium shot, 40mm lens look at f/4, medium depth of focus: Anudi fills the rear-seat middle of the image with "
    "the window beside her, the driver soft at one edge. "
    "Who they are: Anudi: 25, average height, slender build, medium warm-brown skin, a heart-shaped face, wide "
    "dark-brown eyes, gently arched eyebrows. Long lightly wavy black hair, side-parted and gathered into a low "
    "ponytail; as in her look sheet: dusty-rose three-quarter-sleeved blouse, navy ankle-length tailored trousers, "
    "small gold stud earrings, a tan structured handbag and a navy folding umbrella (folded). | driver: 46, slim "
    "straight-backed build, dark-brown skin, a long rectangular face, clean-shaven, short tightly curled black hair "
    "lightly silvered at the temples; plain pale-grey short-sleeved collared shirt. "
    "Lighting: overcast daylight enters from the pavement side, with gentle falloff across faces and the background "
    "slightly darker. Colour temperature: 5600K overcast daylight. Colour: naturalistic neutral colour, gentle "
    "highlights and restrained saturation. Scene mood: absorbed and sheltered. The people, place and everyday details "
    "are Sri Lankan. 9:16 vertical framing. A single still frame: no watermark, no captions, no collage, no split "
    "panels. Draw no text."
)


def latest_board() -> bytes | None:
    found = sorted((HERE / "runs").glob("run_*/board_bmw.png"))
    return found[-1].read_bytes() if found else None


def frame_prompt(board: bytes) -> tuple[str, list[Reference]]:
    boxes = pics.cell_boxes(board, PANELS)
    panel1 = pics.crop(board, [int(v) for v in boxes[0]])
    refs = [Reference(label="the face sheet for Anudi", data=(IN / "anudi_face.png").read_bytes()),
            Reference(label="the face sheet for driver", data=(IN / "driver_face.png").read_bytes()),
            Reference(label="the look sheet for Anudi", data=(IN / "anudi_look.png").read_bytes()),
            Reference(label="the look sheet for driver", data=(IN / "driver_look.png").read_bytes()),
            Reference(label=f"the vehicle plate for {CAR}", data=(IN / "plate_Family_car.png").read_bytes()),
            Reference(label="the approved scene board panel of this shot", data=panel1)]
    return FRAME, refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "board", "frame"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()
    board = latest_board()

    if args.mode == "dry":
        d = HERE / "runs" / "dry"
        d.mkdir(parents=True, exist_ok=True)
        stand_in = board or (IN / "board_0_v3_p1.png").read_bytes()
        for name, (prompt, refs), quality in (("board_bmw", board_prompt(), "low"),
                                              ("frame_bmw", frame_prompt(stand_in), "medium")):
            (d / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
            blocked = safe_depiction.blocking(prompt)
            print(f"{name}: {len(prompt)} chars, {len(refs)} pictures ({'; '.join(r.label for r in refs)}); worst "
                  f"${worst(refs, prompt, quality):.3f}{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
        return 0

    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode == "frame" and board is None:
        print("paint the board first")
        return 2
    if args.mode == "board":
        (prompt, refs), quality, step = board_prompt(), "low", "board_bmw"
    else:
        assert board is not None
        (prompt, refs), quality, step = frame_prompt(board), "medium", "frame_bmw"
    w = worst(refs, prompt, quality)
    if spent() + w > LAB_BUDGET_USD:
        print(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
        return 3
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    out = next_run()
    (out / f"{step}_prompt.txt").write_text(prompt, encoding="utf-8")
    painter = OpenAIImages(client(), model=MODEL, quality=quality)
    t = time.time()
    pic = painter(prompt, "9:16", refs, quality=quality)
    usd = book(out.name, step, pic.input_tokens, pic.output_tokens, f"{step} {quality}")
    (out / f"{step}.png").write_bytes(pic.data)
    if args.mode == "board":
        problems = pics.cut_problems(pic.data, pics.cell_boxes(pic.data, PANELS))
        print(f"cut: {'ok' if not problems else '; '.join(problems)}")
        (out / "compare_board_bmw.jpg").write_bytes(side_by_side((IN / "board_0_v3_p1.png").read_bytes(), pic.data))
    else:
        (out / "compare_frame_bmw.jpg").write_bytes(side_by_side((IN / "plate_Family_car.png").read_bytes(), pic.data))
    print(f"{step}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; "
          f"files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
