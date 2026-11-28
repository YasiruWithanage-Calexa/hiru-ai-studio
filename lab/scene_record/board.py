"""A code-drawn board: what each camera of a scene record sees, at the shot's first and last instant. Free, no model.

Not a painting. A pinhole camera at the camera's position, height and lens (full-frame, 16:9) looks at its target;
every mark (a figure: standing, seated, kneeling or lying, its colour per person, a nose tick for the way it faces),
every prop (a white dot by the hand that holds it, or on the landmark it rests on) and the landmarks (paths and water
as ground lines, fixed things as posts, areas as ground patches) are projected into the frame. What is outside the
lens is outside the frame. Beside the two frames, the floor plan at the shot's opening with this camera's view.

So a person can check a plan by eye: who is on which side, who faces whom, what size the shot really is, whether
the shot after a cut opens where the shot before ended, whether anyone vanishes.
"""
from __future__ import annotations

import math
from html import escape
from itertools import pairwise
from typing import Any

from checks import Report
from geometry import COMPASS, P, World, hfov
from schema import CutPoint, SceneRecord, Shot

W, H = 384, 216
CAM_H = {"ground": 0.15, "knee": 0.5, "seated_eye": 1.1, "standing_eye": 1.6, "high": 2.6, "overhead": 5.0}
BODY_H = {"standing": 1.65, "walking": 1.65, "rising": 1.4, "seated": 1.25, "sitting_down": 1.3, "leaning": 1.5,
          "kneeling": 1.0, "kneeling_down": 1.2, "crouching": 0.95, "lying": 0.25}
PALETTE = ("#d0453a", "#2f6fc0", "#2f9e5b", "#8e44ad", "#d77a1a", "#16a085")
LAND = {"water": "#6fa8d6", "path": "#b98a4e", "area": "#9fcf8f", "light": "#f1c40f", "furniture": "#8d6e63",
        "door": "#7f8c8d", "fixed": "#6d6d6d"}


class Cam:
    """A pinhole: position, height, a horizontal aim at the target and a pitch toward the target's height."""

    def __init__(self, w: World, shot: Shot, aim_h: float) -> None:
        c = w.cam(shot)
        assert c is not None
        self.c = c
        self.x, self.y, self.h = c.x, c.y, CAM_H.get(c.height, 1.5)
        f = w.forward(c, shot) or P(0, 1)
        d = f.length()
        self.fx, self.fy = f.x / d, f.y / d
        self.th = math.tan(math.radians(hfov(c.lens_mm)) / 2)
        self.tv = self.th * 9 / 16
        # aim at the target; a high or low angle keeps it in frame, nudged by a third of the half frame
        pitch = math.atan2(aim_h - self.h, max(d, 0.05))
        nudge = math.atan(self.tv) / 3
        if shot.angle == "high":
            pitch -= nudge
        elif shot.angle == "low":
            pitch += nudge
        elif shot.angle == "overhead":
            pitch = math.radians(-75)
        self.cp, self.sp = math.cos(pitch), math.sin(pitch)

    def project(self, x: float, y: float, z: float) -> tuple[float, float, float] | None:
        vx, vy, vz = x - self.x, y - self.y, z - self.h
        fh = vx * self.fx + vy * self.fy  # along the horizontal aim
        r = vx * self.fy - vy * self.fx  # to the right
        zc = fh * self.cp + vz * self.sp  # depth
        yc = -fh * self.sp + vz * self.cp  # up
        if zc < 0.05:
            return None
        sx, sy = r / (zc * self.th), yc / (zc * self.tv)
        return W / 2 * (1 + sx), H / 2 * (1 - sy), zc

    def px(self, metres: float, depth: float) -> float:
        return metres / (depth * self.th) * W / 2


def _target_height(w: World, shot: Shot, cut: CutPoint) -> float:
    me = next((p for p in cut.people if p.who == shot.subject), None)
    if me is not None:
        top = BODY_H.get(me.posture, 1.6)
        return top - 0.12 if shot.size in ("CU", "ECU", "MCU") else top * 0.75 if shot.size == "MS" else top * 0.55
    if shot.subject in w.props:
        return _prop_height(w, shot.subject, cut)
    return 0.6


