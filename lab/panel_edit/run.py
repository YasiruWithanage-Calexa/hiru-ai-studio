"""Panel edit lab (2026-11-17): when Zora or Sable adds or changes ONE shot, can the scene board paint only that
panel and keep every other approved panel as it is?

Start: an approved 6-panel portrait board of the tea-stall scene (lab/portrait_board run_001, copied to
`input/scene1/`), its writer text, the two place plates. Two edits (`input/scene1/edits.json`, lab fixtures):

  ADD     a new shot between panels 3 and 4 (over the customer's shoulder, Kasun pouring)
  CHANGE  shot 5, a medium close-up profile, becomes a wide from across the road

Questions
  Q1  One-panel writer: given the board's FIXED world, geography and panels, does `board_writer` (its product prompt
      + `prompt/one_panel.md`) write a panel that holds the neighbours' continuity?
  Q2  Which painting keeps the new panel in the board's world?
        solo   ONE 9:16 picture, the neighbouring panels attached as references             (add_solo, change_solo)
        strip  a sheet assembled by code (neighbours + an empty grey cell), masked edit of that cell (add_strip)
        mask   the board itself, masked edit of the changed cell: the product's method today (change_mask)
  Q3  Does a masked edit leave the rest of the sheet untouched (plan/2026-11-14 phase 0 (a))? `drift.json` measures
      every unmasked cell before code pastes the originals back.

Calls: two writer calls (gpt-6.1-sol, high) and four LOW gpt-image-2 calls, through the product's own painter.

    .venv/Scripts/python.exe lab/panel_edit/run.py dry                         # prompts, sheets sent, masks; no call
    .venv/Scripts/python.exe lab/panel_edit/run.py paid --yes                  # writer x2 + images x4 (a yes)
    .venv/Scripts/python.exe lab/panel_edit/run.py paid --yes --writer-from run_001 --only add_solo,change_solo

Nothing under `src/` changes and nothing is written to the database. Deleting this folder removes the lab.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab")]

from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

from contracts import board as kit  # noqa: E402
from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

LAB_BUDGET_USD = 1.00  # worst case 0.85 (over-stated prices); expected ~0.35
WRITER_MODEL, WRITER_EFFORT, WRITER_MAX_OUT = "gpt-6.1-sol", "high", 6000  # one panel: a fraction of a board's 4-6k
IMAGE_MODEL, QUALITY, ASPECT = "gpt-image-2", "low", kit.TALL
# (input, output) USD per 1M tokens; gpt-image-2 above the repo's provisional 8 / 30 on purpose, as the other labs
PRICES = {WRITER_MODEL: (2.00, 10.00), IMAGE_MODEL: (10.00, 40.00)}
IMAGE_WORST_OUT, IMAGE_IN_PER_REF = 1500, 1700  # LOW measured 158 output tokens; ~1,450 input per reference
WRITER_IN_WORST = 9000
LEDGER = HERE / "runs" / "ledger.csv"
INPUT = HERE / "input" / "scene1"
EDIT_LABEL = "the storyboard sheet to edit"  # the product's (frame_render/board.py)
BLANK = (128, 128, 128)
# solo call → the edit it paints (run_002 added change_solo_b, the same change again, and first_solo, shot 1)
SOLO = {"add_solo": "add", "change_solo": "change", "change_solo_b": "change", "first_solo": "change_first"}
CALLS = (*SOLO, "add_strip", "change_mask")
DEFAULT_CALLS = "add_solo,change_solo,change_solo_b,first_solo"  # run_001 settled the masked ones: not used

PANEL_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["zone", "camera", "background", "picture", "people", "conflicts"],
    "properties": {
        "zone": {"type": "string", "description": "the staging zone or spot the camera is in"},
        "camera": {"type": "string", "description": "where the camera stands, which way it looks, size"},
        "background": {"type": "string", "description": "what is behind the people, and on which side"},
        "picture": {"type": "string", "description": "2-4 sentences: the opening picture of the shot"},
        "people": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["name", "state"],
                                              "properties": {"name": {"type": "string"},
                                                             "state": {"type": "string"}}}},
        "conflicts": {"type": "array", "items": {"type": "string"}}},
}


# ── money ─────────────────────────────────────────────────────────────────────────────────────────────────────

def dollars(model: str, inp: int, out: int) -> float:
    pin, pout = PRICES[model]
    return (inp * pin + out * pout) / 1_000_000


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def guard(worst: float, what: str) -> bool:
    if spent() + worst > LAB_BUDGET_USD:
        print(f"[{what}] NOT SENT: ${spent():.3f} spent + ${worst:.3f} worst case > ${LAB_BUDGET_USD:.2f} budget")
        return False
    return True


def book(run: str, step: str, model: str, inp: int, out: int, status: str, note: str) -> float:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    usd = dollars(model, inp, out)
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "run", "step", "model", "input_tokens", "output_tokens", "usd", "status", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), run, step, model, inp, out, f"{usd:.5f}", status, note])
    return usd


def image_worst(refs: list[Reference], prompt: str) -> float:
    return dollars(IMAGE_MODEL, 3000 + IMAGE_IN_PER_REF * len(refs) + len(prompt) // 3, IMAGE_WORST_OUT)


# ── the input ─────────────────────────────────────────────────────────────────────────────────────────────────

class Scene:
    def __init__(self) -> None:
        self.board = json.loads((INPUT / "board.json").read_text(encoding="utf-8"))
        self.edits = json.loads((INPUT / "edits.json").read_text(encoding="utf-8"))
        self.writer = kit.Writer.of(self.board["writer"])
        self.colours: dict[str, str] = self.edits["colours"]
        self.sheet = (INPUT / "board.png").read_bytes()
        self.panels = {i: (INPUT / "panels" / f"panel_{i:03d}.png").read_bytes() for i in range(1, 7)}
        self.boxes = pics.cell_boxes(self.sheet, 6)
        refs = json.loads((INPUT / "refs.json").read_text(encoding="utf-8"))
        self.places = [Reference(label=f"the location plate for {r['name']}",
                                 data=(INPUT / f"ref_{r['id']}.png").read_bytes()) for r in refs]


def panel_of(raw: dict[str, Any], shot: int) -> kit.Panel:
    return kit.Writer.of({"panels": [{**raw, "shot": shot}]}).panels[0]


def stub_panel(plan: dict[str, Any], shot: int) -> kit.Panel:
    """Dry mode only: a stand-in panel built from the plan, so every prompt can be read before anything is paid."""
    return kit.Panel(shot=shot, zone=plan["setting"], camera=plan["composition"], background="(the writer's)",
                     picture=" ".join(plan["opening_picture"]), people=[])


# ── Q1: the one-panel writer ──────────────────────────────────────────────────────────────────────────────────

def writer_system() -> str:
    base = (ROOT / "src/libs/hiru_ai/agents/board_writer/prompts/system.md").read_text(encoding="utf-8")
    return base.rstrip() + "\n\n" + (HERE / "prompt" / "one_panel.md").read_text(encoding="utf-8")


def neighbours(s: Scene, kind: str) -> list[tuple[str, int]]:
    """(before | after, panel number) of the approved panels next to the edited shot; one at the scene's ends."""
    edit = s.edits[kind]
    pair = (edit["after"], edit["after"] + 1) if kind == "add" else (edit["shot"] - 1, edit["shot"] + 1)
    return [(side, n) for side, n in zip(("before", "after"), pair, strict=True) if n in s.panels]


