"""The Scene board of the coverage plan (2026-11-18): Api Denna E01-S03 as Raphael planned it with the coverage rule
(runs/coverage/12_raphael/E01-S03.json), painted the way the product paints a board
(`hiru_ai.systems.frame_render.board`): the `board_writer` reads every shot's plan and writes the panels,
`contracts.board.board_prompt` writes the picture's prompt, `gpt-image-2` paints all panels at once at LOW, code
cuts the cells and draws the numbered sheet.

    python lab/coverage/board.py --yes        paid: one board_writer call + one LOW image

No reference pictures (no canon sheets exist outside the database), so the image is painted from words alone
(`images.generate`). Nothing is stored in Supabase. Output: runs/coverage/board/ (board.png, cell_NN.png, sheet.png,
writer.json, prompt.txt, spend.txt).
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
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

import run as lab  # noqa: E402  (lab/coverage/run.py)

OUT = HERE / "runs" / "coverage" / "board"
PLAN = HERE / "runs" / "coverage" / "12_raphael" / f"{lab.SID}.json"
PRICES = {"gpt-6.1-sol": (2.00, 0.10, 10.00), "gpt-image-2": (10.00, 10.00, 40.00)}  # $ per 1M (lab/storyboard)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="the person said yes (2026-11-18: 'create an actual image')")
    if not ap.parse_args().yes:
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
    w = lab.world()
    shots, lines = lab.shot_rows(w, json.loads(PLAN.read_text(encoding="utf-8"))["result"])
    for s in shots:
        s.setdefault("id", f"shot-{s['number']}")
    world: dict[str, Any] = {"production": w["production"], "canon": w["canon"], "scene": w["scene"],
                             "shots": shots, "lines": lines}
    usage: list[dict[str, Any]] = []
    ctx = RunContext(usage_sink=usage.append)
    b = boards.Board(ctx, world)
    OUT.mkdir(parents=True, exist_ok=True)

    t = time.time()
    writer = boards.write(ctx, b)
    (OUT / "writer.json").write_text(json.dumps(writer.dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    missing = kit.missing_panels(writer, [s.number for s in b.painted])
    if missing:
        raise SystemExit(f"the writer left out {missing}")
    numbers = [s.number for s in b.painted]
    aspect = kit.board_aspect("16:9")
    prompt = kit.board_prompt(writer, numbers, [], b.colours, aspect)
    (OUT / "prompt.txt").write_text(prompt, encoding="utf-8")
    painter = images.build(sink=usage.append)
    picture = painter(prompt, aspect, [], quality="low")
    (OUT / "board.png").write_bytes(picture.data)
    boxes = pics.cell_boxes(picture.data, len(numbers))
    crops = {}
    for s in b.painted:
        data = pics.crop(picture.data, [int(v) for v in boxes[numbers.index(s.number)]])
        (OUT / f"cell_{s.number:02d}.png").write_bytes(data)
        crops[s.id] = data
    (OUT / "sheet.png").write_bytes(pics.scene_sheet(b.shots, crops))

    dollars = 0.0
    for u in usage:
        model = str(u.get("model") or "")
        p = PRICES.get("gpt-image-2" if "image" in model else "gpt-6.1-sol")
        i, c, o = (int(u.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        dollars += (i - c) * p[0] / 1e6 + c * p[1] / 1e6 + o * p[2] / 1e6
    line = f"{len(usage)} calls, {time.time() - t:.0f} s, ${dollars:.4f}; colours {b.colours}"
    (OUT / "spend.txt").write_text(line + "\n", encoding="utf-8")
    print(line)
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
