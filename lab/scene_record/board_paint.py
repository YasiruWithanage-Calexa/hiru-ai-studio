"""Paint the scene board of a scene record with the PRODUCT's board prompt (mannequins, white clay props, the grid).

    .venv/Scripts/python.exe lab/scene_record/board_paint.py --run 003_canal_sol --scene canal          free: prompt only
    .venv/Scripts/python.exe lab/scene_record/board_paint.py --run 003_canal_sol --scene canal --yes    PAID: one picture

No board-writer model: every panel is written by CODE from the record, the same facts the code-drawn board shows
(camera, lens, height and distance; who is at which side of the frame, how they face, their posture and hands; the
props and where they rest; what of the place is behind them), and handed to `contracts.board.board_prompt`, the
product's own prompt (mannequin line, prop line, world, geography, bodies, support, no text). The painted board shows
what the plan says, painted the way the product paints. The canal attaches its real location views sheet (read from
storage, GET only); the deed has no sheets and is painted from words. Quality medium (the person's image rule: boards
low or medium, never high). Writes runs/<run>/painted/: prompt.txt, board.png, panel_<shot>.png, painted.html (each
painted panel beside the code-drawn opening frame), spend.json. Nothing in src/ or the database changes.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from html import escape
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab"), str(ROOT / "scripts")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from board import frame_svg  # noqa: E402
from chain import POSTURE  # noqa: E402
from checks import check  # noqa: E402
from geometry import P, World  # noqa: E402
from schema import SceneRecord, Shot  # noqa: E402

from contracts import board as kit  # noqa: E402
from contracts import safe_depiction  # noqa: E402

MODEL, QUALITY, CAP_USD = "gpt-image-2", "medium", 0.50
PRICE = {"text_in": 5.00, "image_in": 8.00, "out": 30.00}  # $ per million tokens (contracts/costs.py SEED_PRICES)
SIZE = {"EWS": "extreme wide shot", "WS": "wide shot", "FS": "full shot", "MLS": "medium long shot",
        "MS": "medium shot", "MCU": "medium close-up", "CU": "close-up", "ECU": "extreme close-up",
        "INSERT": "insert close on a detail"}
LEDGER = HERE / "runs" / "paint_ledger.json"


def spent() -> float:
    return sum(r["usd"] for r in json.loads(LEDGER.read_text())) if LEDGER.exists() else 0.0


def compass(v: P) -> str:
    ang = math.degrees(math.atan2(v.y, v.x)) % 360
    return ("east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east")[
        int((ang + 22.5) // 45) % 8]


class Panels:
    def __init__(self, rec: SceneRecord, scene: dict[str, Any]) -> None:
        self.rec, self.scene, self.w = rec, scene, World(rec)
        self.name = {p["id"]: p["name"] for p in scene["people"]} | {p["id"]: p["name"] for p in scene["props"]}
        self.name |= {lm.id: lm.name for lm in rec.landmarks}
        people = [p["id"] for p in scene["people"]]
        self.colours = kit.colours_for([self.name[p] for p in people])
        self.colour_of = {p: self.colours[self.name[p]] for p in people}

    def n(self, ref: str) -> str:
        """A name as it reads in a sentence: a person's name as written, a thing's in lower case."""
        name = self.name.get(ref, ref)
        return name if ref in self.colour_of else name[:1].lower() + name[1:]

    def the(self, ref: str) -> str:
        return self.n(ref) if ref in self.colour_of else f"the {self.n(ref)}"

    def centre(self) -> P:
        pts = [P(p.x, p.y) for lm in self.rec.landmarks if lm.kind != "light" for p in lm.points]
        return P(sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts)) if pts else P(0, 0)

    def geography(self) -> str:
        """The floor plan in words: where each fixed thing is and where each person is, beat by beat."""
        c = self.centre()
        out = []
        for lm in self.rec.landmarks:
            if lm.kind == "light":
                out.append(f"The light comes from the {self.n(lm.id)}, to the {compass(P(lm.points[0].x, lm.points[0].y) - c)}.")
            elif len(lm.points) > 1 and lm.kind != "area":
                a, b = lm.points[0], lm.points[-1]
                out.append(f"The {self.n(lm.id)} runs from the {compass(P(a.x, a.y) - c)} to the {compass(P(b.x, b.y) - c)}.")
            elif lm.kind != "area":
                out.append(f"The {self.n(lm.id)} stands to the {compass(P(lm.points[0].x, lm.points[0].y) - c)} of the scene.")
        fixed = [lm for lm in self.rec.landmarks if lm.kind in ("fixed", "furniture", "door") and lm.points]
        for m in self.rec.marks:
            at = P(m.x, m.y)
            near = min(fixed, key=lambda lm: (P(lm.points[0].x, lm.points[0].y) - at).length(), default=None)
            rel = ""
            if near is not None:
                d = at - P(near.points[0].x, near.points[0].y)
                rel = f", {d.length():.0f} m {compass(d)} of the {self.n(near.id)}" if d.length() >= 0.5 else \
                    f", right by the {self.n(near.id)}"
            walk = ""
            if m.moves_to:
                to = P(m.moves_to[0].x, m.moves_to[0].y)
                walk = f", and walks {compass(to - at)} {((to - at).length()):.0f} m" + \
                    (f" along the {self.n(m.along)}" if m.along else "")
            out.append(f"Beat {m.beat}: {self.n(m.who)} is {POSTURE.get(m.posture, m.posture)}{rel}{walk}.")
        seen, uniq = set(), []
        for s in out:  # a person who keeps the same mark every beat is said once
            key = s.split(": ", 1)[-1]
            if key not in seen:
                seen.add(key)
                uniq.append(s)
        return " ".join(uniq) + " Every camera stays on the same side of the action, so each person keeps their side " \
                                "of the frame from panel to panel."

    def panel(self, number: int, s: Shot) -> kit.Panel:
        w, cam = self.w, self.w.cam(s)
        assert cam is not None
        k = w.cuts[s.start]
        target = w.point_of(cam.looks_at, s.start, s.beat)
        dist = (target - P(cam.x, cam.y)).length() if target else 0.0
        move = "" if s.move == "static" else f", {s.move.replace('_', ' ')} ({s.move_why})"
        camera = (f"{SIZE[s.size]}, {cam.lens_mm} mm lens, the camera at {cam.height.replace('_', ' ')} height, "
                  f"{s.angle} angle, {dist:.1f} m from {self.the(cam.looks_at)}{move}")
        # what of the place is in view, by side
        bits = []
        for lm in self.rec.landmarks:
            if lm.kind in ("light", "area"):
                continue
            pts = [P(p.x, p.y) for p in lm.points]
            inside = [p for p in pts if w.in_view(cam, s, p, margin=4)]
            if len(pts) > 1:
                if inside or any(w.in_view(cam, s, a + (b - a).scale(t / 10), margin=4)
                                 for a, b in pairwise(pts) for t in range(11)):
                    bits.append(f"the {self.n(lm.id)} crossing the frame")
            elif inside:
                bits.append(f"the {self.n(lm.id)} at frame {w.side(cam, s, inside[0])}")
        background = ", ".join(bits) or (
            "the place behind them as the location sheet shows it" if self.scene["place"].get("views")
            else f"the {self.scene['place']['name'].lower()} behind them")
        # the people at the shot's opening instant
        lines, people, props = [], [], []
        for p in k.people:
            if p.who not in s.in_frame:
                continue
            m = w.marks.get(p.mark)
            if m is None:
                continue
            at = w.mark_point(m, p.progress)
            side = w.side(cam, s, at)
            face = w.screen_facing(cam, s, at, w.facing_vector(p.look_at or m.facing, at, k.id, s.beat))
            d = (at - P(cam.x, cam.y)).length()
            colour = self.colour_of.get(p.who, "grey")
            lines.append(f"The {colour} mannequin ({self.n(p.who)}) is {POSTURE.get(p.posture, p.posture)}, at frame "
                         f"{side}, {d:.1f} m from the camera" + (f", its head facing {face}" if face else "")
                         + (f", looking at {self.the(p.look_at)}" if p.look_at else "") + ".")

            def shown(prop: str) -> str:  # a hand names a prop only once the story has shown it
                st = w.prop_state(prop, k.id) if prop else None
                return self.n(prop) if prop and (st is None or st.seen) else ""
            people.append(kit.PanelPerson(name=self.n(p.who), state=POSTURE.get(p.posture, p.posture),
                                          left_hand=shown(p.left_hand), right_hand=shown(p.right_hand)))
        for prop in sorted(w.props):
            st = w.prop_state(prop, k.id)
            if st is None or not st.seen or prop not in s.in_frame:
                continue
            pt = w.point_of(prop, k.id, s.beat)
            props.append(kit.PanelProp(name=self.n(prop), held_by=self.n(st.holder) if st.holder else "",
                                       hand=st.hand if st.hand in ("left", "right") else "",
                                       rests_on=self.n(st.on) if st.on else "",
                                       frame_side=w.side(cam, s, pt) if pt else ""))
            lines.append(f"The {self.n(prop)}: {st.place.rstrip('.')}.")
        if k.under_way and any(p.who in s.in_frame for p in k.people):
            lines.append(f"The instant painted: {k.under_way.rstrip('.')}.")
        if not people:
            lines.append("Nobody is in this panel: no mannequin and no person anywhere in the frame.")
        if s.type == "insert" or s.subject in w.props:
            lines.append(f"Fill the frame with the {self.n(s.subject)}; only the parts of a mannequin next to it "
                         "show.")
        return kit.Panel(shot=number, zone="", camera=camera, background=background, picture=" ".join(lines),
                         people=people, props=props)


HEX = {"red": "#d0453a", "blue": "#2f6fc0", "yellow": "#e8c547", "green": "#2f9e5b", "purple": "#8e44ad",
       "orange": "#e67e22"}
PLAN_LABEL = "the floor plan of this scene seen from above, north up"
PLAN_JOB = ("Image {n} is the floor plan of this scene seen from above, north up, drawn without words: blue is water, "
            "brown is earth or a path, green is field, grey is concrete or stone; each coloured dot is where the "
            "mannequin of that colour is, a dashed line with an arrowhead is a walk, and each white triangle is a "
            "camera position pointing the way it looks. Take from it where everyone and everything stands relative "
            "to each other and to the place, and paint every panel to agree with it from that panel's own camera. "
            "Never draw the plan, its dots, lines, arrows or triangles in a panel.")


def plan_png(rec: SceneRecord, scene: dict[str, Any], colour_of: dict[str, str], out: Path) -> bytes:
    """The floor plan with no text, painted to a PNG by the local headless Chrome (free, offline)."""
    import subprocess

    from checks import check as _check
    from plan_view import Plan
    pl = Plan(rec, scene, _check(rec, scene), pad=1.5)
    body = [pl.place(), pl.cameras()]
    for who, seq in pl.positions().items():
        col = HEX.get(colour_of.get(who, ""), "#cccccc")
        for pos in seq:
            m = pos["mark"]
            if m is not None and m.moves_to:
                a, b = pl.s(pos["at"]), pl.s(P(m.moves_to[0].x, m.moves_to[0].y))
                body.append(f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' stroke='{col}' "
                            "stroke-width='4' stroke-dasharray='10 7' marker-end='url(#arrow)'/>")
            x, y = pl.s(pos["at"])
            body.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='11' fill='{col}' stroke='white' stroke-width='3'/>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{pl.W:.0f}' height='{pl.H:.0f}' "
           f"viewBox='0 0 {pl.W:.0f} {pl.H:.0f}'><defs><marker id='arrow' markerWidth='10' markerHeight='10' "
           "refX='7' refY='5' orient='auto'><path d='M0,0 L10,5 L0,10 z' fill='#e2a93a'/></marker>"
           "<marker id='camarrow' markerWidth='10' markerHeight='10' refX='7' refY='5' orient='auto'>"
           "<path d='M0,0 L10,5 L0,10 z' fill='#5aa7f0'/></marker></defs>" + "".join(body) + "</svg>")
    page = out / "floorplan_ref.html"
    page.write_text(f"<!doctype html><body style='margin:0;background:#15171a'>{svg}</body>", encoding="utf-8")
    png = out / "floorplan_ref.png"
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",  # noqa: S603
                    f"--window-size={int(pl.W)},{int(pl.H)}", f"--screenshot={png}", page.as_uri()],
                   check=True, capture_output=True, timeout=60)
    return png.read_bytes()


def views_ref(scene: dict[str, Any]) -> list[Any]:
    """The canal's location views sheet from storage (GET only), or nothing."""
    if scene["id"] != "canal":
        return []
    from _common import Rest, load_env

    from hiru_ai.core.ports import Reference
    load_env()
    r = Rest()
    loc = r.get("canon_entities", code=f"eq.{scene['place']['id']}", select="current_version_id,production_id",
                production_id="eq.836ceaf5-7280-4906-b7b7-fb66c07cb8bf")[0]
    v = r.get("canon_versions", id=f"eq.{loc['current_version_id']}", select="reference_assets")[0]
    asset = next(a for a in v["reference_assets"] or [] if a.get("views"))
    data = r.download("references", asset["path"])
    return [Reference(label=f"the location sheet for {scene['place']['name']}: six views of the one place", data=data)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--yes", action="store_true", help="PAID: paint the board (one picture)")
    ap.add_argument("--plan", action="store_true", help="attach the floor plan (no text) as a picture")
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    out = run / ("painted_plan" if args.plan else "painted")
    out.mkdir(parents=True, exist_ok=True)
    pp = Panels(rec, scene)
    painted = [s for s in rec.shots if s.type not in ("black", "title") and pp.w.cam(s) is not None]
    writer = kit.Writer(world="", geography=pp.geography(),
                        panels=[pp.panel(i, s) for i, s in enumerate(painted, 1)])
    world = (f"{scene['place']['look']} Time of day: {scene['time_of_day']}. Light: {rec.light.style}")
    writer.world = world
    refs = views_ref(scene) if args.yes else []
    labels = [r.label for r in refs] or ([f"the location sheet for {scene['place']['name']}: six views of the one "
                                          "place"] if scene["id"] == "canal" else [])
    if args.plan:
        from hiru_ai.core.ports import Reference
        data = plan_png(rec, scene, pp.colour_of, out)
        refs.append(Reference(label=PLAN_LABEL, data=data))
        labels = [*labels, PLAN_LABEL] if not args.yes else [r.label for r in refs]
    prompt = kit.board_prompt(writer, list(range(1, len(painted) + 1)), labels, pp.colours,
                              props=[pp.n(p) for p in sorted(pp.w.props)])
    if labels and labels[0].startswith("the location sheet"):
        prompt += ("\n\nTake from image 1 the place itself: the canal, the sluice gate, the path and the paddy, their "
                   "materials and how they sit together. Where things are in each panel comes from that panel's "
                   "words.")
    if args.plan:
        prompt += "\n\n" + PLAN_JOB.format(n=labels.index(PLAN_LABEL) + 1)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"{len(painted)} panels, prompt {len(prompt)} chars -> {out / 'prompt.txt'}")
    blocked = safe_depiction.blocking(prompt)
    if blocked:
        print(f"NOT SENT: safe depiction blocks {blocked}")
        return 2
    if not args.yes:
        print("nothing sent (add --yes to paint)")
        return 0
    worst = (len(prompt) / 3.5 * PRICE["text_in"] + 3000 * PRICE["image_in"] + 4000 * PRICE["out"]) / 1e6
    if spent() + worst > CAP_USD:
        print(f"NOT SENT: ${spent():.3f} spent + ${worst:.3f} worst case > ${CAP_USD}")
        return 2
    from cinematic.run import client
    from hiru_ai.adapters.images import OpenAIImages
    from hiru_ai.systems.frame_render import pictures as pics
    t = time.time()
    pic = OpenAIImages(client(), model=MODEL, quality=QUALITY)(prompt, kit.BOARD_ASPECT, refs, quality=QUALITY)
    img_in = getattr(pic, "image_input_tokens", 0) or 0
    usd = ((pic.input_tokens - img_in) * PRICE["text_in"] + img_in * PRICE["image_in"]
           + pic.output_tokens * PRICE["out"]) / 1e6
    rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    rows.append({"run": args.run, "usd": round(usd, 4), "in": pic.input_tokens, "image_in": img_in,
                 "out": pic.output_tokens, "s": round(time.time() - t)})
    LEDGER.write_text(json.dumps(rows, indent=1))
    (out / "board.png").write_bytes(pic.data)
    print(f"painted: ${usd:.4f} in {round(time.time() - t)} s; lab image spend ${spent():.3f} of ${CAP_USD}")
    from PIL import Image
    boxes = pics.cell_boxes(pic.data, len(painted))
    for s, box in zip(painted, boxes, strict=False):
        cell = Image.open(io.BytesIO(pics.crop(pic.data, [int(v) for v in box])))
        cell.convert("RGB").save(out / f"panel_{s.id}.jpg", quality=88)
    rep = check(rec, scene)
    colour = {p["id"]: c for p, c in zip(scene["people"], ("#d0453a", "#2f6fc0", "#2f9e5b"), strict=False)}
    cards = []
    for s in rec.shots:
        head = f"<h2>Shot {escape(s.id)} · {escape(s.size)} {escape(s.type)} · {s.duration_s} s</h2>"
        if s not in painted:
            cards.append(f"<section>{head}<p>{escape(s.action)}</p></section>")
            continue
        drawn = frame_svg(pp.w, s, pp.w.cuts[s.start], colour, pp.name)
        cards.append(f"<section>{head}<div class='row'><figure><img src='panel_{escape(s.id)}.jpg'><figcaption>painted"
                     f"</figcaption></figure><figure>{drawn}<figcaption>the plan (code-drawn, opening instant)"
                     f"</figcaption></figure></div><p>{escape(s.action)}</p><p class='f'>"
                     f"{escape(str(rep.facts.get(s.id, {}).get('sides', '')))}</p></section>")
    (out / "painted.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Painted board</title><style>body{font-family:system-ui;margin:16px}"
        "section{border:1px solid #ddd;border-radius:8px;padding:8px 12px;margin:0 0 12px}.row{display:flex;gap:10px;"
        "flex-wrap:wrap}img{width:384px;height:216px;object-fit:cover}figure{margin:0}figcaption{font-size:11px;"
        "color:#666}.f{font-size:12px;color:#555}h2{font-size:15px}</style>"
        f"<h1>Painted board: {escape(scene['title'])}</h1><p><a href='board.png'>the whole board</a></p>"
        + "".join(cards), encoding="utf-8")
    print(f"-> {out / 'painted.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