def writer_request(s: Scene, kind: str) -> tuple[str, list[Reference]]:
    edit = s.edits[kind]
    plan = edit["plan"]
    board = s.writer.dump()
    if kind == "add":
        task = (f"ADD. A new shot goes between panel {edit['after']} and panel {edit['after'] + 1}. Write its panel. "
                "The approved panels keep their numbers here; the new shot's plan is below.")
    else:
        n = edit["shot"]
        for p in board["panels"]:
            if p["shot"] == n:
                p["being_replaced"] = True
        task = (f"CHANGE. Shot {n}'s plan changed. Write panel {n} again from the new plan below; its old text is "
                "marked `being_replaced` and is shown only so you know what the neighbours were painted next to.")
    pictures = [*s.places, *(Reference(label=f"panel {n} of the approved board (just {side} this one)",
                                       data=s.panels[n]) for side, n in neighbours(s, kind))]
    listing = "\n".join(f"image {i}: {p.label}" for i, p in enumerate(pictures, 1))
    text = (f"<approved_board>\n{json.dumps(board, ensure_ascii=False, indent=1)}\n</approved_board>\n\n"
            f"<shot>\n{json.dumps(plan, ensure_ascii=False, indent=1)}\n</shot>\n\n{task}\n\n"
            f"The pictures follow, in this order:\n{listing}\n\n{kit.mannequin_note(s.colours)}")
    return text, pictures


