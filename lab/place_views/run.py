"""Place views lab (2026-11-24): can ONE sheet of a place's main possible views be written and painted at CANON time
(before any shot exists), from a fixed template per type of place, with the AI writing what each view shows?

The person's rule (2026-11-24): shots are made after the canon, so a sheet cannot follow shots; it covers the place's
main possible views, so the image model later finds a view facing roughly the way any camera faces. The list of kinds of
place is unlimited, so no template per kind: three answers about the place pick one of four FIXED templates (always six
views, one 3x2 sheet code can cut), and the AI writes each view's content.

    answers   sides: outside | inside | both;  moves: a vehicle or not;  size: small | room | long
    template  vehicle if it moves, else by its sides (TEMPLATES below)

One place of each type from Love Hour: Colombo roadside (outside, has a plate), KASUN'S Restaurant (both, no plate),
Kasun's small food preparation workspace (inside, no plate), Family car = BMW 520d (vehicle, has a plate).

    .venv/Scripts/python.exe lab/place_views/fetch.py               (read-only GETs, already run)
    .venv/Scripts/python.exe lab/place_views/run.py dry             (the writer's prompt for every place, $0)
    .venv/Scripts/python.exe lab/place_views/run.py write --yes     (gpt-5-mini, one call per place: answers + views)
    .venv/Scripts/python.exe lab/place_views/run.py paint <place> --yes   (one sheet, MEDIUM; or `all`)

Nothing under `src/` changes and nothing is written to the database. `src/` is only imported, read-only, for the image
call and the cutter. The ledger stops every call past the budget.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import sys
import time
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(HERE)]

from PIL import Image, ImageDraw  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 0.80  # $0.60 asked first; raised to $0.80 with the person's yes (2026-11-24) for the worst-case check of r2
IMAGE_MODEL, TEXT_MODEL, EFFORT = "gpt-image-2", "gpt-5-mini", "medium"
IMAGE_PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the board labs)
TEXT_PRICES = (0.25, 2.00)  # gpt-5-mini list price per 1M input / output tokens (lab/cinematic PRICES)
LEDGER = HERE / "runs" / "ledger.csv"
IN = HERE / "input"
# Revision 2 (2026-11-24, after r1's read): one camera spot for the outside turns (r1's "Looking left/right" faced the
# same frontage); spaces where a thing that comes and goes stands are kept EMPTY (r1 painted a full stall in the vending
# bay where the food three-wheeler parks); details only from what the scenes use or the card names (r1: a plain table).
REVISION = "r2"
OUT_DIR = HERE / "runs" / REVISION

# ── the four fixed templates: (slot name, what that slot must show). Always six: one 3x2 sheet. ─────────────────────
TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "outside": [
        ("Wide", "from the ANCHOR SPOT (where most of the place's life happens), facing the place's main frontage "
                 "square on: the whole place at once"),
        ("Looking left", "from the SAME anchor spot as the Wide, turned 90 degrees to the LEFT: looking along the "
                         "place to the left; the main frontage is now at the RIGHT edge of the picture"),
        ("Looking right", "from the SAME anchor spot as the Wide, turned 90 degrees to the RIGHT: looking along the "
                          "place to the right; the main frontage is now at the LEFT edge of the picture"),
        ("Reverse", "from the SAME anchor spot as the Wide, turned 180 degrees: what is behind the Wide's camera, "
                    "the main frontage out of the picture"),
        ("Detail 1", "close on the first thing the place is known for"),
        ("Detail 2", "close on the second thing the place is known for"),
    ],
    "inside": [
        ("Wide from the door", "standing at the way in, the whole room at once"),
        ("Opposite wall", "turned round: the wall with the way in, seen from the far side of the room"),
        ("Left wall", "the left wall of the room, square on"),
        ("Right wall", "the right wall of the room, square on"),
        ("Detail 1", "close on the first thing the room is known for"),
        ("Detail 2", "close on the second thing the room is known for"),
    ],
    "both": [
        ("Outside wide", "outside, the front of the place as a passer-by sees it"),
        ("Entrance", "close to the way in, looking in through it"),
        ("Inside wide", "inside, standing just in from the way in, the whole inside at once"),
        ("Inside reverse", "inside, turned round toward the way in and the outside beyond it"),
        ("Detail 1", "close on the first thing the place is known for"),
        ("Detail 2", "close on the second thing the place is known for"),
    ],
    "vehicle": [
        ("Front three-quarter", "outside, the front and one side, the whole vehicle"),
        ("Side", "outside, the full side square on"),
        ("Rear three-quarter", "outside, the back and the other side, the whole vehicle"),
        ("Inside from the rear", "inside, from where the back passengers sit, looking forward to the driver's place"),
        ("Inside from the front", "inside, from the front, looking back at the seats behind"),
        ("Detail", "close on the one thing inside or on it that people use most (the dashboard, a hatch)"),
    ],
}


class Answers(BaseModel):
    sides: Literal["outside", "inside", "both"]
    moves: bool = Field(description="true only for a vehicle: a car, a three-wheeler, a bus, a boat")
    size: Literal["small", "room", "long"]
    why: str = Field(description="one sentence: why these answers")


class View(BaseModel):
    slot: str = Field(description="the template slot name, exactly")
    camera: str = Field(description="where the camera stands and which way it looks, in one sentence")
    sees: str = Field(description="what the camera sees and on which side of the picture (left, centre, right, "
                                  "near, far), in one or two sentences")


class Written(BaseModel):
    answers: Answers
    layout: str = Field(description="the place as ONE connected layout: where each fixed thing stands relative to "
                                    "the others (left, right, behind, across), in two to four sentences")
    empty: list[str] = Field(description="each space of the place kept EMPTY because something that comes and goes "
                                         "stands there in the scenes (a vehicle, a cart, a stall packed away at "
                                         "night): where it is and what it looks like empty; [] when there is none")
    views: list[View]


SYSTEM = """You write the views of ONE place for a location reference sheet of a Sri Lankan television drama.

