"""The scene record as a floor plan and a blocking plan a crew can read (top view, north up), like a director's sheet.

Two drawings from the same plan, in metres:
  FLOOR PLAN     the place (water and fields as filled areas, paths as bands with their width, objects, walls, doors),
                 the key light's source, the axis, every camera as an icon pointing where it looks, and a table of the
                 cameras: which shots, size, lens, height, purpose.
  BLOCKING PLAN  the same place, each person's positions numbered in story order (1 START … n END), a dashed arrow for
                 every walk, a dotted line to what they look at, and a short note at each position; a list underneath.
Older records carry less (a water EDGE instead of an area, a path without width, no notes): the drawing fills in
plain defaults (a water band on the far side of the edge, a 1.2 m path) and says nothing it does not know.
"""
from __future__ import annotations

import math
import re
from html import escape
from typing import Any

from chain import POSTURE
from checks import Report
from geometry import COMPASS, P, World, dot
from schema import Landmark, Mark, SceneRecord

BG, GROUND, INK, MUTED = "#15171a", "#2b2f27", "#f2f2f2", "#9aa3ab"
FILL = {"water": "#3a87ab", "area": "#4f6b3e", "path": "#8c7658", "furniture": "#8a6847", "fixed": "#a3a3a3",
        "door": "#c9a46b", "wall": "#e6e6e6"}
PEOPLE = ("#e893a8", "#6fa3d6", "#7fc48a", "#c49be0", "#e0b45a", "#5fc4bd")
WALK = "#e2a93a"
W_MAX, H_MAX = 820, 560


def compass_of(v: P) -> str:
    ang = math.degrees(math.atan2(v.y, v.x)) % 360
    return ("east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east")[
        int((ang + 22.5) // 45) % 8]


def area_colour(lm: Landmark) -> str:
    n = lm.name.lower()
    if lm.kind == "water" or any(w in n for w in ("water", "canal", "river", "pond", "lake", "sea", "rain")):
        return FILL["water"]
    for words, col in ((("concrete", "stone", "lip", "slab", "step", "cement"), "#8d8f8f"),
                       (("bank", "earth", "mud", "bund", "road", "yard"), "#6e5a42"),
                       (("shop", "room", "floor", "house", "hall", "kitchen", "office", "inside"), "#3a332b"),
                       (("paddy", "field", "grass", "garden", "rice", "lawn"), "#4f6b3e")):
        if any(w in n for w in words):
            return col
    return "#55604b"


def area(pts: list[P]) -> float:
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1], strict=True))) / 2


def short(name: str) -> str:
    """A plan label: 'Weathered metal sluice gate between low concrete cheeks' -> 'sluice gate'."""
    t = name.strip()
    if " of the " in t:
        t = t.split(" of the ", 1)[1]
    t = re.split(r"\s(?:between|beside|beyond|behind|at|in|on|to the|near|under|with)\s|,", t, maxsplit=1)[0]
    words = t.split()
    return " ".join(words[-2:]) if len(words) > 3 else t


