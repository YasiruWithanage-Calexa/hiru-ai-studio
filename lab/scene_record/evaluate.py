"""One page per scene: each painted panel next to what the camera plan says that shot should show, with a verdict.

    .venv/Scripts/python.exe lab/scene_record/evaluate.py --run 005_canal_sol --scene canal

For every painted shot, left to right: the PAINTED panel (runs/<run>/painted_plan/panel_<shot>.jpg), the PLAN's view
of that shot drawn by code (the camera's position, lens and height; who is where, facing which way), and the FLOOR
PLAN with that shot's camera. Under them, the plan in words (setup, size, who is on which side, the eyeline) and the
verdict a person (here: Claude, by eye, 2026-11-28) gave on each point: place, people's sides, size, eyeline, props.
Free: nothing is sent.
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src" / "libs")]

from board import frame_svg, plan_svg  # noqa: E402
from checks import check  # noqa: E402
from geometry import World  # noqa: E402
from schema import SceneRecord  # noqa: E402

OK, PART, NO = "✅", "🟡", "❌"
# verdicts by eye on the painted boards of plans 005 (painted with the text-free floor plan attached)
VERDICTS: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "canal": {
        "1": [("Place", OK, "gate left of the path, canal and paddy as planned"),
              ("Sides", PART, "Aruni frame right on the path (as planned); Nimal at the bottom centre, close to "
                              "the camera, where the plan has him at frame left by the gate"),
              ("Size", OK, "wide")],
        "2": [("Place", OK, "gate behind her at left, path behind at right"), ("Sides", OK, "Aruni centre"),
              ("Size", NO, "planned medium shot, painted full figure"),
              ("Eyeline", NO, "planned: looks frame left at Nimal; painted: looks into the lens")],
        "3": [("Place", OK, "bank and canal edge"), ("Sides", OK, "Nimal centre, lying"), ("Size", OK, "full shot"),
              ("Props", OK, "no key in his hands yet (the reveal is shot 6)")],
        "4": [("Place", OK, "same gate and path as shot 2 (same setup C2)"),
              ("Sides", OK, "Aruni centre-right standing, Nimal lying lower left"), ("Size", OK, "full shot"),
              ("Eyeline", NO, "planned: looks left at Nimal; painted: into the lens")],
        "5": [("Place", PART, "path and paddy, but no gate: shot 2 and 4 from the SAME setup showed the gate"),
              ("Sides", OK, "Aruni centre, bag set down"), ("Size", NO, "planned MCU, painted full kneeling figure"),
              ("Eyeline", OK, "head down to her left, toward him")],
        "6": [("Sides", OK, "his hand, her finger, the key centre"),
              ("Props", PART, "key in an open palm; the script says inside his fist")],
        "7": [("Place", PART, "no gate again (same setup C2)"), ("Size", NO, "planned close-up, painted full kneel"),
              ("Eyeline", OK, "looking down at the key")],
        "8": [("Props", OK, "phone in her right hand, white clay"), ("Size", OK, "insert")],
        "9": [("Place", PART, "no gate (same setup C2)"), ("Size", PART, "planned MCU, painted medium-wide"),
              ("Props", OK, "phone in her hand, she looks at it")],
        "10": [("Camera", NO, "painted from BEHIND her (over the shoulder); planned from setup C2 in front of her"),
               ("Props", NO, "phone held low; planned at her ear (the plan's prop state also lagged)"),
               ("Sides", NO, "Nimal far down the path; he lies beside her")],
        "11": [("Place", OK, "the sluice gate, rain on water"), ("People", OK, "nobody in it, as planned")],
    },
    "deed": {
        "1": [("Place", OK, "window left, lamp, table, cups"), ("Sides", OK, "Nimal (red) left, Saman (blue) right"),
              ("Size", OK, "wide")],
        "2": [("Place", OK, "lamp and shelves behind"), ("Size", OK, "medium close-up"),
              ("Eyeline", NO, "planned: looks frame left at Nimal; painted: into the lens")],
        "3": [("Place", OK, "window, shelves, lamp"), ("Size", OK, "medium close-up"),
              ("Props", NO, "the deed is in Nimal's hands; he only NOTICES it here (he takes it in shot 5)")],
        "4": [("Props", OK, "the folded deed in Saman's pocket"), ("Size", OK, "insert")],
        "5": [("Sides", OK, "Nimal left reaching across, Saman right"), ("Size", OK, "medium two-shot"),
              ("Action", OK, "the grab, the deed coming out of the pocket")],
        "6": [("Action", NO, "planned: the deed struck on the TABLE; painted: the hand at the pocket again "
                             "(the plan's prop state still said 'at the pocket')")],
        "7": [("Size", OK, "close-up"), ("Eyeline", NO, "planned: looks frame right at Saman; painted: into the lens")],
        "8": [("Size", OK, "close-up"), ("Eyeline", NO, "planned: looks frame left at Nimal; painted: into the lens")],
        "9": [("Sides", OK, "Nimal standing left, Saman seated right"), ("Props", OK, "the deed on the table"),
              ("Size", OK, "full shot")],
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    rep = check(rec, scene)
    w = World(rec)
    names = {p["id"]: p["name"] for p in scene["people"]} | {p["id"]: p["name"] for p in scene["props"]}
    colour = {p["id"]: c for p, c in zip(scene["people"], ("#d0453a", "#2f6fc0", "#2f9e5b"), strict=False)}
    verdicts = VERDICTS.get(args.scene, {})
    tally = {OK: 0, PART: 0, NO: 0}
    rows = []
    for s in rec.shots:
        if s.type in ("black", "title") or w.cam(s) is None:
            continue
        cam = w.cam(s)
        f = rep.facts.get(s.id, {})
        sides = ", ".join(f"{names.get(k, k)} {v}" for k, v in (f.get("sides") or {}).items())
        plan_words = (f"<b>Setup {escape(s.camera)}</b> ({escape(w.cams[s.camera].role)}) · {escape(s.size)} "
                      f"{escape(s.type)} · {cam.lens_mm} mm · {escape(sides)}"
                      + (f" · {escape(f['eyeline'])}" if f.get("eyeline") else ""))
        marks = "".join(f"<tr><td>{escape(k)}</td><td class='v'>{v}</td><td>{escape(t)}</td></tr>"
                        for k, v, t in verdicts.get(s.id, []))
        for _, v, _ in verdicts.get(s.id, []):
            tally[v] += 1
        img = f"painted_plan/panel_{s.id}.jpg"
        rows.append(f"<section><h2>Shot {escape(s.id)} — {escape(s.purpose)}</h2><div class='row'>"
                    f"<figure><img src='{img}'><figcaption>PAINTED</figcaption></figure>"
                    f"<figure>{frame_svg(w, s, w.cuts[s.start], colour, names)}<figcaption>THE PLAN: what camera "
                    f"{escape(s.camera)} should see</figcaption></figure>"
                    f"<figure>{plan_svg(w, s, w.cuts[s.start], colour)}<figcaption>where camera {escape(s.camera)} "
                    "stands</figcaption></figure></div>"
                    f"<p class='plan'>{plan_words}</p><table>{marks}</table></section>")
    head = (f"<p class='score'>{tally[OK]} {OK} matches · {tally[PART]} {PART} partly · {tally[NO]} {NO} wrong</p>")
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Board vs plan: {escape(scene['title'])}</title>
<style>body{{font-family:system-ui,sans-serif;margin:16px;background:#fafafa;color:#222;max-width:1250px}}
section{{background:white;border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin:0 0 14px}}
h1{{font-size:20px}} h2{{font-size:15px;margin:2px 0 8px}} .row{{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}}
figure{{margin:0}} figcaption{{font-size:11px;color:#666;font-weight:600}} img{{width:384px;height:216px;object-fit:cover;
border:1px solid #222}} .plan{{font-size:13px;color:#333}} table{{font-size:13px;border-collapse:collapse}}
td{{padding:3px 10px 3px 0;vertical-align:top}} td.v{{width:26px}} .score{{font-size:16px;font-weight:600}}</style></head>
<body><h1>Painted board vs the camera plan: {escape(scene['title'])}</h1>
<p>For each shot: what was PAINTED, what THE PLAN says that camera should see (drawn by code from the floor plan),
and where that camera stands. The table says, point by point, whether the painting matches the plan.</p>{head}
{''.join(rows)}</body></html>"""
    (run / "evaluate.html").write_text(page, encoding="utf-8")
    print(f"{tally[OK]} match, {tally[PART]} partly, {tally[NO]} wrong -> {run / 'evaluate.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
