"""The camera floor plan, simple: easy to read and to work with (the person's reference, 2026-11-28).

    .venv/Scripts/python.exe lab/scene_record/simple.py --run 005_canal_sol --scene canal

Only what a crew needs to read at a glance: the main areas as clean flat blocks with one big label each (field, path,
water, room), the main objects as plain boxes, people as dots in their colour (numbered in story order) with each
walk as one dashed line, and every camera set-up as a blue triangle labelled C1, C2 ... with one dashed arrow to
what it films. No wedges, lens text, legend, scale or axis lines. Positions are the plan's, to scale, so the picture
agrees with the cameras. Under it, one small table: camera, shots, lens, what it covers.

Writes runs/<run>/floorplan/simple.svg, simple.png and simple.html. Free.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from html import escape
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from checks import check  # noqa: E402
from geometry import P  # noqa: E402
from plan_view import Plan, area, short  # noqa: E402
from schema import SceneRecord  # noqa: E402
from sheet import HEX, compact, render_png  # noqa: E402

from contracts import board as kit  # noqa: E402

FRAME, INK = "#1c1f22", "#f2f2f2"
CAM, WALK = "#4aa3ff", "#eaa53d"


def tone(lm: Any) -> str:
    n = lm.name.lower()
    if lm.kind == "water" or any(w in n for w in ("water", "canal", "river", "pond", "lake", "sea")):
        return "#1e4a63"
    if any(w in n for w in ("paddy", "field", "grass", "garden", "rice", "lawn")):
        return "#3c5d3a"
    if any(w in n for w in ("concrete", "stone", "slab", "cement", "sluice")):
        return "#77797b"
    if any(w in n for w in ("shop", "room", "floor", "house", "hall", "kitchen", "office")):
        return "#3b342c"
    return "#8f7f63"  # earth, bank, road, yard


class Simple(Plan):
    def __init__(self, rec: SceneRecord, scene: dict[str, Any], width: float = 900, height: float = 640) -> None:
        focus = [P(m.x, m.y) for m in rec.marks] + [P(m.moves_to[0].x, m.moves_to[0].y) for m in rec.marks
                                                    if m.moves_to] + [P(c.x, c.y) for c in rec.cameras
                                                                      if any(s.camera == c.id for s in rec.shots)]
        super().__init__(rec, scene, check(rec, scene), focus=focus, pad=1.6)
        self.k = min(width / (self.x1 - self.x0), height / (self.y1 - self.y0))
        self.W, self.H = (self.x1 - self.x0) * self.k, (self.y1 - self.y0) * self.k
        words = kit.colours_for([p["name"] for p in scene["people"]])
        self.colour = {p["id"]: HEX[words[p["name"]]] for p in scene["people"]}
        self.obstacles: list[tuple[float, float, float, float]] = []
        self.order = self.positions()
        initials = {p["id"]: p["name"][:1].upper() for p in scene["people"]}
        self.pins = {(who, id(pos)): f"{initials.get(who, '?')}{i + 1}"
                     for who, seq in self.order.items() for i, pos in enumerate(seq)}

    def visible_centre(self, poly: list[P], above: list[list[P]] | None = None) -> P | None:
        """The centre of the part of an area that is on the drawing; None when too little of it shows."""
        hits = []
        n = 24
        for i in range(n):
            for j in range(n):
                q = P(self.x0 + (i + 0.5) * (self.x1 - self.x0) / n, self.y0 + (j + 0.5) * (self.y1 - self.y0) / n)
                inside = False
                for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
                    if (a.y > q.y) != (b.y > q.y) and q.x < (b.x - a.x) * (q.y - a.y) / (b.y - a.y) + a.x:
                        inside = not inside
                if inside and not any(self.contains(o, q) for o in above or []):
                    hits.append(q)
        if len(hits) < n * n * 0.04:
            return None
        xs, ys = [self.s(q)[0] for q in hits], [self.s(q)[1] for q in hits]
        cell_w, cell_h = self.W / n, self.H / n
        self.seen_w, self.seen_h = max(xs) - min(xs) + cell_w, max(ys) - min(ys) + cell_h
        return P(sum(q.x for q in hits) / len(hits), sum(q.y for q in hits) / len(hits))

    @staticmethod
    def contains(poly: list[P], q: P) -> bool:
        hit = False
        for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
            if (a.y > q.y) != (b.y > q.y) and q.x < (b.x - a.x) * (q.y - a.y) / (b.y - a.y) + a.x:
                hit = not hit
        return hit

    def big_label(self, p: P, text: str, colour: str = INK, size: int = 18) -> None:
        self.text(p, text.upper(), size, colour, "600", priority=1)

    def ground(self) -> str:
        out = [f"<rect width='{self.W:.0f}' height='{self.H:.0f}' fill='#2a2d26'/>"]
        polys = [(lm, [P(q.x, q.y) for q in lm.points]) for lm in self.rec.landmarks
                 if lm.kind in ("water", "area") and len(lm.points) >= 3]
        polys = [x for x in polys if area(x[1]) > 1.0]
        polys = sorted(polys, key=lambda x: -area(x[1]))
        for k, (lm, pts) in enumerate(polys):
            out.append(f"<polygon points='{self.poly(pts)}' fill='{tone(lm)}' stroke='{FRAME}' stroke-width='6' "
                       "stroke-linejoin='round'/>")
            seen = self.visible_centre(pts, [q for _, q in polys[k + 1:]])  # drawn later = on top of it
            if seen is not None:
                name = short(lm.name).upper()
                wide = len(name) * 18 * 0.62
                if self.seen_w < wide and self.seen_h > wide:  # a tall narrow strip: the label runs up it
                    x, y = self.s(seen)
                    out.append(f"<text x='{x:.1f}' y='{y:.1f}' font-size='16' font-weight='600' fill='{INK}' "
                               f"text-anchor='middle' transform='rotate(-90 {x:.1f} {y:.1f})' dy='5'>"
                               f"{escape(name)}</text>")
                    self.obstacles.append((x - 10, y - wide / 2, x + 10, y + wide / 2))
                else:
                    self.big_label(seen, short(lm.name))
        for lm in self.rec.landmarks:
            if lm.kind == "path" and len(lm.points) > 1:
                pts = [P(q.x, q.y) for q in lm.points]
                wpx = max((lm.width or 1.2) * self.k, 26)
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='#a89676' stroke-width='{wpx:.0f}' "
                           "stroke-linecap='round' stroke-linejoin='round'/>")
                # the label runs along the path's longest stretch, a quarter of the way in (clear of the pins)
                a, b = max(pairwise(pts), key=lambda s: (s[1] - s[0]).length())
                (ax, ay), (bx, by) = self.s(a), self.s(b)
                ang = math.degrees(math.atan2(by - ay, bx - ax))
                if ang > 90:
                    ang -= 180
                elif ang < -90:
                    ang += 180
                d = math.hypot(bx - ax, by - ay) or 1.0
                off = min(max((lm.width or 1.2) * self.k / 2 - 12, 10), 22)  # beside the walk, inside the band
                lx = ax + (bx - ax) * 0.5 - (by - ay) / d * off
                ly = ay + (by - ay) * 0.5 + (bx - ax) / d * off
                out.append(f"<text x='{lx:.1f}' y='{ly:.1f}' font-size='13' font-weight='700' fill='#2b241a' "
                           f"text-anchor='middle' dy='4' transform='rotate({ang:.1f} {lx:.1f} {ly:.1f})'>"
                           f"{escape(short(lm.name).upper())}</text>")
                self.obstacles.append((lx - 14, ly - 50, lx + 14, ly + 50) if abs(ang) > 45 else
                                      (lx - 50, ly - 10, lx + 50, ly + 10))
            elif lm.kind == "wall" and len(lm.points) > 1:
                pts = [P(q.x, q.y) for q in lm.points]
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='#d9d4cc' stroke-width='6' "
                           "stroke-linecap='round'/>")
        for lm in self.rec.landmarks:
            if lm.kind in ("fixed", "furniture", "door") and len(lm.points) == 1:
                c = P(lm.points[0].x, lm.points[0].y)
                w = max((lm.width or 1.0) * self.k, 22)
                h = w * (0.6 if lm.kind == "furniture" else 0.45)
                x, y = self.s(c)
                fill = "#7d5a3c" if lm.kind == "furniture" else "#6f7173"
                out.append(f"<rect x='{x - w / 2:.1f}' y='{y - h / 2:.1f}' width='{w:.1f}' height='{h:.1f}' rx='3' "
                           f"fill='{fill}' stroke='white' stroke-width='2'/>")
                self.obstacles.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
                self.text(c, short(lm.name).upper(), 11, "#e6e6e6", "600", dy=-h / 2 - 7, priority=2)
        return "".join(out)

    def people_layer(self) -> str:
        out = []
        for who, seq in self.order.items():
            col = self.colour.get(who, "#ccc")
            for pos in seq:
                m = pos["mark"]
                if m is not None and m.moves_to:
                    a, b = self.s(pos["at"]), self.s(P(m.moves_to[0].x, m.moves_to[0].y))
                    out.append(f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' "
                               f"stroke='{WALK}' stroke-width='4' stroke-dasharray='10 7'/>")
            spots: list[tuple[P, list[str]]] = []
            for pos in seq:
                spot = next((sp for sp in spots if (sp[0] - pos["at"]).length() < 0.3), None)
                label = self.pins[(who, id(pos))]
                if spot is None:
                    spots.append((pos["at"], [label]))
                else:
                    spot[1].append(label)
            for at, labels in spots:
                x, y = self.s(at)
                tag = compact(labels)
                r = max(12, 4 + 3.2 * len(tag))
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{col}' stroke='white' "
                           f"stroke-width='2'/><text x='{x:.1f}' y='{y + 3.5:.1f}' font-size='10' font-weight='700' "
                           f"fill='white' text-anchor='middle'>{escape(tag)}</text>")
                self.obstacles.append((x - r, y - r, x + r, y + r))
        return "".join(out)

    def camera_layer(self) -> str:
        out, arrows = [], []
        for ids in self.w.setups(cluster_m=0.15):
            shots = [s for s in self.rec.shots if s.camera in ids]
            if not shots:
                continue
            c = self.w.cams[ids[0]]
            here = P(c.x, c.y)
            targets: list[P] = []
            for s in shots:
                cam = self.w.cam(s)
                t = self.w.point_of(cam.looks_at, s.start, s.beat) if cam else None
                if t is not None and all((t - q).length() > 0.6 for q in targets):
                    targets.append(t)
            x, y = self.s(here)
            for t in targets[:2]:  # at most two arrows: the clean look; the table lists every shot
                v = t - here
                if v.length() < 0.3:
                    continue
                tx, ty = self.s(t)
                d = math.hypot(tx - x, ty - y)
                ex, ey = x + (tx - x) * (d - 16) / d, y + (ty - y) * (d - 16) / d
                arrows.append(f"<line x1='{x:.1f}' y1='{y:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='{CAM}' "
                              "stroke-width='2.5' stroke-dasharray='7 6' marker-end='url(#cam)'/>")
            u = (targets[0] - here) if targets else P(0, 1)
            ang = math.atan2(-u.y, u.x)
            tri = [(x + 16 * math.cos(ang), y + 16 * math.sin(ang)),
                   (x + 14 * math.cos(ang + 2.25), y + 14 * math.sin(ang + 2.25)),
                   (x + 14 * math.cos(ang - 2.25), y + 14 * math.sin(ang - 2.25))]
            out.append("<polygon points='" + " ".join(f"{a:.1f},{b:.1f}" for a, b in tri) +
                       f"' fill='{CAM}' stroke='white' stroke-width='2.5' stroke-linejoin='round'/>")
            self.obstacles.append((x - 17, y - 17, x + 17, y + 17))
            self.text(here, "/".join(ids), 14, INK, "700", dy=-22, priority=3)
        return "".join(arrows) + "".join(out)

    def drawing(self) -> str:
        self.labels = []
        body = self.ground() + self.people_layer() + self.camera_layer()
        names = " ".join(
            f"<circle cx='{18 + i * 110}' cy='{self.H - 16:.0f}' r='7' fill='{self.colour[p['id']]}'/><text "
            f"x='{30 + i * 110}' y='{self.H - 12:.0f}' font-size='12' fill='{INK}'>{escape(p['name'])}</text>"
            for i, p in enumerate(self.scene["people"]))
        self.obstacles.append((0, self.H - 30, 30 + 110 * len(self.scene["people"]), self.H))
        return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {self.W:.0f} {self.H:.0f}' "
                f"width='{self.W:.0f}' height='{self.H:.0f}' font-family='system-ui, sans-serif'><defs><marker "
                "id='cam' markerUnits='userSpaceOnUse' markerWidth='12' markerHeight='12' refX='10' refY='6' "
                f"orient='auto'><path d='M0,0 L12,6 L0,12 z' fill='{CAM}'/></marker></defs>{body}"
                f"<rect x='0' y='{self.H - 30:.0f}' width='{30 + 110 * len(self.scene['people'])}' height='30' "
                f"fill='{FRAME}' opacity='0.8'/>{names}{self.resolve()}</svg>")

    def table(self) -> str:
        rows = []
        for c in self.rec.cameras:
            shots = [s for s in self.rec.shots if s.camera == c.id]
            if not shots:
                continue
            lenses = sorted({s.lens_mm or c.lens_mm for s in shots})
            lens = f"{lenses[0]} mm" if len(lenses) == 1 else f"{lenses[0]}–{lenses[-1]} mm"
            rows.append(f"<tr><td><b>{escape(c.id)}</b></td><td>{escape(c.role)}</td><td>"
                        f"{escape(', '.join(f'{s.id} {s.size}' for s in shots))}</td><td>{lens}</td><td>"
                        f"{escape(c.covers or shots[0].purpose)}</td></tr>")
        return ("<table><tr><th>Camera</th><th>Role</th><th>Shots</th><th>Lens</th><th>Coverage</th></tr>"
                + "".join(rows) + "</table>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    out = run / "floorplan"
    out.mkdir(parents=True, exist_ok=True)
    sp = Simple(rec, scene)
    svg = sp.drawing()
    (out / "simple.svg").write_text(svg, encoding="utf-8")
    render_png(svg, out / "simple.png", sp.W, sp.H)
    (out / "simple.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Camera floor plan</title><style>body{background:#111;color:#eee;"
        "font-family:system-ui;margin:20px;max-width:960px}.card{border:1px solid #333;border-radius:14px;padding:"
        "14px;background:#000}h1{font-size:16px;letter-spacing:.04em}p{color:#aaa;font-size:12px}table{width:100%;"
        "border-collapse:collapse;font-size:13px;margin-top:14px}td,th{text-align:left;padding:7px 8px;border-bottom:"
        "1px solid #2a2a2a}th{color:#bbb}</style>"
        f"<div class='card'><h1>CAMERA FLOOR PLAN</h1><p>{escape(scene.get('heading', ''))} · top-down view · camera "
        f"locations and viewing directions</p><div style='border-radius:12px;overflow:hidden;display:inline-block'>"
        f"{svg}</div>{sp.table()}</div>", encoding="utf-8")
    print(f"-> {out / 'simple.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