def _prop_height(w: World, prop: str, cut: CutPoint) -> float:
    st = w.prop_state(prop, cut.id)
    if st is None:
        return 0.5
    if st.on:
        return 0.78 if w.land.get(st.on) and w.land[st.on].kind == "furniture" else 0.02
    holder = next((p for p in cut.people if p.who == st.holder), None)
    if holder is None:
        return 0.5
    top = BODY_H.get(holder.posture, 1.6)
    return 0.12 if holder.posture == "lying" else top * (0.45 if st.hand else 0.62)


def frame_svg(w: World, shot: Shot, cut: CutPoint, colour: dict[str, str], names: dict[str, str]) -> str:
    cam = Cam(w, shot, _target_height(w, shot, cut))
    items: list[tuple[float, str]] = []  # (depth, svg) drawn far to near
    sky = cam.project(cam.x + cam.fx * 1000, cam.y + cam.fy * 1000, cam.h)
    horizon = max(0.0, min(H, sky[1])) if sky else 0.0
    out = [f"<rect width='{W}' height='{H}' fill='#d9dde2'/>",
           f"<rect y='{horizon:.1f}' width='{W}' height='{H - horizon:.1f}' fill='#cdbfa9'/>"]
    # ground lines and patches
    for lm in w.rec.landmarks:
        col = LAND.get(lm.kind, "#777")
        pts = lm.points
        if len(pts) >= 2 and lm.kind in ("path", "water", "area"):
            seq = [*pts, pts[0]] if lm.kind == "area" else pts
            dense = []
            for a, b in pairwise(seq):
                n = max(2, int(math.hypot(b.x - a.x, b.y - a.y) / 0.2))
                dense += [(a.x + (b.x - a.x) * i / n, a.y + (b.y - a.y) * i / n) for i in range(n + 1)]
            run: list[str] = []
            segs: list[list[str]] = []
            for x, y in dense:
                p = cam.project(x, y, 0.0)
                if p is None:
                    if run:
                        segs.append(run)
                    run = []
                    continue
                run.append(f"{p[0]:.1f},{p[1]:.1f}")
            if run:
                segs.append(run)
            width = 2 if lm.kind == "area" else 6
            for s in segs:
                if len(s) > 1:
                    out.append(f"<polyline points='{' '.join(s)}' fill='none' stroke='{col}' stroke-width='{width}' "
                               "stroke-linecap='round' opacity='0.8'/>")
        else:
            c = pts[0]
            tall = {"fixed": 1.4, "furniture": 0.78, "door": 2.0, "light": 1.8}.get(lm.kind, 1.0)
            a, b = cam.project(c.x, c.y, 0.0), cam.project(c.x, c.y, tall)
            if a and b:
                wd = min(18.0, max(3.0, cam.px(0.5 if lm.kind != "light" else 0.2, a[2])))
                items.append((a[2], f"<rect x='{a[0] - wd / 2:.1f}' y='{b[1]:.1f}' width='{wd:.1f}' "
                                    f"height='{max(2.0, a[1] - b[1]):.1f}' fill='{col}' opacity='0.85'/>"
                                    + (f"<text x='{a[0] + wd / 2 + 2:.1f}' y='{b[1] + 10:.1f}' font-size='9' "
                                       f"fill='#333'>{escape(lm.id)}</text>")))
    body_op = 0.35 if shot.subject in w.props or shot.type == "insert" else 0.92
    tops: list[str] = []  # props, drawn last so a body never hides them
    # people
    for p in cut.people:
        m = w.marks.get(p.mark)
        if m is None:
            continue
        at = w.mark_point(m, p.progress)
        col = colour.get(p.who, "#444")
        top = BODY_H.get(p.posture, 1.6)
        face = w.facing_vector(p.look_at or m.facing, at, cut.id, shot.beat)
        if face is not None and face.length() > 0:
            face = face.scale(1 / face.length())
        if p.posture == "lying":
            d = face if face is not None else P(1, 0)
            d = P(*COMPASS["east"]) if m.facing in ("sky", "") or face is None else d
            head, feet = at + d.scale(0.8), at + d.scale(-0.9)
            a, b = cam.project(head.x, head.y, 0.15), cam.project(feet.x, feet.y, 0.12)
            if a and b:
                wd = max(3.0, cam.px(0.35, (a[2] + b[2]) / 2))
                svg = (f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' stroke='{col}' "
                       f"stroke-width='{wd:.1f}' stroke-linecap='round' opacity='{body_op}'/>"
                       f"<circle cx='{a[0]:.1f}' cy='{a[1]:.1f}' r='{max(2.0, cam.px(0.12, a[2])):.1f}' fill='{col}' "
                       f"stroke='#222' stroke-width='1' opacity='{body_op}'/>")
                items.append((min(a[2], b[2]), svg + _label(a, names.get(p.who, p.who) + " (lying)", col)))
            elif a or b:
                q = a or b
                items.append((q[2], f"<circle cx='{q[0]:.1f}' cy='{q[1]:.1f}' r='{max(3.0, cam.px(0.2, q[2])):.1f}'"
                                    f" fill='{col}'/>"))
            continue
        foot, neck = cam.project(at.x, at.y, 0.0), cam.project(at.x, at.y, top - 0.24)
        head = cam.project(at.x, at.y, top - 0.12)
        if not (foot and neck and head):
            continue
        wd = max(3.0, cam.px(0.42, head[2]))
        svg = (f"<line x1='{foot[0]:.1f}' y1='{foot[1]:.1f}' x2='{neck[0]:.1f}' y2='{neck[1]:.1f}' stroke='{col}' "
               f"stroke-width='{wd:.1f}' stroke-linecap='round' opacity='{body_op}'/>"
               f"<circle cx='{head[0]:.1f}' cy='{head[1]:.1f}' r='{max(2.5, cam.px(0.12, head[2])):.1f}' fill='{col}' "
               f"stroke='#222' stroke-width='1' opacity='{body_op}'/>")
        if face is not None:
            nose = cam.project(at.x + face.x * 0.3, at.y + face.y * 0.3, top - 0.12)
            if nose:
                svg += (f"<line x1='{head[0]:.1f}' y1='{head[1]:.1f}' x2='{nose[0]:.1f}' y2='{nose[1]:.1f}' "
                        "stroke='#111' stroke-width='2'/>")
        items.append((head[2], svg + _label(head, names.get(p.who, p.who), col)))
    # props
    for prop in sorted(w.props):
        st = w.prop_state(prop, cut.id)
        if st is None or not st.seen:
            continue
        pt = w.point_of(prop, cut.id, shot.beat)
        if pt is None:
            continue
        holder = next((p for p in cut.people if p.who == st.holder), None) if st.holder else None
        if holder is not None and not st.on and prop != shot.subject:  # a shot ON the prop aims where it is drawn
            m = w.marks.get(holder.mark)
            fv = w.facing_vector(holder.look_at or (m.facing if m else ""), pt, cut.id, shot.beat) if m else None
            if fv is not None and fv.length() > 0 and st.hand in ("left", "right"):
                u = fv.scale(1 / fv.length())
                side = P(-u.y, u.x) if st.hand == "left" else P(u.y, -u.x)
                pt = pt + side.scale(0.25) + u.scale(0.15)
        q = cam.project(pt.x, pt.y, _prop_height(w, prop, cut))
        if q:
            tops.append(f"<circle cx='{q[0]:.1f}' cy='{q[1]:.1f}' r='{min(14.0, max(3.5, cam.px(0.06, q[2]))):.1f}'"
                                       f" fill='white' stroke='#222' stroke-width='1.2'/>"
                                       + _label(q, names.get(prop, prop), "#222", dy=-6))
    out += [s for _, s in sorted(items, key=lambda t: -t[0])] + tops
    return (f"<svg viewBox='0 0 {W} {H}' width='{W}' height='{H}' xmlns='http://www.w3.org/2000/svg' "
            f"font-family='sans-serif'><defs><clipPath id='c'><rect width='{W}' height='{H}'/></clipPath></defs>"
            f"<g clip-path='url(#c)'>{''.join(out)}</g><rect width='{W}' height='{H}' fill='none' stroke='#222'/></svg>")


