"""Prop mapping lab (2026-11-25): which way turns the board's clay props back into the RIGHT real props in a first
frame? PAID (the person's yes, 2026-11-25), cap $1.50.

The case: Love Hour scene 4 (de75bc31), board v22, shots 11 and 1 (`fetch.py`). The product's own frames are the
baseline: shot 11 painted a white umbrella (the clay's colour) AND a second, folded navy one from the look sheet, and a
dark phone although the phone sheet is orange; shot 1 a dark phone, and its prompt says both "Kasun ... gripping the
phone" (board) and "Kasun is not holding the phone. Anudi holds the phone" (ledger).

Each approach starts from the SAVED product prompt of the shot and changes only the prop parts:

    A  tier 1, the prop roster in words: every prop on the panel gets its sheet (umbrella, handbag; never the "bag"
       document case), one sentence per stand-in binding it to its image number by holder, hand and side, one state
       (the umbrella open), "each prop once", and one hands sentence (the ledger's contradicting line goes).
    B  tier 2: A + the panel's stand-ins outlined and numbered on the panel picture (boxes found by a vision model).
    C  tier 3: A's frame, then ONE masked edit of only the props' boxes against their sheets, pasted back by code.
    D  colours: the panel's clay props repainted each in its own flat colour (low edit of the panel), then A's words
       with "the yellow stand-in is the umbrella, image 8".

    .venv/Scripts/python.exe lab/prop_mapping/run.py dry
    .venv/Scripts/python.exe lab/prop_mapping/run.py detect 11 panel --yes
    .venv/Scripts/python.exe lab/prop_mapping/run.py A 11 --yes      (B, C, D the same; C needs A, B needs detect)
    .venv/Scripts/python.exe lab/prop_mapping/run.py sheet 11         (the side-by-side picture, free)

Nothing under `src/` changes and nothing is written to the database; `src/` is imported read-only for the image call.
The ledger refuses any call whose worst case passes the cap.
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
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(HERE)]

import httpx  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402

CAP = 1.50
MODEL = "gpt-image-2"
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the other board labs)
GEMINI = "gemini-3.5-flash"
GEMINI_PRICES = (0.50, 3.00)  # above list on purpose
LEDGER = HERE / "runs" / "ledger.csv"
IN = HERE / "input"
RUNS = HERE / "runs"


# ── the roster (what `contracts.props.shot_props` would give; written by hand for the lab) ───────────────────

@dataclass(frozen=True)
class Prop:
    key: str
    name: str  # the ONE name used everywhere in the prompt
    sheet: str  # input file, "" = words only
    look: str  # what it looks like, from its canon card
    where: str  # where the stand-in is on the panel: holder, hand, side
    state: str = ""
    colour: str = ""  # D: its stand-in colour
    find: str = ""  # what the detector looks for on the panel


PHONE_LOOK = "an orange iPhone with a transparent back cover"
UMBRELLA_LOOK = "a navy folding umbrella with a black curved handle"
HANDBAG_LOOK = "a medium tan faux-leather handbag with two short handles and brass-coloured fittings"
FLASK_LOOK = ("a scuffed two-litre stainless-steel vacuum flask with a dark-brown plastic handle and screw lid, a dull "
              "silver body with shallow dents")

ROSTER: dict[int, list[Prop]] = {
    11: [
        Prop("phone", "the phone", "prop_phone.png", PHONE_LOOK,
             "the flat clay shape in Anudi's right hand (the blue mannequin's), at chest height just right of centre",
             colour="bright green", find="the small flat object in the blue figure's right hand"),
        Prop("umbrella", "the umbrella", "prop_umbrella.png", UMBRELLA_LOOK,
             "the clay umbrella in Anudi's left hand, at frame right, its canopy above her", state="open over her head",
             colour="bright yellow", find="the umbrella (canopy and shaft) held by the blue figure"),
        Prop("handbag", "the handbag", "prop_handbag.png", HANDBAG_LOOK,
             "the clay bag hanging from Anudi's left forearm, at frame right below the umbrella hand",
             colour="purple", find="the handbag hanging from the blue figure's arm"),
        Prop("flask", "the tea flask", "", FLASK_LOOK,
             "the clay flask standing on the stainless serving ledge of the three-wheeler, at lower left",
             colour="cyan", find="the flask standing on the vehicle's serving ledge"),
    ],
    1: [
        Prop("phone", "the phone", "prop_phone.png", PHONE_LOOK,
             "the flat clay shape in Kasun's right hand (the red mannequin's), held out at the centre of the frame "
             "above Anudi's open right palm", colour="bright green",
             find="the small flat object passed between the two figures' hands"),
        Prop("umbrella", "the umbrella", "prop_umbrella.png", UMBRELLA_LOOK,
             "the clay umbrella in Anudi's left hand, at frame right, its canopy above her", state="open over her head",
             colour="bright yellow", find="the umbrella (canopy and shaft) held by the blue figure"),
        Prop("handbag", "the handbag", "prop_handbag.png", HANDBAG_LOOK,
             "the clay bag hanging by its handles from Anudi's left forearm, at lower right", colour="purple",
             find="the handbag hanging from the blue figure's arm"),
        Prop("flask", "the tea flask", "", FLASK_LOOK,
             "the clay flask standing on the right end of the three-wheeler's stainless serving ledge, at lower left",
             colour="cyan", find="the flask standing on the vehicle's serving ledge"),
    ],
}

# The saved product words this lab replaces (each must be found exactly once).
OLD_LIST = "image 7 is the reference sheet for phone (held by Anudi); image 8 is the approved scene board panel of this shot"
OLD_JOB = "image 7: phone exactly as shown."
OLD_PROPS = ("The approved scene board panel shows the props as plain white clay stand-ins: they mark where each prop "
             "is, its size, its angle and the hand that holds it, nothing more. Paint every one as the real prop from "
             "its reference sheet, in exactly that place and hand. No white clay shape, blank object or unfinished "
             "prop remains in the frame.")
OLD_LEDGER = "Hands: Kasun is not holding the phone. Anudi holds the phone in one hand. "
OLD_BLOCKING = "the props as white clay stand-ins: take from it"


def swap(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{what}: expected the saved words once, found {text.count(old)}")
    return text.replace(old, new)


def saved(case: int) -> dict:
    return json.loads((IN / f"frame_shot{case}.json").read_text(encoding="utf-8"))


def sheets(case: int) -> list[Prop]:
    return [p for p in ROSTER[case] if p.sheet]


def image_of(case: int) -> dict[str, int]:
    return {p.key: 7 + i for i, p in enumerate(sheets(case))}


def panel_number(case: int) -> int:
    return 7 + len(sheets(case))


def base_refs(case: int) -> list[Reference]:
    """The saved frame's pictures in its order (images 1-6), then each prop sheet, then the panel (LAST)."""
    out = [Reference(label="the face sheet for Kasun", data=(IN / "kasun_face.png").read_bytes()),
           Reference(label="the face sheet for Anudi", data=(IN / "anudi_face.png").read_bytes()),
           Reference(label="the look sheet for Kasun", data=(IN / "kasun_look.png").read_bytes()),
           Reference(label="the look sheet for Anudi", data=(IN / "anudi_look.png").read_bytes()),
           Reference(label="view 1 (wide) of the location sheet for Colombo roadside",
                     data=(IN / f"view_shot{case}.png").read_bytes()),
           Reference(label="the vehicle plate for Food three-wheeler", data=(IN / "vehicle_plate.png").read_bytes())]
    out += [Reference(label=f"the reference sheet for {p.name[4:]}", data=(IN / p.sheet).read_bytes())
            for p in sheets(case)]
    return out


