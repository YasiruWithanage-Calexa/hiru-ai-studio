"""The storyboard lab: ONE scene's shot plans + its reference pictures -> ONE storyboard image.

Two paid calls per run, nothing else:
  1. the writer (an OpenAI text model, JSON schema output) reads the scene and every shot's PLAN (never a first-frame
     prompt) and writes the board: a shared `world`, the `geography` as a path, and one `picture` per panel;
  2. the image model paints the board in one generation, with every reference picture attached in the order the
     prompt cites them (code builds the citation from the same list it attaches).

Money: the whole lab has a hard budget (`LAB_BUDGET_USD`). Before each call its WORST case is added to the ledger's
total; over the budget, the call is not sent. Image tokens are priced above the list price on purpose (see PRICES).
Nothing under `src/` changes and nothing is written to the database.

    .venv/Scripts/python.exe lab/storyboard/run.py dry   --input scene1  # the request + worst case; no call
    .venv/Scripts/python.exe lab/storyboard/run.py paid  --input scene1 --hypothesis "..."
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts.safe_depiction import blocking  # noqa: E402

# 2026-11-14: 1.00 → 1.30 (scene 02 board) → 1.80 (frame test) → 2.10 (input_fidelity) → 2.30 (face sheet),
# each on the person's go-ahead
LAB_BUDGET_USD = 3.40  # → 2.60 (mannequin) → 2.80 (close-up) → 3.20 (scene 01) → 3.40 (state fix)
# Writer cap: run_001 used 4,341 output tokens (1,931 reasoning); 10,000 keeps over 2x headroom and fits the budget.
WRITER_MODEL, WRITER_EFFORT, WRITER_MAX_OUT = "gpt-6.1-sol", "high", 10000
IMAGE_MODEL, IMAGE_SIZE = "gpt-image-2", "1536x1024"
# Worst-case output tokens of one high-quality 1536x1024 picture (guard only). run_001 used 5,488; 10,000 left no
# room for a second run in the $1.00 budget, so the guard uses the measured value plus ~20 %.
# low / medium have no measurement yet: OpenAI's low 1536x1024 is a few hundred tokens, so 1500 is a wide margin.
IMAGE_WORST_OUT = {"low": 1500, "medium": 3000, "high": 6500}
# Image input: run_001/002 measured 11,498 / 11,584 for 6 references (9,216 image + ~2,300 text); +15 %.
IMAGE_IN_BASE, IMAGE_IN_PER_REF = 3000, 1700
# input_fidelity=high sends each reference in more detail; not measured yet, so the guard assumes a generous 6000.
IMAGE_IN_PER_REF_HIGH_FIDELITY = 6000
# (input, cached input, output) USD per 1M tokens. gpt-6.1-sol: the repo's seeded list price. gpt-image-2: the repo's
# seed says 8 / 30 and is marked provisional, so the lab charges itself MORE (10 / 40) to stay safely under the budget.
PRICES = {"gpt-6.1-sol": (2.00, 0.10, 10.00), "gpt-image-2": (10.00, 10.00, 40.00)}
LEDGER = HERE / "runs" / "ledger.csv"
FIELDS = ["time", "run", "call", "model", "input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens",
          "dollars", "status", "hypothesis"]

SCHEMA: dict[str, Any] = {
    "title": "storyboard", "type": "object", "additionalProperties": False,
    "required": ["world", "geography", "panels", "conflicts"],
    "properties": {
        "world": {"type": "string"},
        "geography": {"type": "string"},
        "panels": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["shot", "zone", "camera", "background", "picture"],
            "properties": {
                "shot": {"type": "integer"},
                "zone": {"type": "string", "description": "the staging zone or spot the camera is in"},
                "camera": {"type": "string", "description": "where the camera stands, which way it looks, size"},
                "background": {"type": "string", "description": "what is behind the people, and on which side"},
                "picture": {"type": "string", "description": "2-4 sentences: the opening picture of the shot"}}}},
        "conflicts": {"type": "array", "items": {"type": "string"}}},
}

ROLE_LABEL = {"face": "the face sheet for {n}", "look": "the look sheet for {n}",
              "place": "the location plate for {n}",
              "prop": "the reference sheet for {n}"}
ROLE_JOB = {
    "face": "{n}'s face, age, hair and build, the same man at every angle and expression; {n}'s face comes ONLY from "
            "this sheet",
    "look": "{n}'s face, body, hair and clothes in this scene, not the sheet's light or backdrop",
    "place": "the kind of place: its ground, water, plants, structures and materials. It is ONE view of the place; "
             "each panel has its own camera position, so do not repeat this view in every panel",
    "prop": "{n} exactly as shown",
}


# ── money ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def dollars(model: str, inp: int, cached: int, out: int) -> float:
    pin, pc, pout = PRICES[model]
    return (max(inp - cached, 0) * pin + cached * pc + out * pout) / 1_000_000


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def guard(worst: float, what: str) -> None:
    if spent() + worst > LAB_BUDGET_USD:
        raise SystemExit(f"STOP: {what} could cost up to ${worst:.3f}; the ledger has ${spent():.3f} of "
                         f"${LAB_BUDGET_USD:.2f}. Not sent.")


def book(run: str, call: str, model: str, usage: dict[str, int], status: str, hypothesis: str) -> float:
    cost = dollars(model, usage.get("input", 0), usage.get("cached", 0), usage.get("output", 0))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run, "call": call, "model": model,
                    "input_tokens": usage.get("input", 0), "cached_tokens": usage.get("cached", 0),
                    "output_tokens": usage.get("output", 0), "reasoning_tokens": usage.get("reasoning", 0),
                    "dollars": f"{cost:.5f}", "status": status, "hypothesis": hypothesis})
    return cost


# ── the request ───────────────────────────────────────────────────────────────────────────────────────────────────

def grid_for(n: int) -> tuple[int, int]:
    """(columns, rows) for n landscape panels on a landscape sheet."""
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def labels(refs: list[dict[str, Any]]) -> list[str]:
    return [ROLE_LABEL[r["role"]].format(n=r["name"]) for r in refs]


# plan/2026-11-13e §6h: a board of colour-coded, faceless mannequins: the board fixes place, camera, props and poses;
# faces and clothes are added only at the first-frame step (face sheet + look sheet), so the board cannot drift them.
MANNEQUIN_COLOURS = ["red", "blue", "yellow", "green", "purple", "orange"]


def mannequin_colours(bundle: dict[str, Any]) -> dict[str, str]:
    return {p["name"]: MANNEQUIN_COLOURS[i % len(MANNEQUIN_COLOURS)] for i, p in enumerate(bundle["people"])}


def mannequin_note(bundle: dict[str, Any]) -> str:
    named = ", ".join(f"{n} = the {c} mannequin" for n, c in mannequin_colours(bundle).items())
    return ("MANNEQUIN BOARD. Every person is painted as a smooth, faceless, colour-coded artist's mannequin, at the "
            f"person's height and build: {named}. So describe each person ONLY by their mannequin's pose: where the "
            "body sits or stands, which way the chest faces, which way the head turns, where each hand is, what it "
            "holds or touches. Never describe a face, expression, mouth, eyes, hair, skin or clothes. Props, the place "
            "and the light are described and painted for real. A person shown INSIDE a photograph, poster or screen "
            "in the scene is not a mannequin: describe that picture as a real photograph.")


def writer_input(bundle: dict[str, Any], mannequins: bool = False) -> list[dict[str, Any]]:
    data = {k: v for k, v in bundle.items() if k not in ("references", "all_shots")}
    data["reference_pictures"] = [f"image {i}: {label}" for i, label in enumerate(labels(bundle["references"]), 1)]
    cols, rows = grid_for(len(bundle["shots"]))
    text = (f"<scene>\n{json.dumps(data, ensure_ascii=False, indent=1)}\n</scene>\n\n"
            f"Write the storyboard: {len(bundle['shots'])} panels, one per shot in shot order, laid out {cols} across "
            f"and {rows} down. The reference pictures follow, in the same order as `reference_pictures`."
            + ("\n\n" + mannequin_note(bundle) if mannequins else ""))
    parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
    for r in bundle["references"]:
        b64 = base64.b64encode((HERE / r["file"]).read_bytes()).decode()
        parts.append({"type": "input_image", "image_url": f"data:image/png;base64,{b64}", "detail": "low"})
    return [{"role": "user", "content": parts}]


# plan/2026-11-13e §6g: people in run_007 posed for the camera (a driver's chest square to the lens with the wheel off
# to one side; a frontal face with the eyes rolled sideways). A principle for every board, never this scene's words.
BODIES = (
    "Bodies (every panel): each person sits or stands the way a real person does the task in front of them, never "
    "posed for the camera. The body faces the task and only the head turns: someone at a steering wheel sits squarely "
    "behind it, the wheel centred in front of the chest, back against the seat, both hands on the rim; someone at a "
    "desk sits square to it; someone at a stove faces the stove. A camera beside a person sees the body side-on, not "
    "the chest. Nobody looks into or faces the lens unless the panel says so. Head and eyes turn together: the eyes "
    "never roll hard to one side while the face points at the camera; a near-frontal face looks just past the lens.")


def mannequin_line(bundle: dict[str, Any]) -> str:
    named = "; ".join(f"{n} is the {c} mannequin" for n, c in mannequin_colours(bundle).items())
    return ("People (every panel): every person is a smooth, matte, faceless artist's mannequin in one solid colour, "
            f"with jointed limbs and simple hands: {named}. A small raised ridge on the front of the head, where a "
            "nose would be, shows which way the head faces. Each mannequin has the person's real height and build and "
            "sits, stands and holds things exactly as a real person would. No faces, no hair, no clothes, no skin: "
            "only the mannequin colour. Everything else (the place, the props, the light, the weather) is a real, "
            "photorealistic film still.")


def board_prompt(bundle: dict[str, Any], board: dict[str, Any], mannequins: bool = False) -> str:
    """The image prompt. Code writes the frame of it (the sheet, the references, the rules); the writer's words fill
    the world, the geography and the panels."""
    n = len(board["panels"])
    cols, rows = grid_for(n)
    names = labels(bundle["references"])
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(names, 1))
    faced = {r["name"] for r in bundle["references"] if r["role"] == "face"}
    jobs = "; ".join(f"image {i}: {_job(r, faced)}" for i, r in enumerate(bundle["references"], 1))
    order = ("left to right, then top to bottom" if rows > 1 else "left to right")
    pos = []
    for i, p in enumerate(board["panels"]):
        r, c = divmod(i, cols)
        pos.append(f"PANEL {i + 1} (row {r + 1}, column {c + 1}) — {p['camera']}. Background: {p['background']}. "
                   f"{p['picture']}")
    return "\n\n".join([
        f"A cinematic storyboard sheet for a Sri Lankan television drama: {n} photorealistic film stills of ONE scene, "
        f"laid out in a grid {cols} panels across and {rows} down, read {order}. Every panel is a landscape 16:9 "
        "still of the same size, separated by thin, even, plain white gutters. All panels are the same moment's "
        "world, painted together: the same people, clothes, props, weather, light and colour grade in every panel.",
        (f"Reference images, in order: {cite}. Take from {jobs}." if mannequins else
         f"Reference images, in order: {cite}. Match the people exactly: the same faces, hair, skin tone, build and "
         f"clothes. Take from {jobs}."),
        *([mannequin_line(bundle)] if mannequins else []),
        "World (every panel): " + _world(board["world"], faced),
        *([_faces_line(bundle)] if faced else []),
        "Geography: " + board["geography"],
        "\n".join(pos),
        BODIES,
        "Draw NO text of any kind: no panel numbers, no captions, no titles, no timestamps, no arrows, no labels, no "
        "borders other than the gutters. The people, place and everyday details are Sri Lankan.",
    ])


def _gutters(white: list[float], parts: int, size: int) -> list[tuple[int, int]]:
    """The cell spans along one axis: the painted gutters (runs of mostly-white lines) found near each even split,
    falling back to the even split where no gutter is found."""
    spans, start = [], 0
    for k in range(1, parts):
        even, reach = round(k * size / parts), size // (parts * 6)
        band = [i for i in range(max(even - reach, 0), min(even + reach, size)) if white[i] > 0.85]
        if band:
            lo, hi = min(band), max(band)
            spans.append((start, lo))
            start = hi + 1
        else:
            spans.append((start, even))
            start = even
    spans.append((start, size))
    # trim a white edge the board may have around it
    a, b = spans[0]
    while a < b and white[a] > 0.85:
        a += 1
    spans[0] = (a, b)
    a, b = spans[-1]
    while b > a and white[b - 1] > 0.85:
        b -= 1
    spans[-1] = (a, b)
    return spans


def _job(ref: dict[str, Any], faced: set[str]) -> str:
    if ref["role"] == "look" and ref["name"] in faced:
        # the face sheet owns the face; the look sheet keeps only the clothes
        return f"{ref['name']}'s clothes, shoes and accessories in this scene, not the face, light or backdrop"
    return ROLE_JOB[ref["role"]].format(n=ref["name"])


_FACE_WORDS = re.compile(r"\b(face|features|skin|eyes|hair|stubble|beard|moustache|jaw|cheek|brow)", re.IGNORECASE)


def _world(world: str, faced: set[str]) -> str:
    """The writer's World paragraph without its sentences that describe a face-sheet person's face: with a face sheet,
    the picture decides the face, never the words."""
    if not faced:
        return world
    keep = [x for x in re.split(r"(?<=[.!?])\s+", world.strip())
            if not (_FACE_WORDS.search(x) and any(n in x for n in faced))]
    return " ".join(keep)


def _faces_line(bundle: dict[str, Any]) -> str:
    refs = bundle["references"]
    named = "; ".join(f"{r['name']} is the person of image {i}" for i, r in enumerate(refs, 1)
                      if r["role"] == "face")
    return ("Faces: " + named + ". Paint each of them as exactly that person in every panel, at the panel's angle and "
            "expression: the same face shape, age, skin tone, eyes, nose, hairline, hair and stubble. Do not age them, "
            "make them heavier or more weathered to suit the mood.")


def crop_panels(png: Path, n: int, out: Path) -> None:
    from PIL import Image
    cols, rows = grid_for(n)
    im = Image.open(png).convert("RGB")
    w, h = im.size
    g = im.convert("L")
    px = g.load()
    row_white = [sum(px[x, y] > 230 for x in range(0, w, 4)) / len(range(0, w, 4)) for y in range(h)]
    col_white = [sum(px[x, y] > 230 for y in range(0, h, 4)) / len(range(0, h, 4)) for x in range(w)]
    ys, xs = _gutters(row_white, rows, h), _gutters(col_white, cols, w)
    out.mkdir(exist_ok=True)
    for i in range(n):
        r, c = divmod(i, cols)
        im.crop((xs[c][0], ys[r][0], xs[c][1], ys[r][1])).save(out / f"panel_{i + 1:02d}.png")


def scene_sheet(bundle: dict[str, Any], board: dict[str, Any], run: Path) -> None:
    """Every shot of the scene, in order, on one numbered sheet (`sheet.png`), plus each painted panel saved by its shot
    number (`shots/shot_NN.png`) and `sheet.json` (shot -> panel). The numbers are drawn by code, never by the image
    model: a shot that is a cut to black or a title is a black cell carrying its script line."""
    from PIL import Image, ImageDraw, ImageFont
    panel_of = {int(p["shot"]): i + 1 for i, p in enumerate(board["panels"])}
    shots = bundle.get("all_shots") or [{"number": s["number"], "painted": True, "text": ""} for s in bundle["shots"]]
    first = Image.open(run / "panels" / "panel_01.png")
    cw, ch = first.size
    cols, rows = grid_for(len(shots))
    gap = 8
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * gap, rows * ch + (rows + 1) * gap), "white")
    draw = ImageDraw.Draw(sheet)
    tag_font = ImageFont.load_default(size=max(18, ch // 12))
    text_font = ImageFont.load_default(size=max(14, ch // 18))
    (run / "shots").mkdir(exist_ok=True)
    index = []
    for i, shot in enumerate(shots):
        r, c = divmod(i, cols)
        x, y = gap + c * (cw + gap), gap + r * (ch + gap)
        n = int(shot["number"])
        panel = panel_of.get(n) if shot["painted"] else None
        if panel:
            cell = Image.open(run / "panels" / f"panel_{panel:02d}.png").convert("RGB").resize((cw, ch))
            cell.save(run / "shots" / f"shot_{n:02d}.png")
            sheet.paste(cell, (x, y))
        else:
            draw.rectangle((x, y, x + cw - 1, y + ch - 1), fill="black")
            words, line, lines = str(shot.get("text") or "").split(), "", []
            for w in words:
                if draw.textlength(f"{line} {w}".strip(), font=text_font) > cw - 40:
                    lines.append(line)
                    line = w
                else:
                    line = f"{line} {w}".strip()
            lines.append(line)
            draw.multiline_text((x + cw / 2, y + ch / 2), "\n".join(t for t in lines if t), font=text_font,
                                fill="#bbbbbb", anchor="mm", align="center")
        label = f"SHOT {n}"
        tw = draw.textlength(label, font=tag_font)
        pad = 6
        draw.rectangle((x, y, x + tw + 2 * pad, y + tag_font.size + 2 * pad), fill="#c8102e")
        draw.text((x + pad, y + pad), label, font=tag_font, fill="white")
        index.append({"shot": n, "slate": shot.get("slate"), "panel": panel,
                      "kind": "painted" if panel else ("black" if not shot["painted"] else "missing"),
                      "file": f"shots/shot_{n:02d}.png" if panel else None})
    sheet.save(run / "sheet.png")
    (run / "sheet.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────────

def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max([int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()] or [0])
    d = runs / f"run_{n:03d}"
    d.mkdir()
    return d


def client() -> Any:
    from openai import OpenAI
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return OpenAI(api_key=env["OPENAI__API_KEY"], timeout=600)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "paid", "image"])
    ap.add_argument("--from", dest="source", default="",
                    help="image mode: an earlier run whose writer output and board prompt are reused (no writer call)")
    ap.add_argument("--quality", choices=["low", "medium", "high"], default="high")
    ap.add_argument("--faces", default="",
                    help="comma-separated people whose face sheet (input/<name>/refs/face_<person>.png) goes first")
    ap.add_argument("--mannequins", action="store_true",
                    help="people painted as colour-coded faceless mannequins; the board gets no face or look sheets")
    ap.add_argument("--rebuild", action="store_true",
                    help="image mode: rebuild the board prompt from the bundle instead of reusing the source run's")
    ap.add_argument("--fidelity", choices=["low", "high"], default="",
                    help="input_fidelity: how hard the model matches the references, faces above all (API default low)")
    ap.add_argument("--input", default="scene1")
    ap.add_argument("--hypothesis", default="")
    a = ap.parse_args()

    bundle = json.loads((HERE / "input" / a.input / "bundle.json").read_text(encoding="utf-8"))
    faces = [{"role": "face", "name": n.strip(), "file": f"input/{a.input}/refs/face_{n.strip()}.png"}
             for n in a.faces.split(",") if n.strip()]
    bundle["references"] = faces + bundle["references"]
    system = (HERE / "prompt" / "system.md").read_text(encoding="utf-8")
    items = writer_input(bundle, a.mannequins)
    # the board image never sees a person's sheet in mannequin mode (the writer still does, for build and props)
    image_bundle = ({**bundle, "references": [r for r in bundle["references"] if r["role"] not in ("face", "look")]}
                    if a.mannequins else bundle)
    text_chars = len(system) + len(items[0]["content"][0]["text"])
    est_in = text_chars // 3 + 100 * len(bundle["references"])
    w_worst = dollars(WRITER_MODEL, est_in, 0, WRITER_MAX_OUT)
    per_ref = IMAGE_IN_PER_REF_HIGH_FIDELITY if a.fidelity == "high" else IMAGE_IN_PER_REF
    i_worst = dollars(IMAGE_MODEL, IMAGE_IN_BASE + per_ref * len(image_bundle["references"]), 0,
                      IMAGE_WORST_OUT[a.quality])
    if a.mode == "image":
        w_worst = 0.0  # the writer is not called
    print(f"{len(bundle['shots'])} panels, {len(bundle['references'])} references; writer ~{est_in} input tokens")
    print(f"worst case: writer ${w_worst:.3f} + image ${i_worst:.3f} = ${w_worst + i_worst:.3f}; "
          f"ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
    if a.mode == "dry":
        print(items[0]["content"][0]["text"][:3000])
        return 0

    guard(w_worst + i_worst, "this run")
    run = next_run()
    print("run:", run.name, "quality:", a.quality)
    if a.mode == "image":
        src = HERE / "runs" / a.source
        board = json.loads((src / "writer_output.json").read_text(encoding="utf-8"))
        prompt = (board_prompt(image_bundle, board, a.mannequins) if a.rebuild
                  else (src / "board_prompt.txt").read_text(encoding="utf-8"))
        (run / "writer_output.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
        (run / "board_prompt.txt").write_text(prompt, encoding="utf-8")
        if blocking(prompt):
            print("STOP: the board prompt has words the image model declines")
            return 1
        return paint(run, image_bundle, board, prompt, client(), a, 0.0, None)
    (run / "writer_input.txt").write_text(system + "\n\n=====\n\n" + items[0]["content"][0]["text"], encoding="utf-8")
    oa = client()

    # 1. the writer
    t0 = time.time()
    resp = oa.responses.create(model=WRITER_MODEL, instructions=system, input=items, max_output_tokens=WRITER_MAX_OUT,
                               reasoning={"effort": WRITER_EFFORT},
                               text={"format": {"type": "json_schema", "name": "storyboard", "schema": SCHEMA,
                                                "strict": True}})
    u = resp.usage
    usage = {"input": u.input_tokens, "output": u.output_tokens,
             "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "reasoning": getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0}
    w_cost = book(run.name, "writer", WRITER_MODEL, usage, resp.status, a.hypothesis)
    board = json.loads(resp.output_text)
    (run / "writer_output.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"writer: {time.time() - t0:.0f}s, {usage}, ${w_cost:.4f}")

    # 2. the board prompt, checked before anything more is spent
    prompt = board_prompt(image_bundle, board, a.mannequins)
    (run / "board_prompt.txt").write_text(prompt, encoding="utf-8")
    found = blocking(prompt)
    if found:
        print("STOP: the board prompt has words the image model declines:", [f.said for f in found])
        return 1
    if len(board["panels"]) != len(bundle["shots"]):
        print(f"note: {len(board['panels'])} panels for {len(bundle['shots'])} shots")

    return paint(run, image_bundle, board, prompt, oa, a, w_cost, usage)


def paint(run: Path, bundle: dict[str, Any], board: dict[str, Any], prompt: str, oa: Any, a: Any, w_cost: float,
          usage: dict[str, int] | None) -> int:
    # 3. the image
    t0 = time.time()
    files = [(f"reference-{i}.png", (HERE / r["file"]).read_bytes(), "image/png")
             for i, r in enumerate(bundle["references"], 1)]
    extra = {"input_fidelity": a.fidelity} if a.fidelity else {}
    img = oa.images.edit(model=IMAGE_MODEL, image=files, prompt=prompt, size=IMAGE_SIZE, quality=a.quality, **extra)
    iu = getattr(img, "usage", None)
    iusage = {"input": int(getattr(iu, "input_tokens", 0) or 0), "output": int(getattr(iu, "output_tokens", 0) or 0)}
    i_cost = book(run.name, "image", IMAGE_MODEL, iusage, "done", a.hypothesis)
    (run / "board.png").write_bytes(base64.b64decode(img.data[0].b64_json))
    crop_panels(run / "board.png", len(board["panels"]), run / "panels")
    scene_sheet(bundle, board, run)
    details = getattr(iu, "input_tokens_details", None)
    print(f"image: {time.time() - t0:.0f}s, {iusage}, details={details}, ${i_cost:.4f}")

    summary = {"run": run.name, "hypothesis": a.hypothesis, "writer": {"model": WRITER_MODEL, "effort": WRITER_EFFORT,
               "usage": usage, "usd": round(w_cost, 4), "reused_from": a.source or None},
               "image": {"model": IMAGE_MODEL, "quality": a.quality,
                         "input_fidelity": a.fidelity or "default (low)",
               "size": IMAGE_SIZE, "usage": iusage, "usd": round(i_cost, 4)},
               "run_usd": round(w_cost + i_cost, 4), "ledger_usd": round(spent(), 4),
               "references": labels(bundle["references"])}
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
