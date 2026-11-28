"""Code checks on a scene record: the rules of "The Deed" Part 4 that code can decide, and the chain.

Every fault is BLOCKING unless its rule is one a shot may break on purpose (schema.Rule) AND that shot carries a
`breaks` entry for the rule with a reason; then it is EXPLAINED (reported, never blocking). ADVISORY faults are
reported only. A plan passes when no blocking fault is left.

Story checks come first (never invent: no person, prop or line the scene does not have), then the chain (one cut
point between every two shots, positions on marks, hands against the prop timeline), then space (180, 30 degrees,
what the lens can see, eyelines, screen direction of a walk), then size and length against intensity, wardrobe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from geometry import RANK, P, World, angle_deg, cross, size_for_width
from schema import SceneRecord, Shot

GARMENTS = ("dress", "blouse", "skirt", "shirt", "t-shirt", "sarong", "saree", "sari", "trousers", "pants", "jeans",
            "shorts", "sandals", "shoes", "slippers", "jacket", "coat", "raincoat", "hood", "cap", "hat", "kurta",
            "frock", "uniform", "belt", "scarf", "shawl", "apron", "vest", "sweater", "lungi", "cardigan", "sleeves")
COLOURS = ("ochre", "mustard", "maroon", "navy", "white", "red", "blue", "green", "black", "grey", "brown", "yellow",
           "orange", "pink", "purple", "beige", "brick")


@dataclass
class Fault:
    code: str
    msg: str
    fix: str = ""
    shot: str = ""
    level: str = "blocking"  # blocking | explained | advisory
    reason: str = ""

    def line(self) -> str:
        where = f"shot {self.shot}: " if self.shot else ""
        tail = f" Reason given: {self.reason}" if self.reason else (f" Fix: {self.fix}" if self.fix else "")
        return f"[{self.level}] {self.code}: {where}{self.msg}{tail}"


@dataclass
class Report:
    faults: list[Fault] = field(default_factory=list)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)  # shot id -> derived facts (screen sides, ...)

    @property
    def blocking(self) -> list[Fault]:
        return [f for f in self.faults if f.level == "blocking"]

    def by_level(self, level: str) -> list[Fault]:
        return [f for f in self.faults if f.level == level]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z\-]*", (text or "").lower()))


class Checker:
    def __init__(self, rec: SceneRecord, scene: dict[str, Any]) -> None:
        self.rec, self.scene, self.w = rec, scene, World(rec)
        self.r = Report()
        self.shots = rec.shots
        self.people = {p["id"] for p in scene["people"]}
        self.names = {p["id"]: p["name"] for p in scene["people"]}
        self.props = {p["id"]: p["name"] for p in scene["props"]}
        self.lines = {b["line_id"]: b for b in scene["blocks"] if b.get("line_id")}

    # ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────────
    def add(self, code: str, msg: str, fix: str = "", shot: Shot | None = None, rule: str = "",
            level: str = "blocking") -> None:
        reason = ""
        if shot is not None and rule:
            reason = next((b.reason for b in shot.breaks if b.rule == rule and b.reason.strip()), "")
        if reason:
            level = "explained"
        self.r.faults.append(Fault(code, msg, fix, shot.id if shot else "", level, reason))

    def is_person(self, ref: str) -> bool:
        return ref in self.people

    # ── story: never invent ────────────────────────────────────────────────────────────────────────────────────────
    def story(self) -> None:
        for m in self.rec.marks:
            if m.who not in self.people:
                self.add("story:person", f"mark {m.id} is for '{m.who}', who is not in this scene.",
                         "use only the scene's people ids")
        for s in self.rec.prop_states:
            if s.prop not in self.props:
                self.add("story:prop", f"prop '{s.prop}' is not one of the scene's props.",
                         "use only the scene's props ids")
        blocks = [b["n"] for b in self.scene["blocks"]]
        seen = [n for bt in sorted(self.rec.beats, key=lambda b: b.n) for n in bt.blocks]
        if seen != blocks:
            self.add("story:beats", f"the beats cover blocks {seen}; the script has {blocks}, each once, in order.",
                     "give every block to exactly one beat, in script order")
        shown = {n for s in self.shots for n in s.blocks}
        for n in blocks:
            if n not in shown:
                self.add("story:block", f"block {n} is in no shot.", "cover it, or fold it into a shot that is there")
        for lid, b in self.lines.items():
            shots = [s for s in self.shots if lid in s.lines]
            if not shots:
                self.add("story:line", f"line {lid} is said in no shot.", "give it to a shot")
            speaker = next((pid for pid, n in self.names.items() if n == b.get("speaker")), "")
            for s in shots:
                if speaker and speaker not in s.in_frame:
                    self.add("story:line_unseen", f"line {lid} is said by {b.get('speaker')}, who is not in frame.",
                             "put the speaker in frame for the shot that holds the line", s, level="advisory")
        for s in self.shots:
            for lid in s.lines:
                if lid not in self.lines:
                    self.add("story:line_id", f"line '{lid}' is not a line of this scene.", "use the line ids given", s)

    # ── the chain ──────────────────────────────────────────────────────────────────────────────────────────────────
    def chain(self) -> None:
        cuts = self.w.cuts
        if not self.shots:
            self.add("chain:none", "the record has no shots.")
            return
        first = self.shots[0]
        if first.start != "K0" or first.cut_in != "first":
            self.add("chain:first", "the first shot opens on K0 with cut_in 'first'.", "set start K0, cut_in first",
                     first)
        for a, b in pairwise(self.shots):
            if b.start != a.end:
                self.add("chain:link", f"shot {a.id} ends on {a.end} but shot {b.id} opens on {b.start}.",
                         "the next shot opens on the cut point the shot before ends on", b)
            if b.cut_in == "first":
                self.add("chain:first", "only the first shot has cut_in 'first'.", "use cut or match_on_action", b)
            if b.cut_in == "match_on_action":
                k = cuts.get(b.start)
                if k is None or not k.under_way.strip():
                    self.add("chain:action", f"a match on action at {b.start} needs the movement under way there.",
                             "write the cut point's under_way", b)
                if a.overlap_out_s < 0.5 or b.overlap_in_s < 0.5:
                    self.add("chain:overlap", f"the movement across {b.start} must be covered by both shots "
                             f"(overlap_out {a.overlap_out_s}s on {a.id}, overlap_in {b.overlap_in_s}s on {b.id}).",
                             "give both shots at least 0.5 s of the movement past the cut", b)
        used = [self.shots[0].start] + [s.end for s in self.shots]
        for k in used:
            if k not in cuts:
                self.add("chain:cut", f"cut point {k} is used but not written.", "write it")
        for s in self.shots:
            for kid in (s.start, s.end):
                k = cuts.get(kid)
                if k is None:
                    continue
                listed = {p.who for p in k.people}
                for ref in s.in_frame:
                    if self.is_person(ref) and ref not in listed:
                        self.add("chain:missing", f"{ref} is in frame but has no state at {kid}.",
                                 "list every on-screen person at both cut points of the shot", s)
        for k in self.rec.cuts:
            for p in k.people:
                m = self.w.marks.get(p.mark)
                if m is None:
                    self.add("chain:mark", f"{p.who} at {k.id} stands on mark '{p.mark}', which does not exist.",
                             "use a mark id from marks")
                elif m.who != p.who:
                    self.add("chain:mark", f"{p.who} at {k.id} is put on {m.who}'s mark {m.id}.", "use their own mark")
                elif p.progress > 0 and not m.moves_to:
                    self.add("chain:progress", f"{p.who} at {k.id} has progress {p.progress} on mark {m.id}, "
                             "which does not move.", "progress 0, or give the mark its moves_to")

    # ── props ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def props_check(self) -> None:
        for k in self.rec.cuts:
            held: dict[str, str] = {}
            for p in k.people:
                for hand, prop in (("left", p.left_hand), ("right", p.right_hand)):
                    if not prop:
                        continue
                    if prop in held and held[prop] != p.who:
                        self.add("prop:two", f"{prop} is in {held[prop]}'s and {p.who}'s hands at {k.id}.")
                    held[prop] = p.who
                    st = self.w.prop_state(prop, k.id)
                    if st is None:
                        self.add("prop:state", f"{p.who} holds {prop} at {k.id} but it has no state yet.",
                                 "start its state at or before this cut point")
                    elif st.holder != p.who or (st.hand not in (hand, "both")):
                        self.add("prop:hand", f"at {k.id} {p.who}'s {hand} hand holds {prop}, but its state there is "
                                 f"'{st.place}' (holder {st.holder or 'nobody'}, hand {st.hand or 'none'}).",
                                 "make the hands and the prop timeline agree")
            for prop in self.props:
                st = self.w.prop_state(prop, k.id)
                if st and st.holder and st.hand in ("left", "right"):
                    who = next((p for p in k.people if p.who == st.holder), None)
                    if who is not None and getattr(who, f"{st.hand}_hand") != prop:
                        self.add("prop:hand", f"at {k.id} {prop} should be in {st.holder}'s {st.hand} hand "
                                 f"('{st.place}') but that hand holds '{getattr(who, f'{st.hand}_hand') or 'nothing'}'.",
                                 "make the hands and the prop timeline agree")
        for s in self.shots:
            for ref in s.in_frame:
                if ref in self.props:
                    st = self.w.prop_state(ref, s.start)
                    if st is not None and not st.seen:
                        self.add("prop:early", f"{ref} is in frame before the story shows it ('{st.place}').",
                                 "keep it out of frame until its state is seen", s)

    # ── space ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def space(self) -> None:
        w = self.w
        prev: Shot | None = None
        for s in self.shots:
            cam = w.cam(s)
            facts: dict[str, Any] = {}
            self.r.facts[s.id] = facts
            if s.type in ("black", "title"):
                prev = None
                continue
            if cam is None:
                self.add("space:camera", f"camera '{s.camera}' does not exist.", "use a camera id", s)
                prev = None
                continue
            if w.forward(cam, s) is None:
                self.add("space:looks_at", f"camera {cam.id} looks at '{cam.looks_at}', which has no place here.",
                         "look at a person, landmark or held prop", s)
                prev = None
                continue
            ok, dist = w.camera_side_ok(cam, s)
            facts["axis_m"] = round(dist, 2)
            if not ok:
                ax = w.axis_for(s.beat)
                self.add("180", f"camera {cam.id} is {abs(dist):.1f} m on the wrong side of the {ax.a}–{ax.b} axis "
                         f"(the scene keeps cameras {ax.camera_side} of it).",
                         "move the camera back across the line, or plan a legal crossing and say so", s, "180")
            # who is where in this frame
            sides: dict[str, str] = {}
            for ref in sorted(w.people | w.props):
                pt = w.point_of(ref, s.start, s.beat)
                if pt is None:
                    continue
                side = w.side(cam, s, pt)
                visible = w.in_view(cam, s, pt, margin=8)
                if ref in s.in_frame:
                    sides[ref] = side
                    if not visible:
                        self.add("frame:out", f"{ref} is listed in frame but camera {cam.id} ({cam.lens_mm} mm) does "
                                 f"not see that spot ({side}).", "aim the camera, change the lens, or take them out", s)
                elif ref in w.people and w.in_view(cam, s, pt) and (pt - P(cam.x, cam.y)).length() < 10:
                    self.add("frame_missing", f"{ref} is on their mark inside camera {cam.id}'s view but not in frame.",
                             "list them in in_frame, move the camera, or give a reason (cropped below frame)", s,
                             "frame_missing")
            facts["sides"] = sides
            for ref in s.in_frame:
                if self.is_person(ref) and w.mark_of(ref, s.beat) is None:
                    self.add("place:unmarked", f"{ref} is in frame but has no mark at beat {s.beat}.",
                             "give every on-screen person a mark, lying people too", s)
            # size vs what the lens and distance can hold
            width = w.frame_width(cam, s)
            if width is not None:
                facts["frame_width_m"] = round(width, 2)
                geo = size_for_width(width)
                facts["size_from_plan"] = geo
                if s.size == "INSERT":
                    if width > 0.9:
                        self.add("size_geometry", f"an INSERT, but camera {cam.id} frames {width:.1f} m at the subject.",
                                 "move closer or use a longer lens", s, "size_geometry")
                elif abs(RANK[s.size] - RANK[geo]) > 1:
                    self.add("size_geometry", f"called {s.size}, but {cam.lens_mm} mm from this distance frames "
                             f"{width:.1f} m at the subject, which reads as {geo}.",
                             "move the camera, change the lens, or change the size", s, "size_geometry")
            # 30 degrees / size step against the shot before on the same subject
            if prev is not None and prev.subject == s.subject and s.type not in ("insert",):
                pc, sp = w.cam(prev), w.point_of(s.subject, s.start, s.beat)
                if pc is not None and sp is not None:
                    turn = angle_deg(P(pc.x, pc.y) - sp, P(cam.x, cam.y) - sp)
                    step = abs(RANK[s.size] - RANK[prev.size])
                    facts["turn_from_prev_deg"] = round(turn)
                    if turn < 30 and step < 1:
                        self.add("30_degree", f"same subject as shot {prev.id}, turned only {turn:.0f}° and the same "
                                 f"size: a jump cut.", "move the camera 30° or more, or change the size a step", s,
                                 "30_degree")
            # walking: screen direction and the path it follows
            k = w.cuts.get(s.start)
            for p in k.people if k else []:
                m = w.marks.get(p.mark)
                if m is None or not m.moves_to or p.who not in s.in_frame:
                    continue
                move = P(m.moves_to[0].x - m.x, m.moves_to[0].y - m.y)
                f = w.forward(cam, s)
                direction = "towards the camera" if f and angle_deg(f, move) > 145 else \
                    "away from the camera" if f and angle_deg(f, move) < 35 else \
                    ("to frame left" if f and cross(f, move) > 0 else "to frame right")
                facts.setdefault("travel", {})[p.who] = direction
                if m.along and m.along in w.land:
                    pts = w.land[m.along].points
                    if len(pts) >= 2:
                        best = min(min(angle_deg(move, P(b.x - a.x, b.y - a.y)), 180 - angle_deg(
                            move, P(b.x - a.x, b.y - a.y))) for a, b in pairwise(pts))
                        if best > 30:
                            self.add("move:off_path", f"{p.who} walks {best:.0f}° off the line of '{m.along}' "
                                     "that the mark says they follow.", "move moves_to along the path", s)
            prev = s
        self._directions()
        self._eyelines()

    def _directions(self) -> None:
        last: dict[str, tuple[str, str]] = {}
        for s in self.shots:
            for who, d in (self.r.facts.get(s.id, {}).get("travel") or {}).items():
                if who in last and d.startswith("to frame") and last[who][1].startswith("to frame") \
                        and d != last[who][1]:
                    self.add("screen_direction", f"{who} travels {last[who][1]} in shot {last[who][0]} and {d} here.",
                             "keep one direction of travel across the cut, or show the turn", s, "screen_direction")
                last[who] = (s.id, d)

    def _eyelines(self) -> None:
        """A single of A looking at B, then of B looking at A: the two looks must point opposite ways on screen."""
        w = self.w
        looks: dict[str, tuple[str, str, str]] = {}  # shot -> (who, at, side of the target in that frame)
        for s in self.shots:
            cam, k = w.cam(s), w.cuts.get(s.start)
            if cam is None or k is None or not self.is_person(s.subject):
                continue
            me = next((p for p in k.people if p.who == s.subject), None)
            if me is None or not me.look_at:
                continue
            tgt = w.point_of(me.look_at, s.start, s.beat)
            if tgt is None:
                continue
            side = w.side(cam, s, tgt)
            if side == "behind":  # the target is behind the camera: the look reads off the side it leans to
                f = w.forward(cam, s)
                side = "left" if f and cross(f, tgt - P(cam.x, cam.y)) > 0 else "right"
            looks[s.id] = (s.subject, me.look_at, side)
            self.r.facts.setdefault(s.id, {})["eyeline"] = f"{s.subject} looks {side} of frame at {me.look_at}"
        ids = [s.id for s in self.shots]
        for a, b in pairwise(ids):
            if a in looks and b in looks:
                wa, ta, sa = looks[a]
                wb, tb, sb = looks[b]
                if wa == tb and wb == ta and sa == sb and sa in ("left", "right"):
                    shot = next(s for s in self.shots if s.id == b)
                    self.add("eyeline", f"{wa} looks {sa} in shot {a} and {wb} looks {sb} in shot {b}: they do not "
                             "meet.", "keep both cameras on one side of the axis", shot, "eyeline")

    # ── size and length follow intensity ───────────────────────────────────────────────────────────────────────────
    def intensity(self) -> None:
        beats = {b.n: b for b in self.rec.beats}
        if not beats:
            return
        peak = max(b.intensity for b in beats.values())
        shown = {s.beat for s in self.shots if s.type not in ("black", "title")}  # a black card is not a calm beat
        low = min((b.intensity for b in beats.values() if b.n in shown), default=peak)
        cams = [s for s in self.shots if s.type not in ("black", "title")]
        top = [s for s in cams if s.beat in beats and beats[s.beat].intensity == peak]
        if top and not any(s.size == "INSERT" or RANK[s.size] >= RANK["MCU"] for s in top):
            self.add("size_intensity", f"the peak beat (intensity {peak}) has no shot at MCU or tighter.",
                     "tighten a shot in the peak beat, or say why it stays wide", top[0], "size_intensity")
        for s in cams:
            b = beats.get(s.beat)
            if b and b.intensity <= 3 and s.size in ("CU", "ECU"):
                self.add("size_intensity", f"a {s.size} in a calm beat (intensity {b.intensity}).",
                         "widen it, or say why the calm beat needs it", s, "size_intensity")
        if peak > low:
            calm = [s for s in cams if beats.get(s.beat) and beats[s.beat].intensity == low]
            if top and calm:
                mt = sum(s.duration_s for s in top) / len(top)
                mc = sum(s.duration_s for s in calm) / len(calm)
                if mt > mc:
                    self.add("length_intensity", f"peak-beat shots average {mt:.1f} s, calm-beat shots {mc:.1f} s: "
                             "the peak should cut faster.", "shorten the peak shots, or say why they hold",
                             top[0], "length_intensity")
        for a, b in pairwise(cams):
            if "INSERT" in (a.size, b.size):
                continue
            if abs(RANK[a.size] - RANK[b.size]) >= 5:
                self.add("progression", f"{a.size} straight to {b.size}.", "step through a middle size, or say why "
                         "the leap is the point", b, "progression")
        first = cams[0] if cams else None
        if first and first.size not in ("EWS", "WS", "FS") and first.type != "master":
            self.add("establish", "the scene opens without showing the space.", "open on a master, or say why", first,
                     "establish")
        km = self.rec.key_moment
        if not km.shots:
            self.add("key_moment", "no shot delivers the key moment.", "name the shots that deliver it")
        for sid in km.shots:
            s = next((x for x in self.shots if x.id == sid), None)
            if s is None:
                self.add("key_moment", f"key moment shot {sid} does not exist.")
            elif not (s.size == "INSERT" or RANK[s.size] >= RANK["MCU"] or s.move != "static"):
                self.add("key_moment", f"key moment shot {sid} is a static {s.size}: give it the strongest shot.",
                         "tighter, a move, or held longer", s, level="advisory")
        if km.beat in beats and beats[km.beat].intensity != peak:
            self.add("key_moment", f"the key moment is in beat {km.beat}, not the peak beat.", level="advisory")

    # ── wardrobe comes from the look, never from the plan ─────────────────────────────────────────────────────────
    def wardrobe(self) -> None:
        allowed: set[str] = set()
        for p in self.scene["people"]:
            look = p.get("look") or {}
            allowed |= _words(" ".join(str(v) for v in look.values()) + " " + p.get("condition", ""))
        texts: list[tuple[str, Shot | None]] = [(b.what, None) for b in self.rec.beats]
        texts += [(s.action + " " + s.purpose, s) for s in self.shots]
        texts += [(k.moment + " " + " ".join(p.state for p in k.people), None) for k in self.rec.cuts]
        for text, shot in texts:
            ws = _words(text)
            for g in GARMENTS:
                # "uniform" is clothing only as a noun: "a uniform black image" is not a garment
                if g == "uniform" and not re.search(r"\buniforms?\b(?!\s+(?:black|grey|gray|white|colou?r|light|"
                                                    r"image|frame|field|surface|texture|rain|pace|dark))",
                                                    text.lower()):
                    continue
                if g in ws and g not in allowed:
                    self.add("wardrobe:invented", f"'{g}' is named, and no look in this scene has it: "
                             f"\"{text[:90]}\"", "never describe clothes; code adds each person's look", shot)
            low = text.lower()
            for c in COLOURS:
                for g in GARMENTS:
                    if re.search(rf"\b{c}\s+(?:\w+\s+)?{g}\b", low) and not re.search(rf"\b{c}\b", " ".join(allowed)):
                        self.add("wardrobe:colour", f"'{c} … {g}' is not the look's colour.",
                                 "never describe clothes", shot)

    def faces(self) -> None:
        """A single, MCU, CU or ECU on a person must see their face: the way they face (their look_at, else their
        mark's facing) may not point away from the camera at the shot's first or last instant."""
        w = self.w
        for s in self.shots:
            cam = w.cam(s)
            if cam is None or not self.is_person(s.subject) or s.type == "pov" or \
                    s.size not in ("MS", "MCU", "CU", "ECU") or w.forward(cam, s) is None:
                continue
            for kid in (s.start, s.end):
                k = w.cuts.get(kid)
                me = next((p for p in k.people if p.who == s.subject), None) if k else None
                m = w.marks.get(me.mark) if me else None
                if me is None or m is None:
                    continue
                at = w.mark_point(m, me.progress)
                face = w.screen_facing(cam, s, at, w.facing_vector(me.look_at or m.facing, at, kid, s.beat))
                if face == "away":
                    self.add("face_hidden", f"a {s.size} on {s.subject}, who at {kid} faces away from camera "
                             f"{cam.id} (looking at {me.look_at or m.facing}): the shot sees the back of the head.",
                             "put the camera where it sees the face (in front of their eyeline, still on the axis "
                             "side), or say why the back is the point", s, "face_hidden")
                    break

    def words(self) -> None:
        """Words that reach a picture or video model carry no plan numbers: no 'x 0.28, y 0.32', no metres."""
        pat = re.compile(r"\b[xy]\s*[=:]?\s*-?\d+(\.\d+)?\b|\b\d+(\.\d+)?\s*(m|metres|meters)\b", re.I)
        texts = [(f"prop state {p.prop} at {p.from_cut}", p.place) for p in self.rec.prop_states]
        texts += [(f"cut {k.id}", k.moment + " " + k.under_way + " " + " ".join(p.state for p in k.people))
                  for k in self.rec.cuts]
        texts += [(f"shot {s.id}", s.action) for s in self.shots]
        for where, text in texts:
            if pat.search(text or ""):
                self.add("words:numbers", f"{where} writes plan numbers into prompt words: \"{text[:90]}\"",
                         "say it in words (beside her left knee, at the waterline); positions belong in the plan")

    def setups(self) -> None:
        """A crew works in SETUPS: a few positions, several shots from each. More positions than about one for every
        two to three shots is a plan that moves and relights for every shot (the canal's 11 cameras for 11 shots)."""
        import math
        painted = [s for s in self.shots if s.camera and s.type not in ("black", "title")]
        # a detail or insert position is cheap (no relight of the people): only setups that film people count
        groups = [g for g in self.w.setups(cluster_m=0.15) if any(s.camera in g and s.size != "INSERT" and s.type != "insert"
                                                    for s in painted)]
        limit = max(4, math.ceil(len(painted) / 2))
        self.r.facts.setdefault("_scene", {})["setups"] = [", ".join(g) for g in groups]
        if len(groups) > limit:
            first = next((s for s in painted if any(b.rule == "setups" for b in s.breaks)), painted[0] if painted
                         else None)
            self.add("setups", f"{len(groups)} camera positions on the people for {len(painted)} shots (at most {limit}): a crew "
                     "would move and relight for almost every shot.",
                     "plan a few setups (master, side, reaction or OTS, reverse, detail) and take several shots from "
                     "each with a different lens or a pan (shot lens_mm / looks_at)", first, "setups")

    def access(self) -> None:
        """A camera standing in water is possible (waded in, on a platform) but a crew must plan it: say so."""
        def inside(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
            hit = False
            for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    hit = not hit
            return hit

        water = [[(q.x, q.y) for q in lm.points] for lm in self.rec.landmarks
                 if lm.kind == "water" and len(lm.points) >= 3]
        for c in self.rec.cameras:
            if any(s.camera == c.id for s in self.shots) and any(inside(c.x, c.y, w) for w in water):
                self.add("access:water", f"setup {c.id} ({c.role}) stands in the water.",
                         "plan the access (waders, a platform, a boat) or move it to the bank", level="advisory")

    def light(self) -> None:
        if self.rec.light.key not in self.w.land:
            self.add("light:key", f"the key light's source '{self.rec.light.key}' is not a landmark.",
                     "add the window, lamp or sky as a landmark")
        if len(self.rec.light.by_beat) != len(self.rec.beats):
            self.add("light:beats", "light.by_beat needs one entry per beat.", level="advisory")

    def run(self) -> Report:
        self.story()
        self.chain()
        self.props_check()
        self.space()
        self.intensity()
        self.wardrobe()
        self.faces()
        self.words()
        self.setups()
        self.access()
        self.light()
        # light side, per shot (a fact, not a check)
        key = self.rec.light.key
        for s in self.shots:
            cam = self.w.cam(s)
            if cam is None or key not in self.w.land:
                continue
            pt = self.w.point_of(key, s.start, s.beat)
            if pt is not None and self.w.forward(cam, s) is not None:
                side = self.w.side(cam, s, pt)
                self.r.facts.setdefault(s.id, {})["key_light"] = {
                    "left": "from frame left", "right": "from frame right", "centre": "from behind the subject",
                    "behind": "from behind the camera"}.get(side, side)
        return self.r


def check(rec: SceneRecord, scene: dict[str, Any]) -> Report:
    return Checker(rec, scene).run()