class Plan:
    def __init__(self, rec: SceneRecord, scene: dict[str, Any], rep: Report, focus: list[P] | None = None,
                 pad: float = 2.0) -> None:
        self.rec, self.scene, self.rep, self.w = rec, scene, rep, World(rec)
        self.names = {p["id"]: p["name"] for p in scene["people"]} | {p["id"]: p["name"] for p in scene["props"]}
        self.colour = {p["id"]: PEOPLE[i % len(PEOPLE)] for i, p in enumerate(scene["people"])}
        pts = [P(p.x, p.y) for lm in rec.landmarks if lm.kind != "light" and len(lm.points) > 1
               and not (len(lm.points) >= 3 and area([P(q.x, q.y) for q in lm.points]) > 40) for p in lm.points]
        pts += [P(lm.points[0].x, lm.points[0].y) for lm in rec.landmarks if lm.kind != "light" and len(lm.points) == 1]
        pts += [P(m.x, m.y) for m in rec.marks] + [P(m.moves_to[0].x, m.moves_to[0].y) for m in rec.marks if m.moves_to]
        pts += [P(c.x, c.y) for c in rec.cameras]
        pts = focus or pts
        self.x0, self.x1 = min(p.x for p in pts) - pad, max(p.x for p in pts) + pad
        self.y0, self.y1 = min(p.y for p in pts) - pad, max(p.y for p in pts) + pad
        self.k = min(W_MAX / (self.x1 - self.x0), H_MAX / (self.y1 - self.y0))
        self.W, self.H = (self.x1 - self.x0) * self.k, (self.y1 - self.y0) * self.k
        self.centre = P((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)
        self.labels: list[tuple[int, float, float, str, int, str, str, str]] = []
        people = [P(m.x, m.y) for m in rec.marks]
        self.people_c = P(sum(p.x for p in people) / len(people), sum(p.y for p in people) / len(people)) \
            if people else self.centre

    def s(self, p: P) -> tuple[float, float]:
        return (p.x - self.x0) * self.k, (self.y1 - p.y) * self.k

    def poly(self, pts: list[P]) -> str:
        return " ".join("{:.1f},{:.1f}".format(*self.s(p)) for p in pts)

    def text(self, p: P, label: str, size: int = 13, fill: str = INK, weight: str = "normal", dy: float = 0,
             anchor: str = "middle", priority: int = 1) -> str:
        """Labels are kept and placed last (`resolve`), most important first, each nudged until it does not overlap
        one already placed; a place's label that finds no room is left out."""
        x, y = self.s(p)
        self.labels.append((priority, x, y + dy, label, size, fill, weight, anchor))
        return ""

    def resolve(self) -> str:
        # drawn symbols (pins, camera icons) are obstacles too, so a label never sits on one
        placed: list[tuple[float, float, float, float]] = list(getattr(self, "obstacles", []))
        out = []
        for pri, x, y, label, size, fill, weight, anchor in sorted(self.labels, key=lambda r: -r[0]):
            w, h = len(label) * size * 0.58, size + 3
            spot = None
            for dy in (0, -15, 15, -30, 30, -45, 45):
                for dx in (0, 45, -45):
                    x0 = x + dx - (w / 2 if anchor == "middle" else 0)
                    box = (x0, y + dy - h + 3, x0 + w, y + dy + 3)
                    if box[0] < 2 or box[2] > self.W - 2 or box[1] < 2 or box[3] > self.H - 2:
                        continue
                    if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                        spot = (dx, dy, box)
                        break
                if spot:
                    break
            if spot is None:
                if pri < 2:
                    continue
                # an important label with no free room: keep it inside the drawing, shortened if it must be
                room = int((self.W - 8) / (size * 0.58))
                if len(label) > room:
                    label = label[:max(room - 1, 4)] + "…"
                    w = len(label) * size * 0.58
                x0 = x - (w / 2 if anchor == "middle" else 0)
                shift = max(4 - x0, 0) - max(x0 + w - (self.W - 4), 0)
                spot = (shift, 0, (x0 + shift, y - h, x0 + shift + w, y))
            dx, dy, box = spot
            placed.append(box)
            out.append(f"<text x='{x + dx:.1f}' y='{y + dy:.1f}' font-size='{size}' fill='{fill}' "
                       f"font-weight='{weight}' text-anchor='{anchor}' paint-order='stroke' stroke='{BG}' "
                       f"stroke-width='3'>{escape(label)}</text>")
        return "".join(out)

    # ── the place ──────────────────────────────────────────────────────────────────────────────────────────────────
    def water_band(self, lm: Landmark) -> list[P]:
        """A water EDGE (a line) drawn as water 4 m deep on the side away from the people."""
        line = [P(p.x, p.y) for p in lm.points]
        a, b = line[0], line[-1]
        d = b - a
        n = P(-d.y, d.x).scale(1 / max(d.length(), 1e-6))
        mid = P((a.x + b.x) / 2, (a.y + b.y) / 2)
        if dot(n, self.people_c - mid) > 0:
            n = n.scale(-1)
        return [*line, *[p + n.scale(4) for p in reversed(line)]]

    def place(self) -> str:
        out = [f"<rect width='{self.W:.0f}' height='{self.H:.0f}' rx='10' fill='{GROUND}'/>"]
        labels = []
        order = {"area": 0, "water": 1, "path": 2, "wall": 3, "furniture": 4, "fixed": 5, "door": 6}
        for lm in sorted(self.rec.landmarks, key=lambda x: order.get(x.kind, 9)):
            if lm.kind == "light":
                continue
            pts = [P(p.x, p.y) for p in lm.points]
            col, name = FILL.get(lm.kind, "#888"), short(lm.name).upper()
            if lm.kind in ("area", "water"):
                col = area_colour(lm)
            mid = P(sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))
            if lm.kind in ("water", "area") and len(pts) >= 3 and area(pts) > 0.5:
                out.append(f"<polygon points='{self.poly(pts)}' fill='{col}' opacity='0.95'/>")
                labels.append(self.text(mid, name, 16, INK, "bold"))
            elif lm.kind == "water" and len(pts) > 1:
                band = self.water_band(lm)
                out.append(f"<polygon points='{self.poly(band)}' fill='{col}' opacity='0.95'/>")
                c = P(sum(p.x for p in band) / len(band), sum(p.y for p in band) / len(band))
                labels.append(self.text(c, name, 16, INK, "bold"))
            elif lm.kind == "path" and len(pts) > 1:
                wpx = (lm.width or 1.2) * self.k
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='{col}' stroke-width='{wpx:.1f}' "
                           "stroke-linecap='round' stroke-linejoin='round'/>")
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='#d9c7a3' stroke-width='1' "
                           "stroke-dasharray='6 5' opacity='0.5'/>")
                a = pts[len(pts) // 2 - 1] if len(pts) > 2 else pts[0]
                b = pts[len(pts) // 2]
                labels.append(self.text(P((a.x + b.x) / 2, (a.y + b.y) / 2), name, 12, "#3b3123", "bold",
                                        dy=(lm.width or 1.2) * self.k / 2 + 14))
            elif lm.kind == "wall" and len(pts) > 1:
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='{col}' stroke-width='6'/>")
            elif lm.kind == "area":  # an area given as one point is a SPOT (a table corner, a place to stand)
                r = max(5.0, (lm.width or 0.5) * self.k / 2)
                x, y = self.s(mid)
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='none' stroke='#b7d99c' "
                           "stroke-width='1.5' stroke-dasharray='3 3'/>")
                labels.append(self.text(mid, name.lower(), 10, "#b7d99c", dy=r + 12))
            elif len(pts) > 1:  # a fixed line (a lip, a fence)
                out.append(f"<polyline points='{self.poly(pts)}' fill='none' stroke='{col}' stroke-width='5' "
                           "stroke-linecap='round'/>")
                labels.append(self.text(pts[-1], name, 10, MUTED, dy=-8, anchor="start"))
            else:
                wd = (lm.width or {"furniture": 1.2, "door": 0.9}.get(lm.kind, 0.8)) * self.k
                ht = wd * (0.65 if lm.kind == "furniture" else 0.25 if lm.kind == "door" else 0.5)
                x, y = self.s(mid)
                out.append(f"<rect x='{x - wd / 2:.1f}' y='{y - ht / 2:.1f}' width='{wd:.1f}' height='{ht:.1f}' "
                           f"rx='4' fill='{col}'/>")
                labels.append(self.text(mid, name, 12, INK, dy=-ht / 2 - 6))
        return "".join(out) + "".join(labels)

    def light(self) -> str:
        out = []
        for lm in self.rec.landmarks:
            if lm.kind != "light":
                continue
            p = P(lm.points[0].x, lm.points[0].y)
            inside = self.x0 <= p.x <= self.x1 and self.y0 <= p.y <= self.y1
            if not inside:  # put the sun on the border, in its direction from the centre
                d = p - self.centre
                t = min((self.x1 - self.centre.x - 0.6) / d.x if d.x > 0 else (self.x0 - self.centre.x + 0.6) / d.x
                        if d.x < 0 else 1e9,
                        (self.y1 - self.centre.y - 0.6) / d.y if d.y > 0 else (self.y0 - self.centre.y + 0.6) / d.y
                        if d.y < 0 else 1e9)
                p = self.centre + d.scale(t)
            x, y = self.s(p)
            rays = "".join(f"<line x1='{x + 9 * math.cos(a):.1f}' y1='{y + 9 * math.sin(a):.1f}' "
                           f"x2='{x + 14 * math.cos(a):.1f}' y2='{y + 14 * math.sin(a):.1f}' stroke='#f2c94c' "
                           "stroke-width='2'/>" for a in [i * math.pi / 4 for i in range(8)])
            key = " (KEY)" if lm.id == self.rec.light.key else ""
            out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='7' fill='#f2c94c'/>{rays}"
                       + self.text(p, short(lm.name).upper() + key, 11, "#f2c94c", "bold", dy=26))
        return "".join(out)

    def axis(self) -> str:
        out = []
        for ax in self.rec.axes[:1]:
            first = self.rec.shots[0].start if self.rec.shots else "K0"
            a, b = self.w.point_of(ax.a, first, ax.from_beat), self.w.point_of(ax.b, first, ax.from_beat)
            if a is None or b is None or (b - a).length() == 0:
                continue
            d = (b - a).scale(1 / (b - a).length())
            p1, p2 = a + d.scale(-40), b + d.scale(40)
            x1, y1 = self.s(p1)
            x2, y2 = self.s(p2)
            out.append(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' stroke='#e5534b' "
                       "stroke-width='1.5' stroke-dasharray='8 6' opacity='0.8'/>")
            out.append(self.text(b + d.scale(1.2), f"AXIS · cameras stay {ax.camera_side}", 11, "#e5534b", dy=-8))
        return "".join(out)

    # ── cameras ────────────────────────────────────────────────────────────────────────────────────────────────────
    def cameras(self) -> str:
        """Each SETUP (cameras within half a metre are one position) as a blue triangle pointing at its first target,
        with a dashed arrow to every subject its shots film, and its id, role and shots."""
        out, arrows = [], []
        for ids in self.w.setups(cluster_m=0.15):
            c = self.w.cams[ids[0]]
            shots = [s for s in self.rec.shots if s.camera in ids]
            x, y = self.s(P(c.x, c.y))
            targets: list[P] = []
            for s in shots:
                cam = self.w.cam(s)
                t = self.w.point_of(cam.looks_at, s.start, s.beat) if cam else None
                if t is not None and all((t - q).length() > 0.3 for q in targets):
                    targets.append(t)
            for t in targets:
                v = t - P(c.x, c.y)
                if v.length() < 0.2:
                    continue
                stop = P(c.x, c.y) + v.scale(max(0.0, (v.length() - 0.35)) / v.length())
                ex, ey = self.s(stop)
                arrows.append(f"<line x1='{x:.1f}' y1='{y:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='#5aa7f0' "
                              "stroke-width='2.5' stroke-dasharray='7 5' marker-end='url(#camarrow)'/>")
            u = (targets[0] - P(c.x, c.y)) if targets else P(0, 1)
            u = u.scale(1 / max(u.length(), 1e-6))
            ang = math.atan2(-u.y, u.x)
            tri = [(x + 15 * math.cos(ang), y + 15 * math.sin(ang)),
                   (x + 12 * math.cos(ang + 2.3), y + 12 * math.sin(ang + 2.3)),
                   (x + 12 * math.cos(ang - 2.3), y + 12 * math.sin(ang - 2.3))]
            out.append("<polygon points='" + " ".join(f"{a:.1f},{b:.1f}" for a, b in tri) +
                       "' fill='#4aa3ff' stroke='white' stroke-width='2'/>")
            roles = ", ".join(dict.fromkeys(self.w.cams[i].role for i in ids))
            self.text(P(c.x, c.y), f"{'/'.join(ids)} · {roles}", 12, INK, "bold", dy=-20, priority=2)
            self.text(P(c.x, c.y), "shot " + ", ".join(s.id for s in shots), 10, MUTED, dy=28, priority=2)
        return "".join(arrows) + "".join(out)

    # ── blocking ───────────────────────────────────────────────────────────────────────────────────────────────────
    def positions(self) -> dict[str, list[dict[str, Any]]]:
        """Each person's positions in story order; repeated marks on the same spot and posture are one position."""
        out: dict[str, list[dict[str, Any]]] = {}
        for who in [p["id"] for p in self.scene["people"]]:
            own = sorted((m for m in self.rec.marks if m.who == who), key=lambda m: m.beat)
            seq: list[dict[str, Any]] = []
            for m in own:
                last = seq[-1] if seq else None
                if last and (P(m.x, m.y) - last["at"]).length() < 0.2 and m.posture == last["mark"].posture \
                        and not m.moves_to and not last["mark"].moves_to:
                    last["beats"].append(m.beat)
                    continue
                seq.append({"mark": m, "at": P(m.x, m.y), "beats": [m.beat]})
            if seq and seq[-1]["mark"].moves_to:  # a walk that ends nowhere marked: its end is a position too
                end = seq[-1]["mark"].moves_to[0]
                seq.append({"mark": None, "at": P(end.x, end.y), "beats": seq[-1]["beats"][-1:], "end_of": True})
            out[who] = seq
        return out

    def note(self, who: str, pos: dict[str, Any], i: int, n: int) -> str:
        m: Mark | None = pos["mark"]
        if m is None:
            return "end of the walk"
        tag = "START · " if i == 0 and n > 1 else "END · " if i == n - 1 and n > 1 else ""
        text = m.label.strip() if m.label.strip() else POSTURE.get(m.posture, m.posture)
        if m.moves_to and not m.label.strip():
            d = P(m.moves_to[0].x - m.x, m.moves_to[0].y - m.y)
            text = f"walks {compass_of(d)} {d.length():.0f} m"
        return tag + text

    def blocking(self) -> tuple[str, list[str]]:
        out, notes, caps = [], [], []
        multi = len(self.scene["people"]) > 1
        for who, seq in self.positions().items():
            col = self.colour[who]
            name = self.names.get(who, who)
            initial = name[:1].upper() if multi else "P"
            for pos in seq:
                m = pos["mark"]
                if m is not None and m.moves_to:
                    a, b = self.s(pos["at"]), self.s(P(m.moves_to[0].x, m.moves_to[0].y))
                    out.append(f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' stroke='{WALK}' "
                               "stroke-width='4' stroke-dasharray='10 7' marker-end='url(#arrow)'/>")
                if m is not None and m.facing:
                    fv = self.w.facing_vector(m.facing, pos["at"], "K0", m.beat)
                    if fv is not None and fv.length() > 0 and m.facing not in COMPASS:
                        tip = pos["at"] + fv.scale(min(1.0, fv.length() * 0.6) / fv.length())
                        a, b = self.s(pos["at"]), self.s(tip)
                        out.append(f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' "
                                   f"stroke='{col}' stroke-width='2' stroke-dasharray='2 4'/>")
            n = len(seq)
            spots: list[dict[str, Any]] = []  # positions on (nearly) one spot share a pin: N1·N2·N3
            for i, pos in enumerate(seq):
                label = f"{initial}{i + 1}"
                note = self.note(who, pos, i, n)
                spot = next((sp for sp in spots if (sp["at"] - pos["at"]).length() < 0.3), None)
                if spot is None:
                    spots.append({"at": pos["at"], "labels": [label], "notes": [note], "hollow": pos.get("end_of")})
                else:
                    spot["labels"].append(label)
                    spot["notes"].append(note)
                beats = pos["beats"]
                span = f"beat {beats[0]}" if len(beats) == 1 else f"beats {beats[0]}–{beats[-1]}"
                caps.append(f"<li><b style='color:{col}'>{label}</b> {escape(name)}, {span}: {escape(note)}"
                            + (f" (posture: {escape(POSTURE.get(pos['mark'].posture, ''))})" if pos["mark"] else "")
                            + "</li>")
            for j, sp in enumerate(spots):
                x, y = self.s(sp["at"])
                tag = "·".join(sp["labels"])
                r = 12 + 5 * (len(sp["labels"]) - 1)
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r}' fill='{BG if sp['hollow'] else col}' "
                           f"stroke='white' stroke-width='3'/><text x='{x:.1f}' y='{y + 4:.1f}' font-size='10' "
                           f"font-weight='bold' fill='{col if sp['hollow'] else '#1a1a1a'}' text-anchor='middle'>"
                           f"{escape(tag)}</text>")
                note = " → ".join(sp["notes"])
                note = note if len(note) < 70 else note[:67] + "…"
                self.text(sp["at"], f"{tag} {note}", 11, INK, "bold", dy=-r - 8 if j % 2 == 0 else r + 16,
                          priority=3)
        return "".join(out) + "".join(notes), caps

    def ghosts(self) -> str:
        """People, small, on the floor plan (where they are while the cameras are placed)."""
        out = []
        for who, seq in self.positions().items():
            for pos in seq:
                x, y = self.s(pos["at"])
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='6' fill='{self.colour[who]}' opacity='0.8'/>")
        return "".join(out)

    def svg(self, body: str) -> str:
        return (f"<svg viewBox='0 0 {self.W:.0f} {self.H:.0f}' width='{self.W:.0f}' height='{self.H:.0f}' "
                "xmlns='http://www.w3.org/2000/svg' font-family='system-ui, sans-serif' style='overflow:hidden;"
                "border-radius:10px'><defs><marker id='arrow' "
                "markerUnits='userSpaceOnUse' markerWidth='12' markerHeight='12' refX='10' refY='6' orient='auto'><path d='M0,0 L12,6 L0,12 z' "
                f"fill='{WALK}'/></marker><marker id='camarrow' markerUnits='userSpaceOnUse' markerWidth='12' markerHeight='12' refX='10' refY='6' orient='auto'><path d='M0,0 L12,6 L0,12 z' fill='#5aa7f0'/></marker></defs>{body}{self.resolve()}</svg>")

    def camera_rows(self) -> str:
        rows = []
        for c in self.rec.cameras:
            shots = [s for s in self.rec.shots if s.camera == c.id]
            if not shots:
                continue
            sizes = ", ".join(f"{s.id} {s.size}" for s in shots)
            lenses = ", ".join(dict.fromkeys(f"{s.lens_mm or c.lens_mm} mm" for s in shots))
            covers = c.covers or shots[0].purpose
            rows.append(f"<tr><td><b>{escape(c.id)}</b></td><td>{escape(c.role)}</td><td>{escape(sizes)}</td>"
                        f"<td>{escape(lenses)}</td><td>{escape(c.height.replace('_', ' '))}</td>"
                        f"<td>{escape(covers)}</td></tr>")
        return "".join(rows)