def write_panel(oa: Any, run: Path, s: Scene, kind: str) -> dict[str, Any] | None:
    text, pictures = writer_request(s, kind)
    (run / f"writer_{kind}_input.txt").write_text(text, encoding="utf-8")
    worst = dollars(WRITER_MODEL, WRITER_IN_WORST, WRITER_MAX_OUT)
    if not guard(worst, f"writer_{kind}"):
        return None
    content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
    content += [{"type": "input_image", "detail": "low",
                 "image_url": "data:image/png;base64," + base64.b64encode(p.data).decode()} for p in pictures]
    t = time.time()
    resp = oa.responses.create(model=WRITER_MODEL, instructions=writer_system(),
                               input=[{"role": "user", "content": content}], max_output_tokens=WRITER_MAX_OUT,
                               reasoning={"effort": WRITER_EFFORT},
                               text={"format": {"type": "json_schema", "name": "panel", "schema": PANEL_SCHEMA,
                                                "strict": True}})
    u = resp.usage
    usd = book(run.name, f"writer_{kind}", WRITER_MODEL, u.input_tokens, u.output_tokens, resp.status,
               f"one-panel writer, {kind}")
    out = json.loads(resp.output_text)
    (run / f"writer_{kind}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    reasoning = getattr(u.output_tokens_details, "reasoning_tokens", 0)
    print(f"[writer_{kind}] {time.time() - t:.0f} s, in {u.input_tokens} out {u.output_tokens} "
          f"(reasoning {reasoning}), ${usd:.4f}; conflicts: {out.get('conflicts') or 'none'}")
    return out


# ── Q2: the image prompts ─────────────────────────────────────────────────────────────────────────────────────

def solo_prompt(s: Scene, panel: kit.Panel, labels: list[str]) -> str:
    """One panel painted on its own; the approved neighbours (the last two references) carry the board's look."""
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(labels, 1))
    jobs = "; ".join(f"image {i}: {job}" for i, label in enumerate(labels, 1) if (job := kit.board_job(label)))
    return "\n\n".join([
        "ONE photorealistic film still for the storyboard of a Sri Lankan television drama: a single tall portrait "
        "9:16 panel filling the whole picture, with no gutters, no border and no other panels.",
        f"Reference images, in order: {cite}. Take from {jobs}.",
        "The approved storyboard panels attached last sit next to this one on the same board. Paint this panel so "
        "it sits beside them unnoticed: the same mannequins in the same colours and finish, the same place, props, "
        "light, weather, colour grade and level of detail. Do not copy their framing: this panel has its own "
        "camera, described below.",
        CAMERA_RULE,
        kit.mannequin_line(s.colours),
        "World: " + solo_world(kit.board_world(s.writer.world, s.colours)),
        "Geography: " + s.writer.geography,
        f"THE PANEL — {panel.camera.rstrip('.')}. Background: {panel.background.rstrip('.')}. {panel.picture}",
        kit.BODIES, kit.NO_TEXT.replace("no borders other than the gutters", "no borders, no gutters"),
    ])


_SHEET_WORDS = ("panel", "gutter", "grid", "storyboard image", "sheet")


def solo_world(world: str) -> str:
    """The board's world without its sentences about the SHEET ("six equal portrait panels ... gutters"): they
    contradict a picture of one panel. A finding for the product: the writer puts layout into `world`."""
    return " ".join(x for x in re.split(r"(?<=[.!?])\s+", world.strip())
                    if not any(w in x.lower() for w in _SHEET_WORDS))


# run_002: run_001's add put the camera BESIDE the customer when the panel said behind their shoulder.
CAMERA_RULE = ("The camera stands exactly where the panel says, and what is nearest the lens is what the panel puts "
               "nearest. When the camera is behind or past someone's shoulder, that person's back and shoulder are "
               "large in the near foreground, cut by the frame edge, and everything else is seen beyond them.")


def solo(s: Scene, panel: kit.Panel, kind: str) -> tuple[str, list[Reference]]:
    refs = [*s.places, *(Reference(label=f"the approved storyboard panel just {side} this one (shot {n})",
                                   data=s.panels[n]) for side, n in neighbours(s, kind))]
    return solo_prompt(s, panel, [r.label for r in refs]), refs