def _label(at: tuple[float, float, float], text: str, col: str, dy: float = -10) -> str:
    return (f"<text x='{at[0] + 5:.1f}' y='{at[1] + dy:.1f}' font-size='10' fill='{col}' stroke='white' "
            f"stroke-width='3' paint-order='stroke'>{escape(text)}</text>")


def plan_svg(w: World, shot: Shot, cut: CutPoint, colour: dict[str, str]) -> str:
    """The floor plan at the cut point, with this camera and its view."""
    rec = w.rec
    pts = [P(m.x, m.y) for m in rec.marks] + [P(c.x, c.y) for c in rec.cameras]
    pts += [P(p.x, p.y) for lm in rec.landmarks for p in lm.points if lm.kind != "light"]
    x0, x1 = min(p.x for p in pts) - 1, max(p.x for p in pts) + 1
    y0, y1 = min(p.y for p in pts) - 1, max(p.y for p in pts) + 1
    k = min(200 / max(x1 - x0, 1), H / max(y1 - y0, 1))
    pw, ph = (x1 - x0) * k, (y1 - y0) * k

    def s(p: P) -> tuple[float, float]:
        return (p.x - x0) * k, (y1 - p.y) * k

    out = [f"<rect width='{pw:.0f}' height='{ph:.0f}' fill='#f7f5f0'/>"]
    for lm in rec.landmarks:
        if lm.kind == "light":
            continue
        col = LAND.get(lm.kind, "#777")
        if len(lm.points) > 1:
            d = " ".join("{:.1f},{:.1f}".format(*s(P(p.x, p.y))) for p in lm.points)
            out.append(f"<polyline points='{d}' fill='none' stroke='{col}' stroke-width='4' opacity='0.6'/>")
        else:
            a = s(P(lm.points[0].x, lm.points[0].y))
            out.append(f"<rect x='{a[0] - 3:.1f}' y='{a[1] - 3:.1f}' width='6' height='6' fill='{col}'/>")
    c = w.cam(shot)
    if c is not None:
        f = w.forward(c, shot)
        if f is not None:
            half, base = math.radians(hfov(c.lens_mm) / 2), math.atan2(f.y, f.x)
            L = min(f.length() * 1.3, 12)
            a = s(P(c.x, c.y))
            tri = [a, s(P(c.x + L * math.cos(base - half), c.y + L * math.sin(base - half))),
                   s(P(c.x + L * math.cos(base + half), c.y + L * math.sin(base + half)))]
            out.append("<polygon points='" + " ".join(f"{x:.1f},{y:.1f}" for x, y in tri) +
                       "' fill='#2e86de' opacity='0.18'/>")
            out.append(f"<circle cx='{a[0]:.1f}' cy='{a[1]:.1f}' r='5' fill='#2e86de'/><text x='{a[0] + 6:.1f}' "
                       f"y='{a[1] + 4:.1f}' font-size='10' fill='#2e86de'>{escape(c.id)}</text>")
    for p in cut.people:
        m = w.marks.get(p.mark)
        if m is None:
            continue
        a = s(w.mark_point(m, p.progress))
        out.append(f"<circle cx='{a[0]:.1f}' cy='{a[1]:.1f}' r='5' fill='{colour.get(p.who, '#444')}'/>")
    return (f"<svg viewBox='0 0 {pw:.0f} {ph:.0f}' width='{pw:.0f}' height='{ph:.0f}' "
            f"xmlns='http://www.w3.org/2000/svg'>{''.join(out)}</svg>")


