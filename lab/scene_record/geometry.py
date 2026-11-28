"""Floor-plan arithmetic: where a thing is, which side of the frame it lands on, what a lens can hold.

Metres, x east, y north (a top-down plan). A camera at C looking at T has forward f = T - C. For a point P,
cross(f, P - C) > 0 means P is to the LEFT of the line of sight, so at FRAME LEFT; < 0 frame right; behind the camera
(dot < 0) it is not in frame. Horizontal field of view is a full-frame (36 mm wide) lens: 2 * atan(18 / mm).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from schema import Camera, Mark, SceneRecord, Shot

SIZES = ("EWS", "WS", "FS", "MLS", "MS", "MCU", "CU", "ECU")
RANK = {s: i for i, s in enumerate(SIZES)} | {"INSERT": 6}
# the frame width (metres, at the subject) each size reads as: a person ~0.5 m across the shoulders
WIDTH_MAX = (("ECU", 0.25), ("CU", 0.5), ("MCU", 0.9), ("MS", 1.4), ("MLS", 2.2), ("FS", 3.5), ("WS", 12.0),
             ("EWS", 1e9))
COMPASS = {"north": (0.0, 1.0), "south": (0.0, -1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0)}


@dataclass(frozen=True)
class P:
    x: float
    y: float

    def __sub__(self, o: P) -> P:
        return P(self.x - o.x, self.y - o.y)

    def __add__(self, o: P) -> P:
        return P(self.x + o.x, self.y + o.y)

    def scale(self, k: float) -> P:
        return P(self.x * k, self.y * k)

    def length(self) -> float:
        return math.hypot(self.x, self.y)


def cross(a: P, b: P) -> float:
    return a.x * b.y - a.y * b.x


def dot(a: P, b: P) -> float:
    return a.x * b.x + a.y * b.y


def angle_deg(a: P, b: P) -> float:
    la, lb = a.length(), b.length()
    if la == 0 or lb == 0:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b) / (la * lb)))))


def hfov(lens_mm: int) -> float:
    return math.degrees(2 * math.atan(18.0 / max(lens_mm, 1)))


def size_for_width(width: float) -> str:
    return next(s for s, w in WIDTH_MAX if width < w)


class World:
    """Where everything is at a shot, from the record alone."""

    def __init__(self, rec: SceneRecord) -> None:
        self.rec = rec
        self.marks = {m.id: m for m in rec.marks}
        self.cams = {c.id: c for c in rec.cameras}
        self.land = {lm.id: lm for lm in rec.landmarks}
        self.cuts = {k.id: k for k in rec.cuts}
        self.people = {m.who for m in rec.marks}
        self.props = {s.prop for s in rec.prop_states}
        self.cut_order = [s.start for s in rec.shots] + ([rec.shots[-1].end] if rec.shots else [])

    # ── positions ──────────────────────────────────────────────────────────────────────────────────────────────────
    def mark_point(self, m: Mark, progress: float = 0.0) -> P:
        start = P(m.x, m.y)
        if not m.moves_to:
            return start
        end = P(m.moves_to[0].x, m.moves_to[0].y)
        return start + (end - start).scale(progress)

    def mark_of(self, who: str, beat: int) -> Mark | None:
        """The person's mark at a beat (the latest mark at or before it)."""
        own = sorted((m for m in self.rec.marks if m.who == who and m.beat <= beat), key=lambda m: m.beat)
        return own[-1] if own else None

    def person_at(self, who: str, cut_id: str, beat: int) -> P | None:
        cut = self.cuts.get(cut_id)
        if cut:
            for p in cut.people:
                if p.who == who and p.mark in self.marks:
                    return self.mark_point(self.marks[p.mark], p.progress)
        m = self.mark_of(who, beat)
        return self.mark_point(m) if m else None

    def prop_state(self, prop: str, cut_id: str):
        """The prop's state in force at a cut point (states keyed by the cut they start at, in cut order)."""
        order = {k: i for i, k in enumerate(self.cut_order)}
        here = order.get(cut_id, -1)
        own = [s for s in self.rec.prop_states if s.prop == prop and order.get(s.from_cut, 10**6) <= here]
        own.sort(key=lambda s: order[s.from_cut])
        return own[-1] if own else None

    def point_of(self, ref: str, cut_id: str, beat: int) -> P | None:
        """A person, prop, landmark or compass word as a point (a prop is where its holder is)."""
        if ref in self.people:
            return self.person_at(ref, cut_id, beat)
        if ref in self.land:
            pts = self.land[ref].points
            if len(pts) == 1:
                return P(pts[0].x, pts[0].y)
            return P(sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))
        if ref in self.props:
            st = self.prop_state(ref, cut_id)
            if st and st.on and st.on in self.land:
                return self.point_of(st.on, cut_id, beat)
            if st and st.holder:
                return self.person_at(st.holder, cut_id, beat)
        return None

    def cam(self, shot: Shot) -> Camera | None:
        """The shot's camera: its setup, with the shot's own lens and target when it sets them."""
        c = self.cams.get(shot.camera)
        if c is None:
            return None
        update: dict[str, object] = {}
        if getattr(shot, "lens_mm", 0):
            update["lens_mm"] = shot.lens_mm
        if getattr(shot, "looks_at", ""):
            update["looks_at"] = shot.looks_at
        return c.model_copy(update=update) if update else c

    def setups(self, cluster_m: float = 0.5) -> list[list[str]]:
        """Camera ids grouped by position: cameras within `cluster_m` of each other are one setup on the floor."""
        groups: list[list[str]] = []
        anchor: list[P] = []
        for c in self.rec.cameras:
            if not any(s.camera == c.id for s in self.rec.shots):
                continue
            here = P(c.x, c.y)
            i = next((i for i, a in enumerate(anchor) if (a - here).length() < cluster_m), None)
            if i is None:
                anchor.append(here)
                groups.append([c.id])
            else:
                groups[i].append(c.id)
        return groups

    # ── a camera's view ────────────────────────────────────────────────────────────────────────────────────────────
    def forward(self, cam: Camera, shot: Shot) -> P | None:
        t = self.point_of(cam.looks_at, shot.start, shot.beat)
        if t is None:
            return None
        f = t - P(cam.x, cam.y)
        return f if f.length() > 1e-6 else None

    def side(self, cam: Camera, shot: Shot, pt: P) -> str:
        """'left' | 'right' | 'centre' | 'behind' for a point in this camera's frame."""
        f = self.forward(cam, shot)
        if f is None:
            return "unknown"
        v = pt - P(cam.x, cam.y)
        if dot(f, v) <= 0:
            return "behind"
        ang = angle_deg(f, v)
        if ang < 4:
            return "centre"
        return "left" if cross(f, v) > 0 else "right"

    def in_view(self, cam: Camera, shot: Shot, pt: P, margin: float = 0.0) -> bool:
        f = self.forward(cam, shot)
        if f is None:
            return False
        v = pt - P(cam.x, cam.y)
        return dot(f, v) > 0 and angle_deg(f, v) <= hfov(cam.lens_mm) / 2 + margin

    def frame_width(self, cam: Camera, shot: Shot) -> float | None:
        t = self.point_of(cam.looks_at, shot.start, shot.beat)
        if t is None:
            return None
        d = (t - P(cam.x, cam.y)).length()
        return d * 36.0 / max(cam.lens_mm, 1)

    def facing_vector(self, facing: str, at: P, cut_id: str, beat: int) -> P | None:
        if facing in COMPASS:
            return P(*COMPASS[facing])
        t = self.point_of(facing, cut_id, beat)
        return (t - at) if t is not None else None

    def screen_facing(self, cam: Camera, shot: Shot, who_at: P, facing: P | None) -> str:
        """How a person's facing reads in this frame: 'frame left' | 'frame right' | 'the camera' | 'away'."""
        f = self.forward(cam, shot)
        if f is None or facing is None or facing.length() == 0:
            return ""
        toward_cam = P(cam.x, cam.y) - who_at
        if angle_deg(facing, toward_cam) < 35:
            return "the camera"
        if angle_deg(facing, f) < 35:
            return "away"
        return "frame left" if cross(f, facing) > 0 else "frame right"

    def axis_for(self, beat: int):
        own = sorted((a for a in self.rec.axes if a.from_beat <= beat), key=lambda a: a.from_beat)
        return own[-1] if own else None

    def camera_side_ok(self, cam: Camera, shot: Shot) -> tuple[bool, float]:
        """(on the stated side, signed distance in metres from the axis line)."""
        ax = self.axis_for(shot.beat)
        if ax is None:
            return True, 0.0
        a = self.point_of(ax.a, shot.start, shot.beat)
        b = self.point_of(ax.b, shot.start, shot.beat)
        if a is None or b is None or (b - a).length() < 1e-6:
            return True, 0.0
        d = b - a
        normal = P(-d.y, d.x).scale(1 / d.length())  # left of a→b
        want = P(*COMPASS[ax.camera_side])
        if dot(normal, want) < 0:
            normal = normal.scale(-1)
        dist = dot(P(cam.x, cam.y) - a, normal)
        return dist > -0.05, dist