The sheet is made from the canon card, BEFORE any shot is planned. Later every shot finds on it a view facing roughly
the way its camera faces, so the sheet covers the place's main POSSIBLE views; it does not follow any shot.

First answer three questions about the place:
- sides: does the story see it from outside only, inside only, or both?
- moves: is it a vehicle (a car, a three-wheeler, a bus, a boat)?
- size: small (a cab, a cupboard-sized room), room (one room or one shop), or long (a road, a market street, a
  corridor people move along).

The answers pick the template: a vehicle uses `vehicle`; otherwise `outside`, `inside` or `both` by its sides. Then
write the place's layout once, and one view for EVERY slot of that template, in its order, with the slot's exact name.

Rules:
- The place is ONE connected place: every view shows the same fixed things on the same sides as the layout puts them.
- Write only what the card, the picture of the place (when given) and the scenes set there say or plainly imply.
  Invent nothing that changes the place; small ordinary details of a real Sri Lankan place are fine.
- No people, no animals, no named characters, no story events. A place is never shown with a vehicle parked in it:
  vehicles have sheets of their own. A vehicle's own sheet shows the vehicle alone.
- Only what is ALWAYS there. When the scenes put something that comes and goes in a part of the place (a vehicle
  parked in a bay, a food cart, a stall set up and packed away), that part is kept EMPTY in every view: bare ground,
  nothing standing in it. List each such space in `empty`, and write it as empty in the layout and the views. When the
  picture of the place shows something standing in such a space, leave it out.
- The outside template's first four views share ONE camera spot, the anchor spot, and differ only by turning: 0, 90
  degrees left, 90 degrees right, 180 degrees. Say in each of them where the main frontage is in the picture.
- Details: a thing people in the scenes touch, use or stand at, or that the card names as the place's own (a counter,
  a stove, a desk with papers, a dashboard). Never a plain table, chair or wall that no scene uses.
- No text, signs with words or logos in any view unless the card names them.