def html(rec: SceneRecord, scene: dict[str, Any], rep: Report) -> str:
    w = World(rec)
    people = [p["id"] for p in scene["people"]]
    colour = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(people)}
    names = {p["id"]: p["name"] for p in scene["people"]} | {p["id"]: p["name"] for p in scene["props"]}
    beats = {b.n: b for b in rec.beats}
    faults: dict[str, list[str]] = {}
    for f in rep.faults:
        if f.shot:
            faults.setdefault(f.shot, []).append(f"{f.level}: {f.code}: {f.msg}" + (f" ({f.reason})" if f.reason else ""))
    cards = []
    for s in rec.shots:
        b = beats.get(s.beat)
        head = (f"<h2>Shot {escape(s.id)} · {escape(s.size)} {escape(s.type.replace('_', ' '))} · {s.duration_s} s"
                f" · beat {s.beat} ({b.intensity if b else '?'}) · in: {escape(s.cut_in)}</h2>")
        if s.type in ("black", "title") or w.cam(s) is None:
            text = escape(s.action)
            cards.append(f"<section>{head}<div class='frames'><div class='card black'>{text}</div></div></section>")
            continue
        c = w.cam(s)
        f = rep.facts.get(s.id, {})
        facts = " · ".join(x for x in [
            f"camera {c.id}: {c.lens_mm} mm, {c.height.replace('_', ' ')}, {s.angle}, {s.move.replace('_', ' ')}",
            f"plan says the frame is {f.get('frame_width_m', '?')} m wide ({f.get('size_from_plan', '?')})",
            ", ".join(f"{names.get(k, k)} {v}" for k, v in (f.get('sides') or {}).items()),
            escape(f.get("eyeline", "")), f"key light {f.get('key_light', '?')}"] if x)
        bad = "".join(f"<li>{escape(x)}</li>" for x in faults.get(s.id, []))
        cards.append(
            f"<section>{head}<div class='frames'>"
            f"<figure>{frame_svg(w, s, w.cuts[s.start], colour, names)}<figcaption>opens · {escape(s.start)}"
            f"</figcaption></figure>"
            f"<figure>{frame_svg(w, s, w.cuts[s.end], colour, names)}<figcaption>ends · {escape(s.end)}"
            f"{' (cut on action)' if any(n.start == s.end and n.cut_in == 'match_on_action' for n in rec.shots) else ''}"
            f"</figcaption></figure>"
            f"<figure>{plan_svg(w, s, w.cuts[s.start], colour)}<figcaption>floor plan, north up</figcaption></figure>"
            f"</div><p class='action'>{escape(s.action)}</p><p class='facts'>{facts}</p>"
            f"{'<ul class=bad>' + bad + '</ul>' if bad else ''}</section>")
    legend = " ".join(f"<span style='color:{colour[p]}'>● {escape(names.get(p, p))}</span>" for p in people)
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Plan board: {escape(rec.scene)}</title><style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}}
section{{background:white;border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin:0 0 14px}}
h1{{font-size:20px}} h2{{font-size:15px;margin:2px 0 8px}}
.frames{{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}} figure{{margin:0}}
figcaption{{font-size:11px;color:#666}} .action{{margin:6px 0 2px}} .facts{{font-size:12px;color:#555;margin:2px 0}}
.bad{{font-size:12px;color:#b03a2e;margin:4px 0}} .card.black{{width:{W}px;height:{H}px;background:#000;color:#eee;
display:flex;align-items:center;justify-content:center;text-align:center;padding:10px;box-sizing:border-box}}
</style></head><body><h1>Plan board: {escape(scene.get('title', rec.scene))}</h1>
<p>Drawn by code from the scene record: each camera's view at the shot's first and last instant (position, height,
lens), the figures on their marks with a tick for the way they face, props as white dots. Not a painting: it shows
what the PLAN says, so sides, facing, size, continuity across cuts and missing people can be checked by eye.</p>
<p>{legend} · <span>○ prop</span></p>{''.join(cards)}</body></html>"""
