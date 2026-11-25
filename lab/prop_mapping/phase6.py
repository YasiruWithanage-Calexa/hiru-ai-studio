"""plan/2026-11-25b phase 6 (the person's yes, 2026-11-25): the PRODUCT's first frame of Love Hour scene 4 shots 11 and
1, painted from board v22 with the built prop roster, beside the lab's A frame and the product's baseline.

The product's own code end to end, as `frame_render.graph.render_frame` runs it: the real Supabase reads (`Scenes.world`,
`_board_panel`, `_panel_breaks_a_fact`, `_references`), the views swap, the `frame_compose` compose op, the safe
depiction stop and the product painter at MEDIUM. What it leaves out: the frame row's claim and finish, the upload, the
`token_usage` row and the frame check (a second model call). Nothing is written to the database or the buckets; the
picture, its prompt and its labels are saved under `runs/phase6/`.

    .venv/Scripts/python.exe lab/prop_mapping/phase6.py dry          (free: the prompts and labels only)
    .venv/Scripts/python.exe lab/prop_mapping/phase6.py paint --yes  (paid, cap $0.70)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab" / "fixed_marks")]

import fetch  # noqa: E402  (read-only helper: GET only)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from contracts import safe_depiction  # noqa: E402
from hiru_ai.adapters import images as painter_kit  # noqa: E402
from hiru_ai.adapters import supabase_rest  # noqa: E402
from hiru_ai.core.context import RunContext  # noqa: E402
from hiru_ai.core.ports import Reference  # noqa: E402
from hiru_ai.core.settings import get_settings  # noqa: E402
from hiru_ai.systems.frame_render import graph  # noqa: E402

CAP = 0.70
PRICES = (10.00, 40.00)  # USD per 1M input / output image tokens, above list on purpose (as the lab)
OUT = HERE / "runs" / "phase6"
LEDGER = OUT / "ledger.csv"
IN = HERE / "input"
CASES = json.loads((IN / "cases.json").read_text(encoding="utf-8"))


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


def book(shot: int, inp: int, out: int, usd: float) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "shot", "model", "input_tokens", "output_tokens", "usd", "note"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), shot, "gpt-image-2", inp, out, f"{usd:.5f}", "medium"])


def context() -> tuple[RunContext, graph.Scenes]:
    ports = supabase_rest.build_ports(get_settings())
    production = fetch.rows("productions", id=f"eq.{fetch.PROD}", select="*")[0]
    ctx = RunContext(production_id=UUID(str(production["id"])), ports=ports)
    return ctx, graph.Scenes(ctx, production)


def frame_of(ctx: RunContext, scenes: graph.Scenes, n: int) -> tuple[str, list[Reference], str]:
    """(prompt, pictures in order, aspect) exactly as `render_frame` builds them for a final from the board."""
    case = CASES[str(n)]
    shot = ctx.need("frames").shot(case["shot_id"])
    world = scenes.world(str(shot["scene_id"]))
    board_id = case["board_id"]
    from_prompt = not graph._compose("shot_prompt", **world, shot=shot)["reasons"]
    faults = graph._panel_breaks_a_fact(ctx, board_id, shot)
    if faults:
        raise SystemExit(f"shot {n}: the panel would not be attached: {faults}")
    panel, board = graph._board_panel(ctx, scenes, board_id, shot, blocking=from_prompt)
    refs = graph._references(ctx, world, shot, board.get("panel"))
    pictures = [r for _, _, r in refs]
    pictures.append(panel)
    for swap in (graph._view_picture(ctx, world, int(board.get("view") or 0)),
                 graph._vehicle_view_picture(ctx, world, shot, int(board.get("view") or 0))):
        if swap is None:
            continue
        plate, view_pic, said = swap
        at = next((i for i, p in enumerate(pictures) if p.label == plate), None)
        if at is not None:
            pictures[at] = view_pic
            board["sections"] = [*board["sections"], said]
            break
    composed = graph._compose("compose", **world, shot=shot, labels=[r.label for r in pictures],
                              board=board["sections"], panel=board.get("panel"))
    aspect = graph.parts.module("step", "frame_compose").production_aspect(scenes.production)
    return composed["prompt"], pictures, aspect


def save_inputs(n: int, prompt: str, pictures: list[Reference]) -> Path:
    d = OUT / f"shot{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.txt").write_text(prompt, encoding="utf-8")
    (d / "refs.json").write_text(json.dumps([r.label for r in pictures], indent=1), encoding="utf-8")
    return d


def worst(pictures: list[Reference], prompt: str) -> float:
    return (1800 * len(pictures) + len(prompt) // 3) * PRICES[0] / 1e6 + 2200 * PRICES[1] / 1e6


def contact(n: int) -> Path:
    d = OUT / f"shot{n}"
    cols = [("board panel", IN / f"panel_shot{n}.png"), ("baseline (before)", IN / f"frame_shot{n}.png"),
            ("lab A", HERE / "runs" / f"shot{n}" / "A.png"), ("PRODUCT (phase 6)", d / "frame.png")]
    h, gap, top = 900, 14, 46
    ims = [(label, Image.open(p).convert("RGB")) for label, p in cols if p.exists()]
    ims = [(label, im.resize((round(im.width * h / im.height), h))) for label, im in ims]
    out = Image.new("RGB", (sum(im.width for _, im in ims) + gap * (len(ims) - 1), h + top), (255, 255, 255))
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
    path = d / f"compare_shot{n}.jpg"
    out.save(path, quality=88)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "paint", "sheet"])
    ap.add_argument("--shots", default="11,1")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    shots = [int(s) for s in a.shots.split(",")]
    if a.mode == "sheet":
        for n in shots:
            print(contact(n))
        return 0
    ctx, scenes = context()
    paint: Any = None
    if a.mode == "paint":
        if not a.yes:
            raise SystemExit("paid: add --yes")
        paint = painter_kit.build(get_settings())  # no sink: no token_usage row
    for n in shots:
        prompt, pictures, aspect = frame_of(ctx, scenes, n)
        d = save_inputs(n, prompt, pictures)
        print(f"shot {n}: {len(pictures)} pictures, {len(prompt)} chars, aspect {aspect} -> {d}")
        for i, r in enumerate(pictures, 1):
            print(f"   image {i}: {r.label}")
        found = safe_depiction.blocking(prompt)
        if found:
            raise SystemExit(f"shot {n}: blocked by safe depiction: {found}")
        if paint is None:
            continue
        w = worst(pictures, prompt)
        if spent() + w > CAP:
            raise SystemExit(f"NOT SENT: ${spent():.3f} spent + ${w:.3f} worst case > ${CAP:.2f}")
        t = time.time()
        pic = paint(prompt, aspect, pictures, quality="medium")
        usd = (pic.input_tokens * PRICES[0] + pic.output_tokens * PRICES[1]) / 1e6
        book(n, pic.input_tokens, pic.output_tokens, usd)
        (d / "frame.png").write_bytes(pic.data)
        print(f"   painted: ${usd:.4f} in {round(time.time() - t)} s; phase 6 ledger ${spent():.3f} of ${CAP:.2f}")
        print(f"   {contact(n)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
