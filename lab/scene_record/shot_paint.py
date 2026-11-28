"""One picture per shot, painted from the MASTER FLOOR PLAN: the plan is the reference, the prompt is the guide.

    .venv/Scripts/python.exe lab/scene_record/shot_paint.py --run 005_canal_sol --scene canal             free
    .venv/Scripts/python.exe lab/scene_record/shot_paint.py --run 005_canal_sol --scene canal --only 2,5 --yes   PAID

The person's design (2026-11-28): one master floor plan with the blocking (the place from above, every person's
positions numbered in story order, the walks, every camera setup C1, C2 ...), attached to EVERY shot's image prompt.
For each shot the plan marks THIS shot's camera (a large yellow triangle and the wedge its lens sees) and rings where
each person is at this shot's instant; the prompt is a guide to reading the plan plus this shot's camera, framing,
blocking, eyeline, props and light, so the picture follows the plan's camera angle and framing. Mannequins and white
clay props (a storyboard frame, the product's board rules), one 16:9 picture per shot, quality medium.

Writes runs/<run>/shots/: plan_<shot>.png (the reference), prompt_<shot>.txt, shot_<shot>.jpg (when painted) and
shots.html (plan, painting and prompt side by side). The canal also attaches its location views sheet (GET only).
"""
from __future__ import annotations

import argparse
import json
import subprocess
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

from board_paint import HEX, views_ref  # noqa: E402
from chain import POSTURE, Writer  # noqa: E402
from checks import check  # noqa: E402
from geometry import P, World  # noqa: E402
from plan_view import Plan  # noqa: E402
from schema import SceneRecord, Shot  # noqa: E402

from contracts import board as kit  # noqa: E402
from contracts import safe_depiction  # noqa: E402

MODEL, QUALITY, CAP_USD = "gpt-image-2", "medium", 1.50
PRICE = {"text_in": 5.00, "image_in": 8.00, "out": 30.00}
LEDGER = HERE / "runs" / "shot_paint_ledger.json"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
YELLOW = "#ffd23f"

FRAMING = {
    "EWS": "an extreme wide shot: the whole place, the people tiny within it",
    "WS": "a wide shot: the place around them, every person full length and small in the frame",
    "FS": "a full shot: each person's whole body, head to feet (or the whole kneeling or lying body), fills most of "
          "the frame's height",
    "MLS": "a medium long shot: from the knees up",
    "MS": "a medium shot: from the waist up; the frame cuts at the waist",
    "MCU": "a medium close-up: head and chest only; the frame cuts at mid-chest",
    "CU": "a close-up: the face fills the frame; the frame cuts at the shoulders",
    "ECU": "an extreme close-up: only the eyes, or one small detail, fills the frame",
    "INSERT": "an insert: the object (and the hand holding it) fills the frame, nothing else",
}
GUIDE = ("How to read image 1, the MASTER FLOOR PLAN of this scene seen from above (north is up), the same plan for "
         "every shot of the scene: the place is drawn flat, blue for water, brown for earth and paths, green for "
         "fields, grey for concrete or stone, with their names. Each round pin is a person at one moment of the "
         "scene, in that person's mannequin colour, labelled with their initial and a number in story order (A1, A2 "
         "...); an orange dashed line is a walk. Each triangle is a camera position labelled C1, C2 ..., "
         "pointing the way it looks, with a blue dashed arrow to what it films. The words below say which camera THIS "
         "shot is from and where each person is on the plan at this instant. Paint what that camera sees from where "
         "it stands: the people, things and place in front of it, on the same sides of the frame as the plan puts "
         "them, near things large and far things small. Never draw the plan, its pins, triangles, arrows, lines or "
         "any of its words in the picture.")


def inside(pt: P, poly: list[P]) -> bool:
    hit = False
    for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
        if (a.y > pt.y) != (b.y > pt.y) and pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x:
            hit = not hit
    return hit


def near_line(pt: P, line: list[P], width: float) -> bool:
    for a, b in pairwise(line):
        d = b - a
        L2 = d.x * d.x + d.y * d.y
        if L2 == 0:
            continue
        k = max(0.0, min(1.0, ((pt.x - a.x) * d.x + (pt.y - a.y) * d.y) / L2))
        if (pt - (a + d.scale(k))).length() <= width / 2:
            return True
    return False


