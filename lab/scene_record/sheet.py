"""The master floor plan sheet: the scene's camera and blocking plan drawn the way a crew's overhead is drawn.

    .venv/Scripts/python.exe lab/scene_record/sheet.py --run 005_canal_sol --scene canal

Best practice (2026-11-28 research: Fiveable and LibreTexts on blocking notation, No Film School, Shot Designer,
FrameForge, production overheads): a legend on every sheet, an accurate scale with a scale bar and north; people as
circles with a facing mark and numbered positions in story order; walks as arrows marked with their beat; every
camera set-up with the field its lens covers, its lens and height; the axis of action; the light sources; one overhead
per beat when people move; and the shot list tied to the plan. This draws:

  MASTER   the whole scene on one sheet (title block, legend, scale bar, north arrow), the picture every shot's
           prompt refers to (cameras named C1, C2 ...; positions A1, A2 ...);
  BEATS    one overhead per beat: who is where in that beat (the others faint), its walks, and only the set-ups whose
           shots cover that beat;
  TABLES   set-ups (role, shots, sizes, lens range, height, covers) and blocking (each position, beats, note).

Writes runs/<run>/floorplan/: master.svg, master.png (rendered by the local headless Chrome), beat_<n>.svg and
floorplan.html. Free.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from chain import POSTURE  # noqa: E402
from checks import Report, check  # noqa: E402
from geometry import COMPASS, P, hfov  # noqa: E402
from plan_view import BG, INK, MUTED, WALK, Plan  # noqa: E402
from schema import SceneRecord  # noqa: E402

from contracts import board as kit  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
HEX = {"red": "#d0453a", "blue": "#3a7bd5", "yellow": "#e3c143", "green": "#2f9e5b", "purple": "#8e44ad",
       "orange": "#e67e22"}
CAM = "#5aa7f0"
LIGHT = "#f2c94c"


class Sheet(Plan):
    """A Plan drawn at sheet size, with pins numbered in story order and the person's mannequin colours."""

    def __init__(self, rec: SceneRecord, scene: dict[str, Any], rep: Report, width: float = 1000,
                 height: float = 780, pad: float = 2.2) -> None:
        focus = [P(m.x, m.y) for m in rec.marks] + [P(m.moves_to[0].x, m.moves_to[0].y) for m in rec.marks
                                                    if m.moves_to] + [P(c.x, c.y) for c in rec.cameras
                                                                      if any(s.camera == c.id for s in rec.shots)]
        super().__init__(rec, scene, rep, focus=focus, pad=pad)
        self.k = min(width / (self.x1 - self.x0), height / (self.y1 - self.y0))
        self.W, self.H = (self.x1 - self.x0) * self.k, (self.y1 - self.y0) * self.k
        words = kit.colours_for([p["name"] for p in scene["people"]])
        self.colour = {p["id"]: HEX[words[p["name"]]] for p in scene["people"]}
        self.word = {p["id"]: words[p["name"]] for p in scene["people"]}
        self.obstacles: list[tuple[float, float, float, float]] = []
        self.pins: dict[tuple[str, int], str] = {}
        self.order = self.positions()
        initials = {p["id"]: p["name"][:1].upper() for p in scene["people"]}
        for who, seq in self.order.items():
            for i, pos in enumerate(seq):
                self.pins[(who, id(pos))] = f"{initials.get(who, '?')}{i + 1}"

    # ── pieces ─────────────────────────────────────────────────────────────────────────────────────────────────────
    def key_light(self) -> str:
        """The key light's source with an arrow showing the way its light travels across the action."""
        key = next((lm for lm in self.rec.landmarks if lm.id == self.rec.light.key), None)
        if key is None:
            return ""
        src = P(key.points[0].x, key.points[0].y)
        centre = self.people_c
        d = centre - src
        if d.length() < 0.1:
            return ""
        u = d.scale(1 / d.length())
        a = self.clamp(centre - u.scale(min(d.length(), 3.5)))
        b = self.clamp(centre - u.scale(1.2))
        (ax, ay), (bx, by) = self.s(a), self.s(b)
        self.text(a, "KEY LIGHT", 11, LIGHT, "bold", dy=-12, priority=2)
        return (f"<line x1='{ax:.1f}' y1='{ay:.1f}' x2='{bx:.1f}' y2='{by:.1f}' stroke='{LIGHT}' stroke-width='3' "
                "stroke-dasharray='2 5' marker-end='url(#lightarrow)'/>")

    def clamp(self, p: P) -> P:
        return P(min(max(p.x, self.x0 + 0.5), self.x1 - 0.5), min(max(p.y, self.y0 + 0.5), self.y1 - 0.5))

    def setups(self, beat: int | None = None) -> str:
        """Each camera set-up: the field its widest lens covers (a light wedge), a triangle pointing the way it looks,
        dashed arrows to what it films, and a label: id, role, shots, lens range, height."""
        out, arrows = [], []
        for ids in self.w.setups(cluster_m=0.15):
            shots = [s for s in self.rec.shots if s.camera in ids and (beat is None or s.beat == beat)]
            if not shots:
                continue
            c = self.w.cams[ids[0]]
            here = P(c.x, c.y)
            lenses = sorted({(self.w.cam(s).lens_mm if self.w.cam(s) else c.lens_mm) for s in shots})
            targets: list[P] = []
            for s in shots:
                cam = self.w.cam(s)
                t = self.w.point_of(cam.looks_at, s.start, s.beat) if cam else None
                if t is not None and all((t - q).length() > 0.3 for q in targets):
                    targets.append(t)
            if not targets:
                continue
            u = targets[0] - here
            u = u.scale(1 / max(u.length(), 1e-6))
            half = math.radians(hfov(lenses[0]) / 2)
            reach = max((t - here).length() for t in targets) * 1.12
            base = math.atan2(u.y, u.x)
            tips = [self.s(P(c.x + reach * math.cos(a), c.y + reach * math.sin(a))) for a in (base - half, base + half)]
            x, y = self.s(here)
            out.append(f"<polygon points='{x:.1f},{y:.1f} {tips[0][0]:.1f},{tips[0][1]:.1f} {tips[1][0]:.1f},"
                       f"{tips[1][1]:.1f}' fill='{CAM}' opacity='0.10' stroke='{CAM}' stroke-opacity='0.35'/>")
            for t in targets:
                v = t - here
                if v.length() < 0.25:
                    continue
                ex, ey = self.s(here + v.scale((v.length() - 0.3) / v.length()))
                arrows.append(f"<line x1='{x:.1f}' y1='{y:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='{CAM}' "
                              "stroke-width='2' stroke-dasharray='6 5' marker-end='url(#camarrow)'/>")
            ang = math.atan2(-u.y, u.x)
            tri = [(x + 14 * math.cos(ang), y + 14 * math.sin(ang)),
                   (x + 11 * math.cos(ang + 2.3), y + 11 * math.sin(ang + 2.3)),
                   (x + 11 * math.cos(ang - 2.3), y + 11 * math.sin(ang - 2.3))]
            out.append("<polygon points='" + " ".join(f"{a:.1f},{b:.1f}" for a, b in tri) +
                       f"' fill='{CAM}' stroke='white' stroke-width='2'/>")
            self.obstacles.append((x - 15, y - 15, x + 15, y + 15))
            lens = f"{lenses[0]} mm" if len(lenses) == 1 else f"{lenses[0]}–{lenses[-1]} mm"
            roles = "/".join(dict.fromkeys(self.w.cams[i].role for i in ids))
            self.text(here, f"{'/'.join(ids)} · {roles}", 13, INK, "bold", dy=-20, priority=3)
            self.text(here, f"shot {', '.join(s.id for s in shots)} · {lens} · {c.height.replace('_', ' ')}", 10,
                      "#bcd7f2", dy=30, priority=2)
        return "".join(out) + "".join(arrows)

    def people(self, beat: int | None = None) -> str:
        """Every person's numbered positions with a facing tick; walks as arrows marked with their beat. With `beat`,
        the positions and walks of other beats are drawn faint."""
        out = []
        for who, seq in self.order.items():
            col = self.colour.get(who, "#ccc")
            for pos in seq:
                m = pos["mark"]
                if m is None or not m.moves_to:
                    continue
                live = beat is None or m.beat == beat
                a, b = self.s(pos["at"]), self.s(P(m.moves_to[0].x, m.moves_to[0].y))
                out.append(f"<line x1='{a[0]:.1f}' y1='{a[1]:.1f}' x2='{b[0]:.1f}' y2='{b[1]:.1f}' stroke='{WALK}' "
                           f"stroke-width='4' stroke-dasharray='10 6' marker-end='url(#arrow)' "
                           f"opacity='{1 if live else 0.25}'/>")
                if live:
                    mid = P((pos["at"].x + m.moves_to[0].x) / 2, (pos["at"].y + m.moves_to[0].y) / 2)
                    self.text(mid, f"walk · beat {m.beat}", 10, WALK, "bold", dy=-10, priority=2)
            drawn: list[tuple[P, list[str], list[Any]]] = []
            for pos in seq:
                label = self.pins[(who, id(pos))]
                spot = next((d for d in drawn if (d[0] - pos["at"]).length() < 0.3), None)
                if spot is None:
                    drawn.append((pos["at"], [label], [pos]))
                else:
                    spot[1].append(label)
                    spot[2].append(pos)
            for at, labels, poss in drawn:
                live = beat is None or any(p["mark"] is not None and (p["mark"].beat == beat or (
                    p["mark"].beat < beat and p is poss[-1])) for p in poss)
                op = 1 if live else 0.3
                x, y = self.s(at)
                m = poss[-1]["mark"] or poss[0]["mark"]
                if m is not None and m.facing:
                    fv = self.w.facing_vector(m.facing, at, "K0", m.beat)
                    if fv is not None and fv.length() > 0:
                        tip = at + fv.scale(0.75 / fv.length())
                        tx, ty = self.s(tip)
                        out.append(f"<line x1='{x:.1f}' y1='{y:.1f}' x2='{tx:.1f}' y2='{ty:.1f}' stroke='white' "
                                   f"stroke-width='3' opacity='{op}' stroke-linecap='round'/>")
                tag = compact(labels)
                r = max(13, 4 + 3.4 * len(tag))
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{col}' stroke='white' "
                           f"stroke-width='2.5' opacity='{op}'/><text x='{x:.1f}' y='{y + 4:.1f}' font-size='11' "
                           f"font-weight='bold' fill='white' text-anchor='middle' opacity='{op}'>{escape(tag)}</text>")
                self.obstacles.append((x - r, y - r, x + r, y + r))
                if live:
                    posture = POSTURE.get((poss[-1]["mark"] or poss[0]["mark"]).posture, "") if m else ""
                    self.text(at, posture, 10, "#e8e8e8", dy=r + 14, priority=2)
        return "".join(out)

    def scale_north(self) -> str:
        """A scale bar (1, 2, 5 or 10 m, whichever is near 120 px) and a north arrow, bottom right."""
        metres = next((m for m in (1, 2, 5, 10, 20) if m * self.k >= 90), 20)
        px = metres * self.k
        x0, y0 = self.W - px - 24, self.H - 22
        nx, ny = self.W - 30, 34
        return (f"<rect x='{x0 - 8:.1f}' y='{y0 - 22:.1f}' width='{px + 16:.1f}' height='34' rx='6' fill='{BG}' "
                f"opacity='0.75'/><line x1='{x0:.1f}' y1='{y0:.1f}' x2='{x0 + px:.1f}' y2='{y0:.1f}' stroke='white' "
                f"stroke-width='3'/><line x1='{x0:.1f}' y1='{y0 - 6:.1f}' x2='{x0:.1f}' y2='{y0 + 6:.1f}' "
                f"stroke='white' stroke-width='2'/><line x1='{x0 + px:.1f}' y1='{y0 - 6:.1f}' x2='{x0 + px:.1f}' "
                f"y2='{y0 + 6:.1f}' stroke='white' stroke-width='2'/><text x='{x0 + px / 2:.1f}' y='{y0 - 8:.1f}' "
                f"font-size='11' fill='white' text-anchor='middle'>{metres} m</text>"
                f"<circle cx='{nx}' cy='{ny}' r='17' fill='{BG}' opacity='0.75'/><polygon points='{nx},{ny - 13} "
                f"{nx - 7},{ny + 7} {nx},{ny + 2} {nx + 7},{ny + 7}' fill='white'/><text x='{nx}' y='{ny + 26}' "
                f"font-size='11' font-weight='bold' fill='white' text-anchor='middle'>N</text>")

    def defs(self) -> str:
        def arrow(name: str, colour: str) -> str:
            return (f"<marker id='{name}' markerUnits='userSpaceOnUse' markerWidth='12' markerHeight='12' refX='10' "
                    f"refY='6' orient='auto'><path d='M0,0 L12,6 L0,12 z' fill='{colour}'/></marker>")
        return "<defs>" + arrow("arrow", WALK) + arrow("camarrow", CAM) + arrow("lightarrow", LIGHT) + "</defs>"

    def drawing(self, beat: int | None = None) -> str:
        """The plan itself (place, light, axis, set-ups, people, scale), as an <svg> of W x H."""
        self.labels = []
        body = self.place() + self.light() + self.key_light() + self.axis() + self.setups(beat) + \
            self.people(beat) + self.scale_north()
        return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {self.W:.0f} {self.H:.0f}' "
                f"width='{self.W:.0f}' height='{self.H:.0f}' font-family='system-ui, sans-serif'>{self.defs()}"
                f"{body}{self.resolve()}</svg>")

    def legend(self) -> str:
        """The legend, as HTML/SVG rows (on the sheet, under the plan)."""
        people = "".join(f"<span class='lg'><svg width='22' height='22'><circle cx='11' cy='11' r='9' "
                         f"fill='{self.colour[p['id']]}' stroke='white' stroke-width='2'/></svg>{escape(p['name'])} "
                         f"({escape(self.word[p['id']])} mannequin)</span>" for p in self.scene["people"])
        items = [
            ("<svg width='34' height='22'><circle cx='11' cy='11' r='9' fill='#888' stroke='white' stroke-width='2'/>"
             "<line x1='11' y1='11' x2='30' y2='11' stroke='white' stroke-width='3' stroke-linecap='round'/></svg>",
             "a person's position, numbered in story order (A1, A2 ...); the white tick is the way they face"),
            (f"<svg width='34' height='22'><line x1='2' y1='11' x2='26' y2='11' stroke='{WALK}' stroke-width='4' "
             f"stroke-dasharray='8 5'/><polygon points='24,5 33,11 24,17' fill='{WALK}'/></svg>",
             "a walk, marked with its beat"),
            (f"<svg width='34' height='22'><polygon points='4,4 32,11 4,18' fill='{CAM}' opacity='0.25'/><polygon "
             f"points='14,11 4,5 4,17' fill='{CAM}' stroke='white' stroke-width='1.5'/></svg>",
             "a camera set-up (C1, C2 ...) and the field its widest lens covers; dashed arrows go to what it films"),
            ("<svg width='34' height='22'><line x1='2' y1='11' x2='32' y2='11' stroke='#e5534b' stroke-width='2' "
             "stroke-dasharray='6 4'/></svg>", "the axis of action: every camera stays on one side of it"),
            (f"<svg width='34' height='22'><circle cx='11' cy='11' r='6' fill='{LIGHT}'/><line x1='20' y1='11' "
             f"x2='32' y2='11' stroke='{LIGHT}' stroke-width='3' stroke-dasharray='2 4'/></svg>",
             "a light source; the dotted arrow is the way the key light falls"),
        ]
        rows = "".join(f"<span class='lg'>{icon}{escape(text)}</span>" for icon, text in items)
        return f"<div class='legend'>{people}{rows}</div>"