The templates (slot: what it shows):
""" + "\n".join(f"{name}:\n" + "\n".join(f"  - {s}: {w}" for s, w in slots) for name, slots in TEMPLATES.items())


# ── money ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def book(run: str, step: str, model: str, inp: int, out: int, usd: float, note: str) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "run", "step", "model", "input_tokens", "output_tokens", "usd", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), run, step, model, inp, out, f"{usd:.5f}", note])


def guard(worst: float) -> None:
    if spent() + worst > LAB_BUDGET_USD:
        raise SystemExit(f"NOT SENT: ${spent():.3f} spent + ${worst:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")


# ── the writer ────────────────────────────────────────────────────────────────────────────────────────────────

def places() -> dict[str, dict]:
    return json.loads((IN / "places.json").read_text(encoding="utf-8"))


def scene_text(scene: dict) -> str:
    lines = [str(i.get("text") or "") for i in scene.get("script") or [] if isinstance(i, dict)]
    return f"Scene {scene['number']} — {scene.get('heading') or ''}: " + " ".join(lines)[:1500]


def user_message(key: str) -> str:
    p = places()[key]
    kind = "a vehicle card" if p["class"] == "vehicle" else "a place card"
    parts = [f"The place: {p['name']} ({kind}).", f"Its look (the canon card): {p['look']}"]
    if p["spots"]:
        parts.append("Its parts: " + "; ".join(f"{s['name']}: {s['look']}" for s in p["spots"]))
    parts.append("Its picture is attached: keep its look and where its things stand." if p["plate"] else
                 "It has no picture yet: the sheet will be painted from your words only.")
    parts.append("Scenes set there or using it:\n" + "\n".join(scene_text(s) for s in p["scenes"]))
    return "\n\n".join(parts)


def data_url(path: Path) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def template_of(a: Answers) -> str:
    return "vehicle" if a.moves else a.sides


def check(w: Written) -> list[str]:
    want = [s for s, _ in TEMPLATES[template_of(w.answers)]]
    got = [v.slot for v in w.views]
    return [] if got == want else [f"slots {got} are not the template's {want}"]


def write(client, key: str) -> Written:
    p = places()[key]
    content: list[dict] = [{"type": "input_text", "text": user_message(key)}]
    if p["plate"]:
        content.append({"type": "input_image", "image_url": data_url(IN / p["plate"])})
    guard(0.02)
    resp = client.responses.parse(model=TEXT_MODEL, reasoning={"effort": EFFORT}, text_format=Written,
                                  input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
                                  max_output_tokens=12000)
    u = resp.usage
    usd = u.input_tokens * TEXT_PRICES[0] / 1e6 + u.output_tokens * TEXT_PRICES[1] / 1e6
    book("write", key, TEXT_MODEL, u.input_tokens, u.output_tokens, usd, f"views {key}")
    return resp.output_parsed


# ── the sheet ─────────────────────────────────────────────────────────────────────────────────────────────────

def written(key: str) -> Written:
    path = OUT_DIR / "written" / f"{key}.json"
    if not path.exists():
        raise SystemExit(f"no written views for {key}: run `write --yes` first")
    return Written.model_validate_json(path.read_text(encoding="utf-8"))


def sheet_prompt(key: str, w: Written) -> tuple[str, list[Reference]]:
    p = places()[key]
    vehicle = template_of(w.answers) == "vehicle"
    refs = [Reference(label=f"the {'vehicle' if vehicle else 'location'} plate for {p['name']}",
                      data=(IN / p["plate"]).read_bytes())] if p["plate"] else []
    what = "vehicle" if vehicle else "place"
    head = (f"A {'vehicle' if vehicle else 'location'} reference sheet for a Sri Lankan television drama: six "
            f"photorealistic film stills of ONE real {what}, laid out in a grid 3 across and 2 down, read left to "
            "right, then top to bottom. Every still is a landscape 3:2 picture of the same size, separated by thin, "
            "even, plain white gutters. Nobody is in any view: no people, no figures.")
    if refs:
        take = (f"Reference images, in order: image 1 is {refs[0].label}. Take from image 1 the {what} itself: "
                + ("its make and model, body, colour, wheels, lights, windows and its inside: dashboard, steering "
                   "wheel and seats. Ignore everything around the vehicle in that picture." if vehicle else
                   "its ground, walls, buildings and fixtures, their materials and colours, and where each stands."))
    else:
        take = f"There is no picture of this {what}: paint it from these words: {p['look']}"
    ground = ("The vehicle stands alone on a plain, empty, light-grey concrete floor of a large covered parking area "
              "for every outside view; nothing else is near it." if vehicle else
              "No vehicle is parked anywhere in the place.")
    if w.empty:
        ground += (" These spaces are EMPTY in every view, bare, with nothing standing in them: "
                   + "; ".join(w.empty) + "." + (" Leave out anything image 1 shows standing in them." if refs else ""))
    views = "\n".join(f"VIEW {i} (row {(i - 1) // 3 + 1}, column {(i - 1) % 3 + 1}) — {v.slot}: {v.camera} {v.sees}"
                      for i, v in enumerate(w.views, 1))
    prompt = "\n\n".join([
        head, take, f"The {what}, one connected layout seen from six positions: {w.layout}",
        f"Light (every view): soft, even daylight that shows the {what} clearly; the same light in every view. "
        + ground,
        views,
        f"Every view shows the SAME {what}: the same things, each where the layout puts it. The people, place and "
        "everyday details are Sri Lankan. Draw NO text of any kind: no labels, no numbers, no captions, no arrows, "
        "no borders other than the gutters.",
    ])
    return prompt, refs


def worst_image(refs: list[Reference], prompt: str) -> float:
    return (1600 * len(refs) + len(prompt) // 3) * IMAGE_PRICES[0] / 1e6 + 6500 * IMAGE_PRICES[1] / 1e6


def labelled(sheet: bytes, names: list[str]) -> bytes:
    """The sheet with each view's name drawn by code in its cell, for people reading the lab."""
    im = Image.open(io.BytesIO(sheet)).convert("RGB")
    draw = ImageDraw.Draw(im)
    for name, box in zip(names, pics.cell_boxes(sheet, len(names)), strict=False):
        x0, y0 = int(box[0]) + 8, int(box[1]) + 8
        draw.rectangle([x0 - 4, y0 - 4, x0 + 7 * len(name) + 8, y0 + 16], fill=(200, 16, 46))
        draw.text((x0, y0), name, fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def paint(key: str) -> None:
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    w = written(key)
    prompt, refs = sheet_prompt(key, w)
    guard(worst_image(refs, prompt))
    out = OUT_DIR / "sheets" / key
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    t = time.time()
    pic = OpenAIImages(client(), model=IMAGE_MODEL, quality="medium")(prompt, "16:9", refs, quality="medium")
    usd = pic.input_tokens * IMAGE_PRICES[0] / 1e6 + pic.output_tokens * IMAGE_PRICES[1] / 1e6
    book("paint", key, IMAGE_MODEL, pic.input_tokens, pic.output_tokens, usd, f"sheet {key} medium")
    (out / "sheet.png").write_bytes(pic.data)
    names = [v.slot for v in w.views]
    (out / "sheet_labelled.png").write_bytes(labelled(pic.data, names))
    small = Image.open(io.BytesIO(labelled(pic.data, names)))
    small.thumbnail((1200, 1200))
    small.convert("RGB").save(out / "sheet_small.jpg", quality=85)
    problems = pics.cut_problems(pic.data, pics.cell_boxes(pic.data, 6))
    print(f"{key}: ${usd:.4f} in {round(time.time() - t)} s; cut {'ok' if not problems else '; '.join(problems)}; "
          f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")


# ── commands ──────────────────────────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "write", "paint"])
    ap.add_argument("place", nargs="?", default="all")
    ap.add_argument("--yes", action="store_true", help="the person said yes to this call")
    args = ap.parse_args()
    keys = list(places()) if args.place == "all" else [args.place]

    if args.mode == "dry":
        d = OUT_DIR / "dry"
        d.mkdir(parents=True, exist_ok=True)
        (d / "system.txt").write_text(SYSTEM, encoding="utf-8")
        for k in keys:
            (d / f"user_{k}.txt").write_text(user_message(k), encoding="utf-8")
            print(f"{k}: user message {len(user_message(k))} chars, picture {'yes' if places()[k]['plate'] else 'no'}")
            if (OUT_DIR / "written" / f"{k}.json").exists():
                prompt, refs = sheet_prompt(k, written(k))
                (d / f"sheet_{k}.txt").write_text(prompt, encoding="utf-8")
                blocked = safe_depiction.blocking(prompt)
                print(f"   sheet prompt {len(prompt)} chars, worst ${worst_image(refs, prompt):.3f}"
                      f"{'; BLOCKED ' + str(blocked) if blocked else ''}")
        print(f"system {len(SYSTEM)} chars; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}; prompts in {d}")
        return 0
    if not args.yes:
        print("needs --yes: the person's yes for this call")
        return 2
    if args.mode == "write":
        from cinematic.run import client

        c = client()
        (OUT_DIR / "written").mkdir(parents=True, exist_ok=True)
        for k in keys:
            w = write(c, k)
            (OUT_DIR / "written" / f"{k}.json").write_text(w.model_dump_json(indent=1), encoding="utf-8")
            problems = check(w)
            print(f"{k}: {w.answers.sides}/{'moves' if w.answers.moves else 'fixed'}/{w.answers.size} -> "
                  f"{template_of(w.answers)}; {'ok' if not problems else problems}; {w.answers.why}")
        print(f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
        return 0
    for k in keys:
        paint(k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
