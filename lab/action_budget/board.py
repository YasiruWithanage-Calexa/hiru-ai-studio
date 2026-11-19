"""Action-budget lab (2026-11-18): the Scene board of a re-planned scene, painted the way the product paints one
(`hiru_ai.systems.frame_render.board`): `board_writer` writes the panels, `contracts.board.board_prompt` the picture's
prompt, gpt-image-2 paints all panels at once at LOW, code cuts the cells and draws the numbered sheet.

    python lab/action_budget/board.py --run replan2 --scene E01-S02 --yes      paid: one board_writer call + one LOW image

No reference pictures (no canon sheets exist outside the database). Nothing is stored in Supabase.
Output: runs/<run>/<scene>/board/ (sheet.png, board.png, cell_NN.png, writer.json, prompt.txt, spend.txt).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "coverage"), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

import run as lab  # noqa: E402  (lab/coverage/run.py: the world and shot rows as the product writes them)

PRICES = {"gpt-6.1-sol": (2.00, 0.10, 10.00), "gpt-image-2": (10.00, 10.00, 40.00)}  # $ per 1M (lab/storyboard)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="replan2")
    ap.add_argument("--scene", default="E01-S02")
    ap.add_argument("--yes", action="store_true", help="the person said yes (2026-11-18: 'i want to see scene board')")
    a = ap.parse_args()
    if not a.yes:
        raise SystemExit("paid: one board_writer call and one LOW image. Add --yes after the person's yes.")
    from cinematic.run import load_env

    from contracts import board as kit
    from hiru_ai.adapters import images
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.settings import get_settings
    from hiru_ai.systems.frame_render import board as boards
    from hiru_ai.systems.frame_render import pictures as pics

    load_env()
    get_settings.cache_clear()
    lab.SID = a.scene
    plan = HERE / "runs" / a.run / a.scene / "12_raphael" / f"{a.scene}.json"
    out = HERE / "runs" / a.run / a.scene / "board"
    w = lab.world()
    shots, lines = lab.shot_rows(w, json.loads(plan.read_text(encoding="utf-8"))["result"])
    for s in shots:
        s.setdefault("id", f"shot-{s['number']}")
    world: dict[str, Any] = {"production": w["production"], "canon": w["canon"], "scene": w["scene"],
                             "shots": shots, "lines": lines}
    usage: list[dict[str, Any]] = []
    ctx = RunContext(usage_sink=usage.append)
    b = boards.Board(ctx, world)
    out.mkdir(parents=True, exist_ok=True)

    t = time.time()
    writer = boards.write(ctx, b)
    (out / "writer.json").write_text(json.dumps(writer.dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    missing = kit.missing_panels(writer, [s.number for s in b.painted])
    if missing:
        raise SystemExit(f"the writer left out {missing}")
    numbers = [s.number for s in b.painted]
    aspect = kit.board_aspect("16:9")
    prompt = kit.board_prompt(writer, numbers, [], b.colours, aspect)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    picture = images.build(sink=usage.append)(prompt, aspect, [], quality="low")
    (out / "board.png").write_bytes(picture.data)
    boxes = pics.cell_boxes(picture.data, len(numbers))
    crops = {}
    for s in b.painted:
        data = pics.crop(picture.data, [int(v) for v in boxes[numbers.index(s.number)]])
        (out / f"cell_{s.number:02d}.png").write_bytes(data)
        crops[s.id] = data
    (out / "sheet.png").write_bytes(pics.scene_sheet(b.shots, crops))

    dollars = 0.0
    for u in usage:
        p = PRICES["gpt-image-2" if "image" in str(u.get("model") or "") else "gpt-6.1-sol"]
        i, c, o = (int(u.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        dollars += (i - c) * p[0] / 1e6 + c * p[1] / 1e6 + o * p[2] / 1e6
    line = f"{len(usage)} calls, {time.time() - t:.0f} s, ${dollars:.4f}; colours {b.colours}"
    (out / "spend.txt").write_text(line + "\n", encoding="utf-8")
    print(line)
    print(f"written: {out}")


if __name__ == "__main__":
    main()
