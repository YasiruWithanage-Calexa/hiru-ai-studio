"""Chaining without the last frame: each clip's video prompt opens and ends on a written cut point.

Shot N's ENDS ON and shot N+1's OPENS ON are written by `world_state(cut)` from the SAME cut point record, so the
world facts (posture, what each hand holds, the prop's state, the movement under way, wardrobe, light) are the same
words on both sides of the cut. Only the frame words differ, and code derives them from the floor plan for each
camera (who is frame left, which way they face on screen, how far they are), so a reverse angle reads correctly.

The cut types tell the video model how to treat the edges:
  cut              the clip settles: the last 0.5 s holds the ENDS ON state still, a clean frame to cut on;
  match_on_action  the movement under way at the cut is NOT finished: the outgoing clip carries it overlap_out_s past
                   the cut point and the incoming clip opens overlap_in_s before it, mid-movement, so the editor cuts
                   inside the motion (the Deed's "cut 1 on movement").
The first frame of every shot is painted from the same OPENS ON words (`frame_brief`), so the picture and the clip
start from one record. No frame is carried from the clip before.
"""
from __future__ import annotations

from typing import Any

from geometry import P, World
from schema import CutPoint, SceneRecord, Shot

POSTURE = {"standing": "standing", "walking": "walking", "seated": "seated", "kneeling": "kneeling",
           "lying": "lying still", "rising": "rising from the seat", "sitting_down": "sitting down",
           "kneeling_down": "lowering onto the knees", "leaning": "leaning in", "crouching": "crouching"}


def clause(t: str) -> str:
    """A sentence as a clause: no closing full stop, first letter as written."""
    return t.strip().rstrip(".")