def roster_words(case: int, *, marks: bool = False, colours: bool = False) -> str:
    """The binding paragraph that replaces `PROP_STAND_INS`."""
    imgs = image_of(case)
    bits = []
    for i, p in enumerate(ROSTER[case], 1):
        where = p.where.replace("clay ", f"{p.colour} clay ", 1) if colours else p.where
        mark = f" (mark {i} on the panel)" if marks else ""
        state = f", {p.state}" if p.state else ""
        what = (f"paint it exactly as image {imgs[p.key]} shows it ({p.look}){state}" if p.key in imgs
                else f"it has no picture: paint {p.look}{state}")
        bits.append(f"{where}{mark} is {p.name}: {what}")
    head = ("The approved scene board panel shows each prop as a clay stand-in in its own flat colour, so you can "
            "tell them apart; the colour is never the prop's colour. Each stand-in marks only where a real prop is, "
            "its size, its angle and the hand that holds it." if colours else
            "The approved scene board panel shows the props as plain white clay stand-ins. White is never a prop's "
            "colour: each stand-in marks only where a real prop is, its size, its angle and the hand that holds it.")
    left = ("No clay shape and none of the stand-in colours (" + ", ".join(p.colour for p in ROSTER[case]) +
            ") remains on any prop in the frame." if colours else
            "No white clay shape, blank object or unfinished prop remains in the frame.")
    marks_line = (" The outlines and numbers on the panel are marks on the sketch only: draw no outline, circle, "
                  "number or label in the frame." if marks else "")
    return (f"{head} These are the props, each exactly once: " + "; ".join(bits) + ". Each prop appears once: the "
            "umbrella and the handbag on Anudi's look sheet are these same things, never a second umbrella or bag. "
            "Keep the panel's layout, proportions and perspective for every prop; add no other prop. " + left
            + marks_line)