def compact(labels: list[str]) -> str:
    """Pins on one spot: N1, N2, N3, N4 -> 'N1–4'; A2, A4 -> 'A2·A4'."""
    if len(labels) == 1:
        return labels[0]
    head = labels[0].rstrip("0123456789")
    nums = [int(x[len(head):]) for x in labels if x.startswith(head) and x[len(head):].isdigit()]
    if len(nums) == len(labels) and nums == list(range(nums[0], nums[0] + len(nums))):
        return f"{head}{nums[0]}–{nums[-1]}"
    return "·".join(labels)


def render_png(svg: str, path: Path, w: float, h: float) -> None:
    page = path.with_suffix(".html")
    page.write_text(f"<!doctype html><body style='margin:0;background:{BG}'>{svg}</body>", encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",  # noqa: S603
                    f"--window-size={int(w)},{int(h)}", f"--screenshot={path}", page.as_uri()],
                   check=True, capture_output=True, timeout=60)
    page.unlink()


def build(rec: SceneRecord, scene: dict[str, Any], out: Path) -> Sheet:
    rep = check(rec, scene)
    master = Sheet(rec, scene, rep)
    svg = master.drawing()
    (out / "master.svg").write_text(svg, encoding="utf-8")
    render_png(svg, out / "master.png", master.W, master.H)
    beats = []
    for b in rec.beats:
        if not any(s.beat == b.n and s.camera for s in rec.shots):
            continue
        sh = Sheet(rec, scene, rep, width=520, height=420)
        bsvg = sh.drawing(beat=b.n)
        (out / f"beat_{b.n}.svg").write_text(bsvg, encoding="utf-8")
        shots = ", ".join(s.id for s in rec.shots if s.beat == b.n and s.camera)
        beats.append(f"<figure>{bsvg}<figcaption><b>Beat {b.n}</b> · intensity {b.intensity} · power "
                     f"{escape(master.names.get(b.dominant, b.dominant))} · shots {escape(shots)}<br>"
                     f"{escape(b.what)}</figcaption></figure>")
    blocking = []
    for who, seq in master.order.items():
        for pos in seq:
            m = pos["mark"]
            label = master.pins[(who, id(pos))]
            note = (m.label or POSTURE.get(m.posture, m.posture)) if m else "end of the walk"
            beats_of = pos["beats"]
            span = f"beat {beats_of[0]}" if len(beats_of) == 1 else f"beats {beats_of[0]}–{beats_of[-1]}"
            facing = ""
            if m and m.facing:
                facing = f"facing {m.facing}" if m.facing in COMPASS else \
                    f"facing {master.names.get(m.facing, m.facing)}"
            blocking.append(f"<tr><td><b style='color:{master.colour[who]}'>{escape(label)}</b></td><td>"
                            f"{escape(master.names.get(who, who))}</td><td>{escape(span)}</td><td>"
                            f"{escape(POSTURE.get(m.posture, '') if m else '')}</td><td>{escape(facing)}</td><td>"
                            f"{escape(note)}</td></tr>")
    head = scene.get("heading", "")
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Floor plan: {escape(scene['title'])}</title>
<style>body{{background:{BG};color:{INK};font-family:system-ui,sans-serif;margin:20px;max-width:1080px}}
.title{{border:2px solid #3a4046;border-radius:10px;padding:10px 14px;margin-bottom:12px;display:flex;gap:30px;
flex-wrap:wrap}} .title b{{font-size:18px}} .title span{{color:{MUTED};font-size:13px}}
.card{{border:1px solid #2c3136;border-radius:12px;padding:12px;background:#0f1113;margin-bottom:18px}}
.legend{{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:10px;font-size:12px;color:#c9d1d9}}
.lg{{display:inline-flex;align-items:center;gap:6px}} h2{{font-size:15px;margin:22px 0 8px}}
.beats{{display:flex;flex-wrap:wrap;gap:14px}} figure{{margin:0;max-width:520px}} figcaption{{font-size:12px;
color:#c9d1d9;margin-top:4px}} table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px
solid #2c3136;padding:6px 8px;text-align:left;vertical-align:top}} th{{color:{MUTED}}}</style></head><body>
<div class='title'><div><b>MASTER FLOOR PLAN</b><br><span>{escape(scene['title'])}</span></div>
<div><span>Scene</span><br>{escape(head)}</div><div><span>Time</span><br>{escape(scene.get('time_of_day', ''))}</div>
<div><span>Set-ups</span><br>{len(master.w.setups(cluster_m=0.15))} for {sum(1 for s in rec.shots if s.camera)} shots</div>
<div><span>North is up · metres to scale</span></div></div>
<div class='card'>{svg}{master.legend()}</div>
<h2>Set-ups</h2><div class='card'><table><tr><th>Set-up</th><th>Role</th><th>Shots</th><th>Lens</th><th>Height</th>
<th>Covers</th></tr>{master.camera_rows()}</table></div>
<h2>Blocking</h2><div class='card'><table><tr><th>Pin</th><th>Who</th><th>When</th><th>Posture</th><th>Facing</th>
<th>Note</th></tr>{''.join(blocking)}</table></div>
<h2>Overheads by beat</h2><div class='beats'>{''.join(beats)}</div></body></html>"""
    (out / "floorplan.html").write_text(page, encoding="utf-8")
    return master


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
    build(rec, scene, out)
    print(f"-> {out / 'floorplan.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