class Writer:
    def __init__(self, rec: SceneRecord, scene: dict[str, Any], facts: dict[str, dict[str, Any]]) -> None:
        self.rec, self.scene, self.facts, self.w = rec, scene, facts, World(rec)
        self.name = {p["id"]: p["name"] for p in scene["people"]}
        self.name |= {p["id"]: p["name"] for p in scene["props"]}
        self.name |= {lm.id: lm.name for lm in rec.landmarks}
        self.people = {p["id"]: p for p in scene["people"]}

    def n(self, ref: str) -> str:
        return self.name.get(ref, ref)

    # ── camera-independent: identical on both sides of a cut ────────────────────────────────────────────────────────
    def world_state(self, cut: CutPoint, shown: set[str] | None = None) -> str:
        """The cut point in words. `shown`: the ids a shot has in frame; a person or prop out of frame is left out,
        so a prompt never invites the model to paint them. Each person's sentence is the same in every shot that
        shows them at this cut point."""
        def low(t: str) -> str:
            t = t.strip().rstrip(".")
            first = t.split(" ", 1)[0].strip(",'s")
            return t if first in self.name.values() else t[:1].lower() + t[1:]

        def keep(ref: str) -> bool:
            return shown is None or ref in shown

        parts = []
        for p in cut.people:
            if not keep(p.who):
                continue
            bits = [f"{self.n(p.who)} is {POSTURE.get(p.posture, p.posture)}"]
            for hand, prop in (("left", p.left_hand), ("right", p.right_hand)):
                st = self.w.prop_state(prop, cut.id) if prop else None
                if prop:
                    bits.append(f"the {self.n(prop)} {low(st.place) if st else 'in the ' + hand + ' hand'}")
            if p.look_at:
                bits.append(f"eyes on {self.n(p.look_at)}")
            if p.state:
                bits.append(low(p.state))
            parts.append(", ".join(bits) + ".")
        held = {x for p in cut.people for x in (p.left_hand, p.right_hand) if x}
        for prop in sorted(self.w.props - held):
            st = self.w.prop_state(prop, cut.id)
            if st and st.seen and not st.holder and keep(prop):
                parts.append(f"The {self.n(prop)}: {low(st.place)}.")
        if cut.under_way and (shown is None or any(keep(p.who) for p in cut.people)):
            parts.append(f"Under way at this instant: {low(cut.under_way)}.")
        return " ".join(parts)

    def wardrobe(self, who: str) -> str:
        p = self.people.get(who)
        if not p:
            return ""
        look = p.get("look") or {}
        cond = p.get("condition", "")
        txt = f"{p['name']} wears exactly: {look.get('outfit', '').rstrip('.')}."
        if look.get("hair"):
            txt += f" Hair: {look['hair'].rstrip('.')}."
        if cond:
            txt += f" In this scene: {cond.rstrip('.')}."
        return txt

    # ── per camera: derived from the plan ───────────────────────────────────────────────────────────────────────────
    def frame_terms(self, shot: Shot, cut: CutPoint) -> str:
        cam = self.w.cam(shot)
        if cam is None:
            return ""
        out = []
        for p in cut.people:
            if p.who not in shot.in_frame:
                continue
            m = self.w.marks.get(p.mark)
            if m is None:
                continue
            at = self.w.mark_point(m, p.progress)
            side = self.w.side(cam, shot, at)
            dist = (at - P(cam.x, cam.y)).length()
            face_ref = p.look_at or m.facing
            face = self.w.screen_facing(cam, shot, at, self.w.facing_vector(face_ref, at, cut.id, shot.beat))
            where = {"left": "at frame left", "right": "at frame right", "centre": "at frame centre"}.get(side, side)
            out.append(f"{self.n(p.who)} {where}, {dist:.1f} m from the camera" + (f", facing {face}" if face else ""))
        return "; ".join(out) + ("." if out else "")

    def camera_line(self, shot: Shot) -> str:
        cam = self.w.cam(shot)
        if cam is None:
            return ""
        f = self.facts.get(shot.id, {})
        move = "Locked off." if shot.move == "static" else f"{shot.move.replace('_', ' ')} ({shot.move_why})."
        light = f" Key light {f['key_light']}." if f.get("key_light") else ""
        return (f"{shot.size} {shot.type.replace('_', ' ')} on {self.n(shot.subject)}, {cam.lens_mm} mm at "
                f"f/{shot.f_stop:g}, camera at {cam.height.replace('_', ' ')} height, {shot.angle} angle. {move} "
                f"Focus: {shot.focus.strip().rstrip('.')}.{light}")

    # ── outputs ────────────────────────────────────────────────────────────────────────────────────────────────────
    def frame_brief(self, shot: Shot) -> str:
        """The first frame (image model, board panel, blocking plate): the OPENS ON state, framed by this camera."""
        if shot.type in ("black", "title"):
            return f"{shot.type.upper()} CARD. {shot.action}"
        cut = self.w.cuts[shot.start]
        people = [p for p in shot.in_frame if p in self.people]
        return "\n".join(x for x in [
            f"CAMERA: {self.camera_line(shot)}",
            f"IN FRAME: {self.frame_terms(shot, cut)}",
            f"STATE: {self.world_state(cut, set(shot.in_frame))}",
            *[f"WARDROBE: {self.wardrobe(p)}" for p in people],
        ] if x.split(": ", 1)[1].strip())

    def video_prompt(self, shot: Shot, nxt: Shot | None) -> str:
        if shot.type in ("black", "title"):
            return f"{shot.type.upper()} CARD for {shot.duration_s} s. {shot.action}"
        start, end = self.w.cuts[shot.start], self.w.cuts[shot.end]
        d = float(shot.duration_s)
        t_in = shot.overlap_in_s if shot.cut_in == "match_on_action" else 0.0
        carry = nxt is not None and nxt.cut_in == "match_on_action"
        t_out = shot.overlap_out_s if carry else 0.0
        hold = 0.0 if carry else 0.5
        core_end = d - t_out - hold
        shown = set(shot.in_frame)
        lines = [f"CAMERA: {self.camera_line(shot)}",
                 f"OPENS ON (0.0 s): {self.world_state(start, shown)} {self.frame_terms(shot, start)}"]
        if shot.cut_in == "match_on_action":
            lines.append(f"0.0–{t_in:.1f} s: the movement is already under way in the first frame ({clause(start.under_way)}); "
                         "continue it without restarting it.")
        lines.append(f"{t_in:.1f}–{core_end:.1f} s: {shot.action}")
        if carry:
            lines.append(f"{core_end:.1f}–{d:.1f} s: {clause(end.under_way)}: it begins and is still moving at the last frame; "
                         "do not stop or settle.")
            lines.append(f"AT {core_end:.1f} s (the cut point): {self.world_state(end, shown)} {self.frame_terms(shot, end)}")
        else:
            lines.append(f"ENDS ON ({core_end:.1f}–{d:.1f} s, held still): {self.world_state(end, shown)} "
                         f"{self.frame_terms(shot, end)}")
        people = [p for p in shot.in_frame if p in self.people]
        keep = [self.wardrobe(p) for p in people]
        lines.append("KEEP THE SAME FROM FIRST TO LAST FRAME: " + " ".join(keep) +
                     " Nobody changes clothes, hands or props except as the action says.")
        return "\n".join(lines)


def write_all(rec: SceneRecord, scene: dict[str, Any], facts: dict[str, dict[str, Any]]) -> str:
    wr = Writer(rec, scene, facts)
    out = [f"# Prompts: {rec.scene}", ""]
    for i, s in enumerate(rec.shots):
        nxt = rec.shots[i + 1] if i + 1 < len(rec.shots) else None
        out += [f"## Shot {s.id} · beat {s.beat} · {s.size} {s.type} · {s.duration_s} s · in: {s.cut_in} "
                f"({s.start} → {s.end})", "", f"_{s.purpose}_", "", "**First frame**", "", "```",
                wr.frame_brief(s), "```", "", "**Video**", "", "```", wr.video_prompt(s, nxt), "```", ""]
    return "\n".join(out)