def prompt_for(case: int, *, marks: bool = False, colours: bool = False) -> str:
    text = saved(case)["prompt"]
    imgs = image_of(case)
    names = "; ".join(f"image {imgs[p.key]} is the reference sheet for {p.name[4:]}" for p in sheets(case))
    text = swap(text, OLD_LIST, f"{names}; image {panel_number(case)} is the approved scene board panel of this "
                                f"shot" + (", its props outlined and numbered" if marks else ""), "reference list")
    jobs = "; ".join(f"image {imgs[p.key]}: {p.name[4:]} exactly as shown ({p.look}), not its backdrop or light"
                     for p in sheets(case))
    text = swap(text, OLD_JOB, jobs + ".", "prop jobs")
    text = swap(text, OLD_PROPS, roster_words(case, marks=marks, colours=colours), "stand-in paragraph")
    text = swap(text, OLD_LEDGER, "", "ledger hands")  # one hands sentence: the board's, which the plan agrees with
    if colours:
        text = swap(text, OLD_BLOCKING, "the props as clay stand-ins, each in its own flat colour: take from it",
                    "blocking paragraph")
    return text


# ── money ──────────────────────────────────────────────────────────────────────────────────────────────────

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


def image_usd(inp: int, out: int) -> float:
    return inp * PRICES[0] / 1e6 + out * PRICES[1] / 1e6