def spent() -> float:
    return sum(r["usd"] for r in json.loads(LEDGER.read_text())) if LEDGER.exists() else 0.0


class ShotPlans:
    def __init__(self, rec: SceneRecord, scene: dict[str, Any]) -> None:
        self.rec, self.scene = rec, scene
        self.rep = check(rec, scene)
        self.w = World(rec)
        names = [p["name"] for p in scene["people"]]
        self.colours = kit.colours_for(names)  # name -> colour word, as the product's board
        self.hex = {p["id"]: HEX[self.colours[p["name"]]] for p in scene["people"]}
        self.word = {p["id"]: self.colours[p["name"]] for p in scene["people"]}
        self.name = {p["id"]: p["name"] for p in scene["people"]} | {p["id"]: p["name"] for p in scene["props"]}
        self.name |= {lm.id: lm.name for lm in rec.landmarks}
        self.writer = Writer(rec, scene, self.rep.facts)

    def n(self, ref: str) -> str:
        name = self.name.get(ref, ref)
        return name if ref in self.hex else "the " + name[:1].lower() + name[1:]

    # ── the reference: the master plan with this shot's camera and instant marked ───────────────────────────────
    def master_svg(self) -> tuple[str, float, float]:
        """The master floor plan: the sheet's drawing (sheet.py), the same picture for every shot and the board."""
        from simple import Simple
        sh = Simple(self.rec, self.scene)
        return sh.drawing(), sh.W, sh.H

    def pin_of(self, who: str, pos: dict[str, Any]) -> str:
        return self.pins.get((who, id(pos)), "?")

    def number_pins(self) -> None:
        """Each person's positions numbered in story order (A1, A2 ...); a mark id -> its pin label."""
        pl = Plan(self.rec, self.scene, self.rep)
        self.pins: dict[tuple[str, int], str] = {}
        self.mark_pin: dict[str, str] = {}
        self.end_pin: dict[str, str] = {}  # a walking mark -> the pin where its walk ends
        initials = {p["id"]: p["name"][:1].upper() for p in self.scene["people"]}
        self.positions = pl.positions()
        for who, seq in self.positions.items():
            for i, pos in enumerate(seq):
                label = f"{initials.get(who, '?')}{i + 1}"
                self.pins[(who, id(pos))] = label
                if pos["mark"] is not None:
                    self.mark_pin.setdefault(pos["mark"].id, label)
            for i, pos in enumerate(seq):
                m = pos["mark"]
                if m is not None and m.moves_to and i + 1 < len(seq):
                    self.end_pin[m.id] = self.pins[(who, id(seq[i + 1]))]
        for m in self.rec.marks:  # a repeated mark on the same spot carries the pin of the first one there
            if m.id not in self.mark_pin:
                seq = self.positions.get(m.who, [])
                near = next((pos for pos in seq if (pos["at"] - P(m.x, m.y)).length() < 0.3), None)
                if near is not None:
                    self.mark_pin[m.id] = self.pins[(m.who, id(near))]

    def pin_now(self, p: Any) -> str:
        """Where a person is on the plan at a cut point: their pin, the end pin of a finished walk, or between two."""
        m = self.w.marks.get(p.mark)
        if m is None:
            return ""
        pin = self.mark_pin.get(m.id, "")
        if m.moves_to and m.id in self.end_pin:
            if p.progress >= 1:
                return self.end_pin[m.id]
            if p.progress > 0:
                return f"between {pin} and {self.end_pin[m.id]}"
        return pin

    def master_png(self, out: Path) -> bytes:
        svg, wd, ht = self.master_svg()
        page = out / "master_plan.html"
        page.write_text(f"<!doctype html><body style='margin:0;background:#15171a'>{svg}</body>", encoding="utf-8")
        png = out / "master_plan.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",  # noqa: S603
                        f"--window-size={int(wd)},{int(ht)}", f"--screenshot={png}", page.as_uri()],
                       check=True, capture_output=True, timeout=60)
        page.unlink()
        return png.read_bytes()

    # ── the guide: this shot's camera, framing, blocking, eyeline ─────────────────────────────────────────────────
    def layout(self, shot: Shot) -> str:
        """How the place lies in this camera's frame, worked out from the floor plan (never from a picture)."""
        w = self.w
        cam = w.cam(shot)
        if cam is None:
            return ""
        c = P(cam.x, cam.y)
        f = w.forward(cam, shot)
        target = w.point_of(cam.looks_at, shot.start, shot.beat)
        if f is None or target is None:
            return ""
        u = f.scale(1 / f.length())

        def nm(lm: Any) -> str:
            return lm.name[:1].lower() + lm.name[1:]

        areas = [(lm, [P(q.x, q.y) for q in lm.points]) for lm in self.rec.landmarks
                 if lm.kind in ("water", "area") and len(lm.points) >= 3]
        paths = [(lm, [P(q.x, q.y) for q in lm.points]) for lm in self.rec.landmarks
                 if lm.kind == "path" and len(lm.points) >= 2]

        def where(pt: P) -> str:
            for lm, line in paths:
                if near_line(pt, line, lm.width or 1.2):
                    return nm(lm)
            hits = [lm for lm, poly in areas if inside(pt, poly)]
            return nm(hits[-1]) if hits else ""

        out = []
        on = where(c)
        if on:
            out.append(f"The camera stands on the {on}.")
        if shot.size in ("MCU", "CU", "ECU", "INSERT"):  # a close frame shows no foreground and no lie of the land
            return "Frame layout from the floor plan: " + " ".join(out) if out else ""
        crossed: list[str] = []
        steps = max(2, int((target - c).length() / 0.25))
        for i in range(1, steps):
            here = where(c + (target - c).scale(i / steps))
            if here and here != on and here not in crossed:
                crossed.append(here)
        if crossed:
            out.append(f"Between the camera and {self.n(cam.looks_at)} lie the {', then the '.join(crossed)}: "
                       f"the {crossed[0]} fills the foreground.")
        from geometry import angle_deg, cross
        for lm, line in paths + [(lm, poly) for lm, poly in areas if lm.kind == "water"]:
            seen = [q for q in line if w.in_view(cam, shot, q, margin=10)]
            if not seen and not any(w.in_view(cam, shot, a + (b - a).scale(k / 8), margin=10)
                                    for a, b in pairwise(line) for k in range(9)):
                continue
            a, b = line[0], line[-1]
            if lm.kind == "water":  # a water area: its long side
                sides = [(q2 - q1) for q1, q2 in zip(line, line[1:] + line[:1], strict=True)]
                d = max(sides, key=lambda v: v.length())
            else:
                d = b - a
            ang = angle_deg(u, d)
            ang = min(ang, 180 - ang)
            if ang > 60:
                how = "runs across the frame from side to side"
            elif ang < 25:
                how = "runs straight away from the camera into the distance"
            else:
                how = f"runs away diagonally toward frame {'left' if cross(u, d if angle_deg(u, d) < 90 else d.scale(-1)) > 0 else 'right'}"
            out.append(f"The {nm(lm)} {how}.")
        for lm in self.rec.landmarks:
            if lm.kind not in ("fixed", "furniture", "door") or len(lm.points) != 1:
                continue
            q = P(lm.points[0].x, lm.points[0].y)
            if not w.in_view(cam, shot, q, margin=4):
                continue
            side = w.side(cam, shot, q)
            dist = (q - c).length()
            far = "near the camera" if dist < 3 else "in the middle distance" if dist < 10 else "far off"
            out.append(f"The {nm(lm)} is at frame {side}, {far}.")
        travel = (self.rep.facts.get(shot.id, {}) or {}).get("travel") or {}
        for who, d in travel.items():
            out.append(f"{self.name.get(who, who)} walks {d}.")
        return "Frame layout from the floor plan: " + " ".join(out) if out else ""

    def prompt(self, shot: Shot, views: bool) -> str:
        w, rec = self.w, self.rec
        cam = w.cam(shot)
        assert cam is not None
        setup = w.cams[shot.camera]
        cut = w.cuts[shot.start]
        target = w.point_of(cam.looks_at, shot.start, shot.beat)
        dist = (target - P(cam.x, cam.y)).length() if target else 0.0
        facts = self.rep.facts.get(shot.id, {})
        move = "The camera does not move." if shot.move == "static" else \
            f"The camera {shot.move.replace('_', ' ')}s ({shot.move_why}); paint its first instant."
        aim = self.n(cam.looks_at)
        aim_pin = next((self.pin_now(p) for p in cut.people if p.who == cam.looks_at), "")
        camera = (f"THIS SHOT is from camera {setup.id} on the master floor plan (the triangle labelled {setup.id}, "
                  f"the {setup.role} setup): the camera stands there at {cam.height.replace('_', ' ')} height and "
                  f"looks toward {aim}" + (f" (pin {aim_pin})" if aim_pin else "") + f", {dist:.1f} m away, at "
                  f"{shot.angle} angle, through a {cam.lens_mm} mm lens. {move} Framing: {FRAMING[shot.size]}.")
        people, out_of = [], []
        for p in cut.people:
            m = w.marks.get(p.mark)
            if m is None:
                continue
            if p.who not in shot.in_frame:
                out_of.append(self.name.get(p.who, p.who))
                continue
            at = w.mark_point(m, p.progress)
            side = w.side(cam, shot, at)
            face = w.screen_facing(cam, shot, at, w.facing_vector(p.look_at or m.facing, at, cut.id, shot.beat))
            look = ""
            if p.look_at:
                tgt = w.point_of(p.look_at, cut.id, shot.beat)
                tside = w.side(cam, shot, tgt) if tgt is not None else ""
                where = {"left": "frame left", "right": "frame right", "behind": "behind the camera",
                         "centre": "the centre"}.get(tside, tside)
                look = (f", looking at {self.n(p.look_at)}" + (f" toward {where}" if where else "")
                        + "; the eyes are off the lens, never into the camera")
            head = {"frame left": "turned to frame left", "frame right": "turned to frame right",
                    "the camera": "toward the camera", "away": "away from the camera"}.get(face, face)
            now = self.pin_now(p)
            where_on_plan = (f"{now} on the plan" if now.startswith("between") else f"at {now} on the plan") \
                if now else ""
            people.append(f"The {self.word.get(p.who, 'grey')} mannequin ({self.name.get(p.who, p.who)}) is "
                          f"{POSTURE.get(p.posture, p.posture)}" + (f", {where_on_plan}" if where_on_plan else "")
                          + f": at frame {side}, {(at - P(cam.x, cam.y)).length():.1f} m from the camera, its head "
                          f"{head}{look}.")
        if not people:
            people.append("Nobody is in this frame: no mannequin and no person anywhere in it.")
        if out_of:
            people.append(f"Outside this frame (do not paint): {', '.join(out_of)}.")
        state = self.writer.world_state(cut, set(shot.in_frame))
        props = [self.name.get(x, x) for x in sorted(w.props)]
        key = facts.get("key_light", "")
        refs = ("Reference images, in order: image 1 is the master floor plan of this scene seen from above; "
                + ("image 2 is the location sheet for the place: six views of it; take from image 2 how the place "
                   "looks (its materials, the gate, the path, the water), never where the camera stands (its views are taken from "
                   "other spots), and from image 1 where everything is and where this camera stands. "
                   if views else "")).rstrip()
        parts = [
            "One photorealistic film still for a Sri Lankan television drama, a wide 16:9 frame: one shot of a "
            "storyboard, painted as a real place with mannequins for people. A single picture, no panels.",
            refs, GUIDE, camera, self.layout(shot),
            "In this frame, at the shot's first instant: " + " ".join(people),
            ("The moment: " + state) if state else "",
            f"Place and light: {self.scene['place']['look']} Time: {self.scene['time_of_day']}. "
            f"{rec.light.style}" + (f" The key light comes {key}." if key else ""),
            kit.mannequin_line(self.colours), kit.prop_line(props), kit.SUPPORT,
            "Draw NO text of any kind: no captions, labels, numbers, arrows or marks. The people, place and everyday "
            "details are Sri Lankan.",
        ]
        if shot.type == "insert" or shot.subject in w.props:
            parts.insert(4, f"Fill the frame with {self.n(shot.subject)}; only the part of a mannequin next to it "
                            "shows.")
        return "\n\n".join(x for x in parts if x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--only", default="", help="shot ids, e.g. 2,5,10 (default: every painted shot)")
    ap.add_argument("--yes", action="store_true", help="PAID: paint the shots")
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    out = run / "shots"
    out.mkdir(parents=True, exist_ok=True)
    sp = ShotPlans(rec, scene)
    sp.number_pins()
    data = sp.master_png(out)
    pick = {s.strip() for s in args.only.split(",") if s.strip()}
    shots = [s for s in rec.shots if s.type not in ("black", "title") and sp.w.cam(s) is not None]
    views = scene["place"].get("views") and scene["id"] == "canal"
    view_refs = views_ref(scene) if (args.yes and views) else []
    from hiru_ai.core.ports import Reference
    for s in shots:
        prompt = sp.prompt(s, bool(views))
        (out / f"prompt_{s.id}.txt").write_text(prompt, encoding="utf-8")
        blocked = safe_depiction.blocking(prompt)
        if blocked:
            print(f"shot {s.id}: NOT SENT, safe depiction blocks {blocked}")
            continue
        if not args.yes or (pick and s.id not in pick):
            continue
        worst = (len(prompt) / 3.5 * PRICE["text_in"] + 3000 * PRICE["image_in"] + 4000 * PRICE["out"]) / 1e6
        if spent() + worst > CAP_USD:
            print(f"shot {s.id}: NOT SENT, ${spent():.3f} spent + ${worst:.3f} worst case > ${CAP_USD}")
            break
        from cinematic.run import client
        from hiru_ai.adapters.images import OpenAIImages
        refs = [Reference(label="the master floor plan of this scene seen from above", data=data), *view_refs]
        t = time.time()
        pic = OpenAIImages(client(), model=MODEL, quality=QUALITY)(prompt, kit.BOARD_ASPECT, refs, quality=QUALITY)
        img_in = getattr(pic, "image_input_tokens", 0) or 0
        usd = ((pic.input_tokens - img_in) * PRICE["text_in"] + img_in * PRICE["image_in"]
               + pic.output_tokens * PRICE["out"]) / 1e6
        rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
        rows.append({"run": args.run, "shot": s.id, "usd": round(usd, 4), "s": round(time.time() - t)})
        LEDGER.write_text(json.dumps(rows, indent=1))
        import io

        from PIL import Image
        Image.open(io.BytesIO(pic.data)).convert("RGB").save(out / f"shot_{s.id}.jpg", quality=90)
        print(f"shot {s.id}: ${usd:.4f}; shot-paint spend ${spent():.3f} of ${CAP_USD}")
    cards = []
    for s in shots:
        painted = (f"<img src='shot_{escape(s.id)}.jpg'>" if (out / f"shot_{s.id}.jpg").exists()
                   else "<div class='none'>not painted yet</div>")
        prompt = (out / f"prompt_{s.id}.txt").read_text(encoding="utf-8")
        cards.append(f"<section><h2>Shot {escape(s.id)} · from camera {escape(s.camera)} · {escape(s.size)} "
                     f"{escape(s.type)} · {escape(s.purpose)}</h2><div class='row'>{painted}<pre>{escape(prompt)}"
                     "</pre></div></section>")
    (out / "shots.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Shots from the floor plan</title><style>body{font-family:"
        "system-ui;margin:16px;max-width:1250px}section{border:1px solid #ddd;border-radius:8px;padding:8px 12px;"
        "margin:0 0 14px}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}img{width:560px;height:315px;"
        "object-fit:contain;background:#15171a}img.master{width:auto;height:auto;max-width:100%;max-height:640px} pre{max-width:620px}figure{margin:0}figcaption{font-size:"
        "11px;color:#666;font-weight:600}pre{white-space:pre-wrap;font-size:12px;background:#f6f6f6;padding:8px}"
        ".none{width:560px;height:315px;display:flex;align-items:center;justify-content:center;background:#eee;color:"
        "#888}h2{font-size:15px}</style>"
        f"<h1>Each shot painted from ONE master floor plan: {escape(scene['title'])}</h1><p>The same floor plan "
        "goes with every shot; each shot's prompt (right) names its camera on the plan and gives the framing.</p>"
        "<img src='master_plan.png' class='master'>" + "".join(cards),
        encoding="utf-8")
    print(f"{len(shots)} shots -> {out / 'shots.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