def _img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def repaint_prompt(writer: kit.Writer, numbers: list[int], repaint: list[int], labels: list[str],
                   colours: dict[str, str]) -> str:
    """The product's masked repaint prompt as it was when this lab ran (D7 method A). plan/2026-11-17 removed it from
    `contracts.board` (the mask is not honoured, D3); kept here so run_001's masked calls can be read again."""
    cols, _ = kit.grid_for(len(numbers))
    which = []
    for i, number in enumerate(numbers):
        p = writer.panel(number)
        if number in repaint and p is not None:
            r, c = divmod(i, cols)
            which.append(f"PANEL {i + 1} (row {r + 1}, column {c + 1}) — {p.camera.rstrip('.')}. Background: "
                         f"{p.background.rstrip('.')}. {p.picture}")
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(labels, 1))
    return "\n\n".join([
        "Image 1 is a storyboard sheet of one scene of a Sri Lankan television drama: a grid of photorealistic film "
        "stills separated by thin white gutters. Paint again ONLY the masked panels listed below, each inside its own "
        "cell, in the same world as the rest of the sheet: the same place, light, weather, colour grade and "
        "mannequins. Everything outside the masked cells stays exactly as it is, the gutters too.",
        f"Reference images, in order: {cite}.",
        kit.mannequin_line(colours),
        "World (every panel): " + kit.board_world(writer.world, colours),
        "Geography: " + writer.geography,
        "\n".join(which), kit.BODIES, kit.NO_TEXT,
    ])


def repaint_mask(size: tuple[int, int], boxes: list[tuple[int, int, int, int]]) -> bytes:
    """Opaque everywhere, transparent over `boxes` (the product's mask when this lab ran; removed by plan/2026-11-17)."""
    mask = Image.new("RGBA", size, (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle((int(x0), int(y0), int(x1) - 1, int(y1) - 1), fill=(0, 0, 0, 0))
    return _png(mask)


NEW = 100  # the added shot's place-holder number inside the lab's writer (prompts say PANEL n by position)


def strip(s: Scene, panel: kit.Panel) -> tuple[str, list[Reference], bytes, bytes, int]:
    """The add as a masked edit: the board's own grid holding panels 2, 3, an empty grey cell, 4, 5, 6.
    → (prompt, refs, the sheet sent, its mask, the empty cell's index)."""
    order = [2, 3, NEW, 4, 5, 6]
    hole = order.index(NEW)
    im = _img(s.sheet)
    draw = ImageDraw.Draw(im)
    for n, box in zip(order, s.boxes, strict=True):
        x0, y0, x1, y1 = box
        if n == NEW:
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=BLANK)
        else:
            im.paste(_img(s.panels[n]).resize((x1 - x0, y1 - y0)), (x0, y0))
    sheet = _png(im)
    mask = repaint_mask(im.size, [s.boxes[hole]])
    writer = kit.Writer(world=s.writer.world, geography=s.writer.geography,
                        panels=[*s.writer.panels, kit.Panel(**{**panel.__dict__, "shot": NEW})])
    refs = [Reference(label=EDIT_LABEL, data=sheet), *s.places]
    prompt = repaint_prompt(writer, order, [NEW], [r.label for r in refs], s.colours)
    return prompt, refs, sheet, mask, hole


def masked(s: Scene, panel: kit.Panel, shot: int) -> tuple[str, list[Reference], bytes, bytes, int]:
    """The change as the product does it today (D7 method A): the board itself, masked over the changed cell."""
    writer = s.writer.merged(kit.Writer(world="", geography="", panels=[panel]), [shot])
    refs = [Reference(label=EDIT_LABEL, data=s.sheet), *s.places]
    prompt = repaint_prompt(writer, list(range(1, 7)), [shot], [r.label for r in refs], s.colours)
    return prompt, refs, s.sheet, repaint_mask(_img(s.sheet).size, [s.boxes[shot - 1]]), shot - 1


# ── Q3: drift, and the sheets a person judges ─────────────────────────────────────────────────────────────────

def drift(before: bytes, after: bytes, boxes: list[tuple[int, int, int, int]], hole: int) -> dict[str, Any]:
    """Mean absolute difference (0-255) of every unmasked cell, and of everything outside the mask."""
    a, b = _img(before), _img(after)
    if a.size != b.size:
        return {"error": f"size changed: {a.size} -> {b.size}"}
    diff = ImageChops.difference(a, b).convert("L")
    cells = {}
    for i, box in enumerate(boxes):
        if i != hole:
            region = list(diff.crop(box).getdata())
            cells[f"cell_{i + 1}"] = round(sum(region) / len(region), 2)
    outside = Image.new("L", a.size, 255)
    ImageDraw.Draw(outside).rectangle(tuple(boxes[hole]), fill=0)
    total = list(ImageChops.multiply(diff, outside).getdata())
    count = sum(1 for v in outside.getdata() if v)
    return {"outside_mask_mean": round(sum(total) / count, 2), "cells": cells,
            "read": "0-1: untouched; 2-6: re-encoded, same picture; above ~8: the model repainted it"}


def sheet(cells: list[tuple[str, bytes, bool]], path: Path) -> None:
    """A side-by-side read: each panel at one height, a code-drawn tag, the new panel's tag in red."""
    h, gap, tag = 640, 14, 34
    ims = [(t, _img(d), new) for t, d, new in cells]
    ims = [(t, im.resize((round(im.width * h / im.height), h)), new) for t, im, new in ims]
    width = sum(im.width for _, im, _ in ims) + gap * (len(ims) + 1)
    out = Image.new("RGB", (width, h + tag + 2 * gap), (245, 245, 245))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    x = gap
    for t, im, new in ims:
        draw.text((x, gap), t, fill=(200, 16, 46) if new else (40, 40, 40), font=font)
        out.paste(im, (x, gap + tag))
        x += im.width + gap
    out.save(path)


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────

def next_run() -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[4:]) for p in runs.glob("run_*") if p.name[4:].isdigit()), default=0)
    out = runs / f"run_{n:03d}"
    out.mkdir()
    return out