def worst(refs: list[Reference], prompt: str, quality: str) -> float:
    return image_usd(1800 * len(refs) + len(prompt) // 3, 500 if quality == "low" else 2200)  # medium was 1372


def guard(w: float) -> None:
    if spent() + w > CAP:
        raise SystemExit(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${CAP:.2f} cap")


def painter(quality: str):
    from cinematic.run import client  # the only place a lab client is built; it reads .env

    from hiru_ai.adapters.images import OpenAIImages

    return OpenAIImages(client(), model=MODEL, quality=quality)


def paint(case: int, step: str, prompt: str, refs: list[Reference], quality: str, mask: bytes | None = None,
          aspect: str = "9:16") -> bytes:
    found = safe_depiction.blocking(prompt)
    if found:
        raise SystemExit(f"blocked by safe depiction: {found}")
    guard(worst(refs, prompt, quality))
    out = RUNS / f"shot{case}"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{step}_prompt.txt").write_text(prompt, encoding="utf-8")
    (out / f"{step}_refs.json").write_text(json.dumps([r.label for r in refs], indent=1), encoding="utf-8")
    t = time.time()
    pic = painter(quality)(prompt, aspect, refs, quality=quality, mask=mask)
    usd = image_usd(pic.input_tokens, pic.output_tokens)
    book(f"shot{case}", step, MODEL, pic.input_tokens, pic.output_tokens, usd, quality)
    (out / f"{step}.png").write_bytes(pic.data)
    print(f"shot {case} {step}: ${usd:.4f} in {round(time.time() - t)} s; ledger ${spent():.3f} of ${CAP:.2f}")
    return pic.data


# ── boxes (Gemini's documented box detection, 0-1000, [ymin, xmin, ymax, xmax]) ─────────────────────────────

def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def detect(case: int, picture: bytes, what: str, tag: str) -> dict[str, list[int]]:
    """Each roster prop's box on `picture`, by its key."""
    guard(0.01)
    items = "; ".join(f"\"{p.key}\": {p.find if what == 'panel' else p.name[4:] + ' (' + p.where.split(',')[0]
                                                                                 .replace('the clay ', 'the ')
                                                                                 .replace('the flat clay shape', 'the object') + ')'}"
                      for p in ROSTER[case])
    ask = (f"Detect these objects in the picture and give the box of each: {items}. Return a JSON list of objects "
           "{\"label\": <the key>, \"box_2d\": [ymin, xmin, ymax, xmax]} with coordinates normalised to 0-1000. Each "
           "label once; the box covers the whole object (an umbrella's canopy and shaft). Leave out an object you "
           "cannot see.")
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/png",
                                                     "data": base64.b64encode(picture).decode()}},
                                    {"text": ask}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0,
                                 }}
    key = env()["GOOGLE__API_KEY"]
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI}:generateContent",
                   headers={"x-goog-api-key": key}, json=body, timeout=120)
    r.raise_for_status()
    data = r.json()
    use = data.get("usageMetadata") or {}
    inp, out = (int(use.get("promptTokenCount") or 0),
                int(use.get("candidatesTokenCount") or 0) + int(use.get("thoughtsTokenCount") or 0))
    usd = inp * GEMINI_PRICES[0] / 1e6 + out * GEMINI_PRICES[1] / 1e6
    book(f"shot{case}", f"detect_{tag}", GEMINI, inp, out, usd, what)
    text = "".join(x.get("text", "") for x in data["candidates"][0]["content"]["parts"] if not x.get("thought"))
    boxes = {str(x["label"]): [int(v) for v in x["box_2d"]] for x in json.loads(text)}
    d = RUNS / f"shot{case}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"boxes_{tag}.json").write_text(json.dumps(boxes, indent=1), encoding="utf-8")
    (d / f"boxes_{tag}.png").write_bytes(draw_marks(picture, case, boxes, numbered=False))
    print(f"shot {case} detect {tag}: {boxes} (${usd:.4f})")
    return boxes


def to_px(box: list[int], w: int, h: int) -> tuple[int, int, int, int]:
    y0, x0, y1, x1 = box
    return round(x0 * w / 1000), round(y0 * h / 1000), round(x1 * w / 1000), round(y1 * h / 1000)


