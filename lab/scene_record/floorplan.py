"""The record's floor plan as an SVG a person can read: landmarks, marks per beat, the axis, cameras and their view.

North is up. Marks are coloured by person and labelled '<who> b<beat>'; an arrow shows a walk to its moves_to; a tick
shows which way they face. Each camera is a blue dot with its id, a wedge for its lens and the shots that use it.
"""
from __future__ import annotations

import math
from html import escape

from geometry import P, World, hfov
from schema import SceneRecord

PALETTE = ("#c0392b", "#2c6fbb", "#27ae60", "#8e44ad", "#d35400", "#16a085")


def svg(rec: SceneRecord) -> str:
    w = World(rec)
    pts: list[P] = [P(m.x, m.y) for m in rec.marks] + [P(c.x, c.y) for c in rec.cameras]
    pts += [P(p.x, p.y) for lm in rec.landmarks for p in lm.points]
    pts += [P(m.moves_to[0].x, m.moves_to[0].y) for m in rec.marks if m.moves_to]
    if not pts:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    x0, x1 = min(p.x for p in pts) - 1.5, max(p.x for p in pts) + 1.5
    y0, y1 = min(p.y for p in pts) - 1.5, max(p.y for p in pts) + 1.5
    k = min(900 / max(x1 - x0, 1), 700 / max(y1 - y0, 1))
    W, H = (x1 - x0) * k, (y1 - y0) * k

    def sx(x: float) -> float:
        return (x - x0) * k

    def sy(y: float) -> float:
        return (y1 - y) * k

    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{W:.0f}' height='{H + 30:.0f}' "
           "font-family='sans-serif' font-size='11'>", "<rect width='100%' height='100%' fill='#fbfaf7'/>",
           f"<text x='8' y='{H + 20:.0f}' fill='#555'>{escape(rec.scene)} · 1 m = {k:.0f} px · north up</text>"]
    for lm in rec.landmarks:
        ps = lm.points
        colour = {"water": "#7fb3d5", "path": "#b9770e", "light": "#f1c40f"}.get(lm.kind, "#7f8c8d")
        if len(ps) > 1:
            d = " ".join(f"{sx(p.x):.1f},{sy(p.y):.1f}" for p in ps)
            out.append(f"<polyline points='{d}' fill='none' stroke='{colour}' stroke-width='6' opacity='0.5'/>")
        c = ps[len(ps) // 2]
        r = 9 if lm.kind == "light" else 5
        out.append(f"<circle cx='{sx(c.x):.1f}' cy='{sy(c.y):.1f}' r='{r}' fill='{colour}'/>")
        out.append(f"<text x='{sx(c.x) + 8:.1f}' y='{sy(c.y) - 6:.1f}' fill='#555'>{escape(lm.name)}</text>")
    for ax in rec.axes:
        a = w.point_of(ax.a, rec.shots[0].start if rec.shots else "K0", ax.from_beat)
        b = w.point_of(ax.b, rec.shots[0].start if rec.shots else "K0", ax.from_beat)
        if a and b and (b - a).length() > 0:
            d = (b - a).scale(1 / (b - a).length())
            p1, p2 = a + d.scale(-3), b + d.scale(3)
            out.append(f"<line x1='{sx(p1.x):.1f}' y1='{sy(p1.y):.1f}' x2='{sx(p2.x):.1f}' y2='{sy(p2.y):.1f}' "
                       "stroke='#e74c3c' stroke-dasharray='6 4'/>")
            out.append(f"<text x='{sx(p2.x):.1f}' y='{sy(p2.y) - 4:.1f}' fill='#e74c3c'>axis b{ax.from_beat}+ "
                       f"(cameras {ax.camera_side})</text>")
    people = sorted({m.who for m in rec.marks})
    col = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(people)}
    for m in rec.marks:
        c = col[m.who]
        out.append(f"<circle cx='{sx(m.x):.1f}' cy='{sy(m.y):.1f}' r='8' fill='white' stroke='{c}' stroke-width='2'/>")
        out.append(f"<text x='{sx(m.x) - 8:.1f}' y='{sy(m.y) + 22:.1f}' fill='{c}'>{escape(m.who)} b{m.beat} "
                   f"{m.posture}</text>")
        fv = w.facing_vector(m.facing, P(m.x, m.y), "K0", m.beat)
        if fv and fv.length() > 0:
            u = fv.scale(0.45 / fv.length())
            out.append(f"<line x1='{sx(m.x):.1f}' y1='{sy(m.y):.1f}' x2='{sx(m.x + u.x):.1f}' y2='{sy(m.y + u.y):.1f}'"
                       f" stroke='{c}' stroke-width='3'/>")
        if m.moves_to:
            t = m.moves_to[0]
            out.append(f"<line x1='{sx(m.x):.1f}' y1='{sy(m.y):.1f}' x2='{sx(t.x):.1f}' y2='{sy(t.y):.1f}' "
                       f"stroke='{c}' stroke-dasharray='3 3' marker-end='url(#a)'/>")
            out.append(f"<circle cx='{sx(t.x):.1f}' cy='{sy(t.y):.1f}' r='4' fill='{c}'/>")
    out.insert(1, "<defs><marker id='a' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto'>"
                  "<path d='M0,0 L6,3 L0,6 z' fill='#333'/></marker></defs>")
    uses: dict[str, list[str]] = {}
    for s in rec.shots:
        if s.camera:
            uses.setdefault(s.camera, []).append(s.id)
    for c in rec.cameras:
        first = next((s for s in rec.shots if s.camera == c.id), None)
        f = w.forward(c, first) if first else None
        if f is not None:
            half = math.radians(hfov(c.lens_mm) / 2)
            base = math.atan2(f.y, f.x)
            L = min(f.length(), 4.0)
            for a in (base - half, base + half):
                ex, ey = c.x + L * math.cos(a), c.y + L * math.sin(a)
                out.append(f"<line x1='{sx(c.x):.1f}' y1='{sy(c.y):.1f}' x2='{sx(ex):.1f}' y2='{sy(ey):.1f}' "
                           "stroke='#2e86de' opacity='0.45'/>")
        out.append(f"<circle cx='{sx(c.x):.1f}' cy='{sy(c.y):.1f}' r='9' fill='#2e86de'/>")
        out.append(f"<text x='{sx(c.x) - 4:.1f}' y='{sy(c.y) + 4:.1f}' fill='white' font-weight='bold'>"
                   f"{escape(c.id)}</text>")
        out.append(f"<text x='{sx(c.x) + 12:.1f}' y='{sy(c.y) + 4:.1f}' fill='#2e86de'>{c.lens_mm}mm · shots "
                   f"{', '.join(uses.get(c.id, []))}</text>")
    out.append("</svg>")
    return "\n".join(out)