def html(rec: SceneRecord, scene: dict[str, Any], rep: Report) -> str:
    pl = Plan(rec, scene, rep)
    floor = pl.svg(pl.place() + pl.axis() + pl.light() + pl.ghosts() + pl.cameras())
    action = [P(m.x, m.y) for m in rec.marks] + [P(m.moves_to[0].x, m.moves_to[0].y) for m in rec.marks if m.moves_to]
    people_c = P(sum(p.x for p in action) / len(action), sum(p.y for p in action) / len(action))
    near = action + [P(c.x, c.y) for c in rec.cameras if (P(c.x, c.y) - people_c).length() < 4]
    zoom = Plan(rec, scene, rep, focus=near, pad=1.2)
    close = zoom.svg(zoom.place() + zoom.axis() + zoom.light() + zoom.ghosts() + zoom.cameras())
    bl = Plan(rec, scene, rep, focus=action, pad=2.2)
    body, caps = bl.blocking()
    block = bl.svg(bl.place() + bl.light() + body)
    legend = " ".join(f"<span style='color:{pl.colour[p['id']]}'>● {escape(p['name'])}</span>" for p in scene["people"])
    zoom_part = (f"<h2>Floor plan — the setups near the action (zoom)</h2><div class='card'>{close}</div>"
                 if (pl.x1 - pl.x0) > 1.6 * (zoom.x1 - zoom.x0) else "")
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Floor plan: {escape(rec.scene)}</title><style>
body{{background:{BG};color:{INK};font-family:system-ui,sans-serif;margin:20px;max-width:900px}}
h1{{font-size:20px}} h2{{font-size:15px;margin:26px 0 10px}} .card{{border:1px solid #2c3136;border-radius:12px;
padding:14px;background:#0f1113}} p,li{{color:#c9d1d9;font-size:13px}} table{{border-collapse:collapse;width:100%;
font-size:13px;margin-top:12px}} td,th{{border-bottom:1px solid #2c3136;padding:7px 8px;text-align:left;
vertical-align:top}} th{{color:{MUTED};font-weight:600}} .legend{{font-size:13px;margin:6px 0}}
</style></head><body><h1>{escape(scene.get('title', rec.scene))}</h1>
<p>{escape(scene.get('heading', ''))} · north is up · drawn by code from the scene record (metres).</p>
<p class='legend'>{legend} · <span style='color:{WALK}'>- - → walk</span> ·
<span style='color:#9cc3e6'>▲ camera, line = where it looks</span> · <span style='color:#e5534b'>- - axis</span></p>
<h2>Blocking plan — top view</h2><div class='card'>{block}<ul>{''.join(caps)}</ul></div>
<h2>Floor plan — top view (every camera)</h2><div class='card'>{floor}
<p>{len(pl.w.setups(cluster_m=0.15))} camera positions for {sum(1 for s in rec.shots if s.camera)} shots.</p>
<table><tr><th>Setup</th><th>Role</th><th>Shots</th><th>Lens</th><th>Height</th><th>Covers</th></tr>
{pl.camera_rows()}</table></div>{zoom_part}
</body></html>"""
