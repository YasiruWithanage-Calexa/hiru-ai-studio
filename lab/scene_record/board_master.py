"""ONE scene board (the product's grid of mannequin panels) painted from the MASTER FLOOR PLAN.

    .venv/Scripts/python.exe lab/scene_record/board_master.py --run 005_canal_sol --scene canal          free: prompt
    .venv/Scripts/python.exe lab/scene_record/board_master.py --run 005_canal_sol --scene canal --yes    PAID: 1 board

The person's design (2026-11-28): one master floor plan for the whole scene (the place, every person's positions in
story order, the walks, every camera setup labelled C1, C2 ...) goes with the board as a reference picture, and each
panel's words pick its camera on that plan by name and give the framing, the blocking (pins on the plan) and the
eyeline. The words per panel are `shot_paint.ShotPlans` (the same as for a single shot); the sheet is
`contracts.board.board_prompt` (the product's grid, mannequins, clay props). The canal also attaches its location
views sheet. Budget for this run: $0.30 (the person). Writes runs/<run>/painted_master/: prompt.txt, master_plan.png,
board.png, panel_<shot>.jpg, compare.html (each panel beside its camera words).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(ROOT / "scripts")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from board_paint import Panels, views_ref  # noqa: E402
from schema import SceneRecord  # noqa: E402
from shot_paint import ShotPlans  # noqa: E402

from contracts import board as kit  # noqa: E402
from contracts import safe_depiction  # noqa: E402

MODEL, QUALITY, BUDGET_USD = "gpt-image-2", "medium", 0.30
PRICE = {"text_in": 5.00, "image_in": 8.00, "out": 30.00}
LEDGER = HERE / "runs" / "board_master_ledger.json"
MASTER = "the master floor plan of this scene seen from above"
BOARD_GUIDE = (
    "Image {n} is the MASTER FLOOR PLAN of this scene seen from above (north is up), one plan for every panel: the "
    "place drawn flat (blue water, brown earth and paths, green fields, grey concrete or stone) with its names; each "
    "round pin is a person at one moment, in that person's mannequin colour, labelled with their initial and a number "
    "in story order (A1, A2 ...); an orange dashed line is a walk; each triangle is a camera position "
    "labelled C1, C2 ..., pointing the way it looks. Every panel below names the camera it is seen from and where "
    "each person is on the plan at that instant. Paint each panel as that camera sees it from where it stands: the "
    "people, things and place in front of it, on the same sides of the frame as the plan puts them, near things "
    "large and far things small, framed exactly as the panel says (how much of the body the frame holds). Panels "
    "from the same camera share the same background. A person looks where the panel says, off the lens, never into "
    "the camera. Never draw the plan, its pins, triangles, arrows, lines or any of its words in a panel.")


PREVIZ = "a rough 3D blocking render of this exact board, the same panels in the same grid"
PREVIZ_GUIDE = (
    "Image 1 is a rough 3D blocking render of THIS board: the same grid, the same panels in the same order, each "
    "rendered from its camera on the floor plan with the real lens. Keep each panel's composition exactly as image "
    "1 has it: where the camera stands and how high, the angle, how tight the frame is, where every figure stands in "
    "the frame and how big, its posture, which way its body and head turn (the small cone on each head is the "
    "nose), where every white block (a prop) is, and where the water, the path, the bank and the gate fall in the "
    "frame. Then paint it as a finished storyboard: the place as the real place (its look from the location sheet), "
    "the people as smooth, matte, faceless artist's mannequins in the same colours with jointed limbs and real "
    "proportions, and each white block as the real prop in white clay. Never copy the render's flat colours, plain "
    "sky or simple shapes; never move a figure, a prop or the camera from where image 1 puts them.")


def spent() -> float:
    return sum(r["usd"] for r in json.loads(LEDGER.read_text())) if LEDGER.exists() else 0.0


def para(prompt: str, head: str) -> str:
    return next((x for x in prompt.split("\n\n") if x.startswith(head)), "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--yes", action="store_true", help="PAID: paint one board")
    ap.add_argument("--previz", action="store_true", help="paint over the 3D blocking render (previz.py's grid)")
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    out = run / ("painted_previz" if args.previz else "painted_master")
    out.mkdir(parents=True, exist_ok=True)
    sp = ShotPlans(rec, scene)
    sp.number_pins()
    master = sp.master_png(out)
    pp = Panels(rec, scene)
    painted = [s for s in rec.shots if s.type not in ("black", "title") and sp.w.cam(s) is not None]
    views = bool(scene["place"].get("views")) and scene["id"] == "canal"
    panels = []
    for i, s in enumerate(painted, 1):
        words = sp.prompt(s, views)
        base = pp.panel(i, s)  # its people, hands and props (a hand names only a prop the story has shown)
        camera = para(words, "THIS SHOT").replace("THIS SHOT is from camera", "Seen from camera", 1)
        layout = para(words, "Frame layout from the floor plan")
        camera = f"{camera} {layout}" if layout else camera
        picture = " ".join(x for x in (para(words, "In this frame").replace(
            "In this frame, at the shot's first instant: ", "", 1), para(words, "The moment: "),
            para(words, "Fill the frame")) if x)
        panels.append(kit.Panel(shot=i, zone="", camera=camera,
                                background="the place on the floor plan as this camera sees it",
                                picture=picture, people=base.people, props=base.props))
    writer = kit.Writer(world=(f"{scene['place']['look']} Time of day: {scene['time_of_day']}. Light: "
                               f"{rec.light.style}"), geography=pp.geography(), panels=panels)
    refs = views_ref(scene) if (args.yes and views) else []
    labels = [r.label for r in refs] or ([f"the location sheet for {scene['place']['name']}: six views of the one "
                                          "place"] if views else [])
    labels = [PREVIZ, *labels] if args.previz else [*labels, MASTER]
    prompt = kit.board_prompt(writer, list(range(1, len(painted) + 1)), labels, pp.colours,
                              props=[pp.n(p) for p in sorted(pp.w.props)])
    if args.previz:
        prompt += "\n\n" + PREVIZ_GUIDE
        if views:
            prompt += ("\n\nTake from image 2 only how the place looks: the canal, the sluice gate, the path and the "
                       "paddy, their materials and colours; never its viewpoints.")
    else:
        if views:
            prompt += ("\n\nTake from image 1 how the place looks: the canal, the sluice gate, the path and the "
                       "paddy, their materials; never its viewpoints (its views are taken from other spots). Take from "
                       "the floor plan where everything is and where each panel's camera stands.")
        prompt += "\n\n" + BOARD_GUIDE.format(n=labels.index(MASTER) + 1)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"{len(painted)} panels, prompt {len(prompt)} chars -> {out / 'prompt.txt'}")
    blocked = safe_depiction.blocking(prompt)
    if blocked:
        print(f"NOT SENT: safe depiction blocks {blocked}")
        return 2
    if not args.yes:
        print("nothing sent (add --yes)")
        return 0
    # measured: every board so far returned 1,372 output tokens (1536x1024, medium); pictures in at most ~2,100
    worst = (len(prompt) / 3.5 * PRICE["text_in"] + 4000 * PRICE["image_in"] + 1500 * PRICE["out"]) / 1e6
    if spent() + worst > BUDGET_USD:
        print(f"NOT SENT: ${spent():.3f} spent + ${worst:.3f} worst case > ${BUDGET_USD}")
        return 2
    from cinematic.run import client
    from hiru_ai.adapters.images import OpenAIImages
    from hiru_ai.core.ports import Reference
    from hiru_ai.systems.frame_render import pictures as pics
    if args.previz:
        grid = run / "previz" / "grid.png"
        refs = [Reference(label=PREVIZ, data=grid.read_bytes()), *refs]
    else:
        refs = [*refs, Reference(label=MASTER, data=master)]
    t = time.time()
    pic = OpenAIImages(client(), model=MODEL, quality=QUALITY)(prompt, kit.BOARD_ASPECT, refs, quality=QUALITY)
    img_in = getattr(pic, "image_input_tokens", 0) or 0
    usd = ((pic.input_tokens - img_in) * PRICE["text_in"] + img_in * PRICE["image_in"]
           + pic.output_tokens * PRICE["out"]) / 1e6
    rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    rows.append({"run": args.run, "usd": round(usd, 4), "s": round(time.time() - t)})
    LEDGER.write_text(json.dumps(rows, indent=1))
    (out / "board.png").write_bytes(pic.data)
    print(f"painted: ${usd:.4f} in {round(time.time() - t)} s; this budget ${spent():.3f} of ${BUDGET_USD}")
    from PIL import Image
    for s, box in zip(painted, pics.cell_boxes(pic.data, len(painted)), strict=False):
        Image.open(io.BytesIO(pics.crop(pic.data, [int(v) for v in box]))).convert("RGB").save(
            out / f"panel_{s.id}.jpg", quality=90)
    cards = "".join(
        f"<section><h2>Shot {escape(s.id)} · camera {escape(s.camera)} · {escape(s.size)}</h2><div class='row'>"
        f"<img src='panel_{escape(s.id)}.jpg'><p>{escape(p.camera)}<br><br>{escape(p.picture)}</p></div></section>"
        for s, p in zip(painted, panels, strict=True))
    (out / "compare.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Board from the master plan</title><style>body{font-family:"
        "system-ui;margin:16px;max-width:1250px}section{border:1px solid #ddd;border-radius:8px;padding:8px 12px;"
        "margin:0 0 12px}.row{display:flex;gap:14px;align-items:flex-start}img{width:480px}p{font-size:13px;"
        "max-width:700px}h2{font-size:15px}img.m{width:auto;max-width:100%;max-height:600px}</style>"
        f"<h1>Scene board painted from the master floor plan: {escape(scene['title'])}</h1>"
        "<p>Reference attached to the board: the master floor plan below (and the canal's views sheet).</p>"
        "<img class='m' src='master_plan.png'><p><a href='board.png'>the whole board</a></p>" + cards,
        encoding="utf-8")
    print(f"-> {out / 'compare.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