def paint(painter: Any, run: Path, step: str, prompt: str, refs: list[Reference], mask: bytes | None = None
          ) -> bytes | None:
    (run / f"{step}_prompt.txt").write_text(prompt, encoding="utf-8")
    found = safe_depiction.blocking(prompt)
    if found:
        print(f"[{step}] stopped by safe depiction: {[f.said for f in found]}")
        return None
    if not guard(image_worst(refs, prompt), step):
        return None
    t = time.time()
    pic = painter(prompt, ASPECT, refs, quality=QUALITY, mask=mask)
    usd = book(run.name, step, IMAGE_MODEL, pic.input_tokens, pic.output_tokens, "done", step)
    (run / f"{step}.png").write_bytes(pic.data)
    print(f"[{step}] {pics.image_size(pic.data)} in {time.time() - t:.0f} s, ${usd:.4f} "
          f"(ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f})")
    return pic.data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "paid"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to these calls")
    ap.add_argument("--writer-from", help="reuse the writer answers of runs/<run>; edits it lacks are written")
    ap.add_argument("--only", default=DEFAULT_CALLS, help=f"image calls to make, from {CALLS}")
    args = ap.parse_args()
    only = [c.strip() for c in args.only.split(",") if c.strip()]
    if bad := [c for c in only if c not in CALLS]:
        raise SystemExit(f"unknown --only {bad}; choose from {CALLS}")
    s = Scene()
    add, change = s.edits["add"], s.edits["change"]
    n_add, n_change = add["after"], change["shot"]
    kinds = list(dict.fromkeys([SOLO[c] for c in only if c in SOLO]
                               + [k for c, k in (("add_strip", "add"), ("change_mask", "change")) if c in only]))

    def shot_of(kind: str) -> int:
        return NEW if kind == "add" else int(s.edits[kind]["shot"])

    reused: dict[str, Any] = {}
    if args.writer_from:
        src = HERE / "runs" / args.writer_from
        reused = {k: json.loads((src / f"writer_{k}.json").read_text(encoding="utf-8"))
                  for k in kinds if (src / f"writer_{k}.json").exists()}
    to_write = [k for k in kinds if k not in reused]

    if args.mode == "dry":
        run = HERE / "runs" / "dry"
        run.mkdir(parents=True, exist_ok=True)
        for kind in kinds:
            text, _ = writer_request(s, kind)
            (run / f"writer_{kind}_input.txt").write_text(writer_system() + "\n\n=====\n\n" + text, encoding="utf-8")
        panels = {k: panel_of(reused[k], shot_of(k)) if k in reused else stub_panel(s.edits[k]["plan"], shot_of(k))
                  for k in kinds}
        prompts = {c: solo(s, panels[SOLO[c]], SOLO[c])[0] for c in only if c in SOLO}
        if "add_strip" in only:
            prompts["add_strip"] = strip(s, panels["add"])[0]
        if "change_mask" in only:
            prompts["change_mask"] = masked(s, panels["change"], n_change)[0]
        for k, v in prompts.items():
            (run / f"{k}_prompt.txt").write_text(v, encoding="utf-8")
        for c in only:
            if c in SOLO:
                print(f"{c}: neighbours {neighbours(s, SOLO[c])}")
        worst = len(to_write) * dollars(WRITER_MODEL, WRITER_IN_WORST, WRITER_MAX_OUT) + sum(
            image_worst([Reference(label="x", data=b"")] * 4, v) for v in prompts.values())
        print(f"writer calls: {to_write or 'none'} (reused: {list(reused) or 'none'}); image calls: {only}")
        print(f"worst case: ${worst:.3f}; ledger ${spent():.3f} of ${LAB_BUDGET_USD:.2f}")
        print(f"prompts: {run}")
        return 0

    if not args.yes:
        print("paid needs --yes: the person's yes for these calls")
        return 2
    from cinematic.run import client  # the only place a client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    oa = client()
    run = next_run()
    print(f"=== {run.name} ===")
    raw = dict(reused)
    for k, v in reused.items():
        (run / f"writer_{k}.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in to_write:
        got = write_panel(oa, run, s, k)
        if not got:
            return 1
        raw[k] = got
    panels = {k: panel_of(raw[k], shot_of(k)) for k in kinds}

    painter = OpenAIImages(oa, model=IMAGE_MODEL, quality=QUALITY)
    old = [(f"SHOT {i}", s.panels[i], False) for i in range(1, 7)]

    def with_new(new: bytes) -> list[tuple[str, bytes, bool]]:
        return [*old[:n_add], ("NEW", new, True), *old[n_add:]]

    def changed(n: int) -> Any:
        return lambda new: [*old[:n - 1], (f"SHOT {n} (changed)", new, True), *old[n:]]

    report: dict[str, Any] = {"run": run.name, "quality": QUALITY, "writer_reused": list(reused)}

    for call in (c for c in only if c in SOLO):
        kind = SOLO[call]
        prompt, refs = solo(s, panels[kind], kind)
        if pic := paint(painter, run, call, prompt, refs):
            sheet((with_new if kind == "add" else changed(shot_of(kind)))(pic), run / f"{call}_sheet.png")
    for step, build, place in (("add_strip", lambda: strip(s, panels["add"]), with_new),
                               ("change_mask", lambda: masked(s, panels["change"], n_change), changed(n_change))):
        if step not in only:
            continue
        prompt, refs, sent, mask, hole = build()
        (run / f"{step}_sent.png").write_bytes(sent)
        (run / f"{step}_mask.png").write_bytes(mask)
        pic = paint(painter, run, step, prompt, refs, mask)
        if not pic:
            continue
        report[step] = drift(sent, pic, s.boxes, hole)
        print(f"[{step}] drift outside the mask: {report[step].get('outside_mask_mean', report[step])}")
        new_cell = pics.crop(pic, s.boxes[hole])
        (run / f"{step}_cell.png").write_bytes(new_cell)
        kept = {i + 1: pics.crop(sent, b) for i, b in enumerate(s.boxes) if i != hole}  # code pastes the rest back
        (run / f"{step}_pasted.png").write_bytes(pics.paste(pic, kept, {i + 1: b for i, b in enumerate(s.boxes)}))
        sheet(place(new_cell), run / f"{step}_sheet.png")
    report["spent_total"] = round(spent(), 4)
    (run / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"look at the *_sheet.png files in {run}; fill in runs/{run.name}/judge.md")
    (run / "judge.md").write_text(judge(only), encoding="utf-8")
    return 0


ROWS = ("same drawing: mannequins, finish, grade, level of detail",
        "mannequin colours right (Kasun red, office worker blue)",
        "same place: maroon three-wheeler, flask, cream cup, trays, tree and pole",
        "continuity with its neighbours (who stands where, faces which way, holds what)",
        "follows the new plan's camera",
        "no text, no numbers, no extra panels or gutters")


def judge(calls: list[str]) -> str:
    head = "| | " + " | ".join(calls) + " |\n|---|" + "---|" * len(calls) + "\n"
    body = "".join(f"| {r} |" + " |" * len(calls) + "\n" for r in ROWS)
    return ("# What the person reads (yes / no / partly + why)\n\nFor each *_sheet.png, does the red-tagged panel "
            "sit among the others unnoticed?\n\n" + head + body + "\nWriter (writer_*.json): did it keep the fixed "
            "world and the neighbours? Its conflicts?\n\nchange_solo vs change_solo_b: the same input twice; do both "
            "fit?\n")


if __name__ == "__main__":
    sys.exit(main())