def draw_marks(picture: bytes, case: int, boxes: dict[str, list[int]], numbered: bool = True) -> bytes:
    """Each prop's box outlined, with its roster number in a small tag at the top-left corner."""
    im = Image.open(io.BytesIO(picture)).convert("RGB")
    d = ImageDraw.Draw(im)
    w, h = im.size
    size = max(12, round(w / 22))
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    line = max(2, round(w / 220))
    for i, p in enumerate(ROSTER[case], 1):
        if p.key not in boxes:
            continue
        x0, y0, x1, y1 = to_px(boxes[p.key], w, h)
        pad = round(w / 120)
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad)
        d.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=line + 2)
        d.rectangle([x0, y0, x1, y1], outline=(255, 235, 0), width=line)
        tag = str(i) if numbered else p.key
        tw = d.textlength(tag, font=font)
        tx, ty = x0, max(0, y0 - size - 6)
        d.rectangle([tx, ty, tx + tw + 8, ty + size + 6], fill=(0, 0, 0))
        d.text((tx + 4, ty + 2), tag, fill=(255, 235, 0), font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ── the approaches ─────────────────────────────────────────────────────────────────────────────────────────

def run_a(case: int) -> None:
    refs = base_refs(case) + [Reference(label="the approved scene board panel of this shot",
                                        data=(IN / f"panel_shot{case}.png").read_bytes())]
    paint(case, "A", prompt_for(case), refs, "medium")


def run_b(case: int) -> None:
    boxes_file = RUNS / f"shot{case}" / "boxes_panel.json"
    if not boxes_file.exists():
        raise SystemExit("run `detect <case> panel` first")
    boxes = json.loads(boxes_file.read_text(encoding="utf-8"))
    marked = draw_marks((IN / f"panel_shot{case}.png").read_bytes(), case, boxes)
    (RUNS / f"shot{case}" / "B_panel.png").write_bytes(marked)
    refs = base_refs(case) + [Reference(label="the approved scene board panel of this shot", data=marked)]
    paint(case, "B", prompt_for(case, marks=True), refs, "medium")


def run_c(case: int) -> None:
    a = RUNS / f"shot{case}" / "A.png"
    if not a.exists():
        raise SystemExit("run A first")
    frame = a.read_bytes()
    boxes = detect(case, frame, "frame", "A")
    im = Image.open(io.BytesIO(frame)).convert("RGB")
    w, h = im.size
    keep = [p for p in sheets(case) if p.key in boxes]
    # the mask: transparent (alpha 0) where the edit may change the picture, opaque elsewhere (OpenAI's convention)
    alpha = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(alpha)
    pad = round(w / 40)
    rects = []
    for p in keep:
        x0, y0, x1, y1 = to_px(boxes[p.key], w, h)
        r = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
        rects.append(r)
        d.rectangle(r, fill=0)
    mask_im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    mask_im.putalpha(alpha)
    buf = io.BytesIO()
    mask_im.save(buf, format="PNG")
    mask = buf.getvalue()
    (RUNS / f"shot{case}" / "C_mask.png").write_bytes(mask)
    refs = [Reference(label="the finished frame", data=frame)]
    refs += [Reference(label=f"the reference sheet for {p.name[4:]}", data=(IN / p.sheet).read_bytes()) for p in keep]
    lines = "; ".join(f"{p.name} ({p.where.replace('the clay ', 'the ').replace('the flat clay shape', 'the object')}"
                      f") must be exactly the {p.name[4:]} of image {i}: {p.look}" + (f", {p.state}" if p.state else "")
                      for i, p in enumerate(keep, 2))
    prompt = ("Image 1 is a finished photorealistic film frame. Change ONLY the props, and only inside the masked "
              f"areas: {lines}. Each prop keeps its exact place, size, angle and the hand that holds it, and each "
              "appears once; fingers stay around a held prop. Change nothing else: the faces, hands, skin, clothes, "
              "hair, the place, the rain, the light, the colours and the camera stay exactly as they are in image 1. "
              "Images " + ", ".join(str(i) for i in range(2, len(keep) + 2)) + " are product pictures: take only "
              "the object from each, not its backdrop or light. Draw no text.")
    edited = paint(case, "C_edit", prompt, refs, "medium", mask=mask)
    # paste back ONLY the masked boxes (feathered), so the rest of A stays pixel for pixel (OpenAI's own advice)
    ed = Image.open(io.BytesIO(edited)).convert("RGB").resize((w, h))
    soft = alpha.point(lambda v: 255 - v).filter(ImageFilter.GaussianBlur(round(w / 150)))
    out = Image.composite(ed, im, soft)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    (RUNS / f"shot{case}" / "C.png").write_bytes(buf.getvalue())
    print(f"shot {case} C: composited {len(rects)} boxes")


def run_d(case: int) -> None:
    d = RUNS / f"shot{case}"
    coloured = d / "D_panel.png"
    if not coloured.exists():
        lines = "; ".join(f"{p.where.split(' is ')[0]} becomes {p.colour}" for p in ROSTER[case])
        prompt = ("This is a storyboard panel: two coloured mannequins (red and blue) in a real street, with white "
                  "clay stand-ins for the props. Recolour ONLY the white clay prop stand-ins, each to one flat, "
                  f"matte, solid colour: {lines}. Each stand-in keeps exactly its shape, size, place and the hand "
                  "that holds it. Change nothing else: the mannequins keep their colours and poses, the street, the "
                  "vehicle, the light, the rain and the framing stay exactly the same. No text or labels.")
        data = paint(case, "D_recolour", prompt,
                     [Reference(label="the storyboard panel", data=(IN / f"panel_shot{case}.png").read_bytes())],
                     "low")
        coloured.write_bytes(data)
    refs = base_refs(case) + [Reference(label="the approved scene board panel of this shot",
                                        data=coloured.read_bytes())]
    paint(case, "D", prompt_for(case, colours=True), refs, "medium")


# ── the picture for the person ─────────────────────────────────────────────────────────────────────────────

def contact(case: int) -> Path:
    d = RUNS / f"shot{case}"
    cols = [("board panel", IN / f"panel_shot{case}.png"), ("baseline (product today)", IN / f"frame_shot{case}.png"),
            ("A  roster words", d / "A.png"), ("B  + numbered marks", d / "B.png"),
            ("C  + props pass", d / "C.png"), ("D  coloured props", d / "D.png")]
    extra = [("B panel sent", d / "B_panel.png"), ("D panel sent", d / "D_panel.png")]
    h, gap, top = 900, 14, 46
    ims = []
    for label, path in cols + extra:
        if path.exists():
            im = Image.open(path).convert("RGB")
            ims.append((label, im.resize((round(im.width * h / im.height), h))))
    width = sum(im.width for _, im in ims) + gap * (len(ims) - 1)
    out = Image.new("RGB", (width, h + top), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arialbd.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    x = 0
    for label, im in ims:
        out.paste(im, (x, top))
        draw.text((x + 6, 8), label, fill=(0, 0, 0), font=font)
        x += im.width + gap
    path = d / f"compare_shot{case}.jpg"
    out.save(path, quality=88)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "detect", "A", "B", "C", "D", "sheet"])
    ap.add_argument("case", nargs="?", type=int, default=11)
    ap.add_argument("what", nargs="?", default="panel")
    ap.add_argument("--yes", action="store_true", help="the person said yes to paid calls (2026-11-25, cap $1.50)")
    a = ap.parse_args()
    if a.mode == "dry":
        for case in ROSTER:
            for name, kw in (("A", {}), ("B", {"marks": True}), ("D", {"colours": True})):
                p = prompt_for(case, **kw)
                out = RUNS / "dry"
                out.mkdir(parents=True, exist_ok=True)
                (out / f"shot{case}_{name}.txt").write_text(p, encoding="utf-8")
                refs = base_refs(case) + [Reference(label="panel", data=b"")]
                print(f"shot {case} {name}: {len(p)} chars, {len(refs)} pictures, worst ${worst(refs, p, 'medium'):.3f}"
                      + (f" BLOCKED {safe_depiction.blocking(p)}" if safe_depiction.blocking(p) else ""))
        print(f"ledger ${spent():.3f} of ${CAP:.2f}")
        return 0
    if a.mode == "sheet":
        print(contact(a.case))
        return 0
    if not a.yes:
        print("needs --yes")
        return 2
    RUNS.mkdir(exist_ok=True)
    if a.mode == "detect":
        detect(a.case, (IN / f"panel_shot{a.case}.png").read_bytes(), "panel", "panel")
    else:
        {"A": run_a, "B": run_b, "C": run_c, "D": run_d}[a.mode](a.case)
    return 0


if __name__ == "__main__":
    sys.exit(main())
