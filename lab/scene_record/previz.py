"""3D blocking previz: each shot rendered from its camera, free and offline (three.js in the local headless Chrome).

    .venv/Scripts/python.exe lab/scene_record/previz.py --run 005_canal_sol --scene canal

The research (2026-11-28, FINDINGS): AI storyboards hold the camera angle only when each frame starts from a rough 3D
blocking render (FrameForge, Shot Generator, PrevizWhiz); text alone is not followed. The scene record already holds
everything a render needs, so this draws each shot from its camera: the place as simple shapes from the floor plan
(ground, water, paths with their width, the gate and walls as blocks, a table), every person as a coloured mannequin
in their posture (standing, walking, kneeling, lying, seated, leaning, rising) facing the way the plan says with the
head turned toward what they look at, the props the story has shown as white blocks at the hand or on the table, and
the camera at its position, height and lens (full-frame 16:9: vertical field of view 2·atan(10.125 / mm)).

Writes runs/<run>/previz/: grid.png (every painted shot in the board's grid, white gutters: the reference a painted
board follows), frame_<shot>.png, previz.html (the page that rendered them) and review.html. three.js r160 (MIT) is
vendored in lab/scene_record/vendor/. Nothing is sent anywhere.
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

from board import _target_height  # noqa: E402
from checks import check  # noqa: E402
from geometry import P, World, dot  # noqa: E402
from plan_view import area, area_colour  # noqa: E402
from schema import SceneRecord  # noqa: E402

from contracts import board as kit  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CELL_W, CELL_H, GUTTER = 640, 360, 8
CAM_H = {"ground": 0.15, "knee": 0.5, "seated_eye": 1.1, "standing_eye": 1.6, "high": 2.6, "overhead": 5.0}
HEX = {"red": "#c8463b", "blue": "#2f6fc0", "yellow": "#e3c143", "green": "#2f9e5b", "purple": "#8e44ad",
       "orange": "#e67e22"}


def yaw_of(v: P) -> float:
    """three.js yaw for a plan direction (plan x east, y north; three x east, z south): local +z points along v."""
    return math.atan2(v.x, -v.y)


def prop_size(name: str) -> list[float]:
    n = name.lower()
    for words, size in ((("bag", "case", "box"), [0.34, 0.24, 0.14]), (("phone",), [0.075, 0.15, 0.012]),
                        (("key",), [0.05, 0.07, 0.01]), (("deed", "paper", "letter", "document"), [0.21, 0.01, 0.12]),
                        (("cup", "glass"), [0.08, 0.09, 0.08])):
        if any(w in n for w in words):
            return size
    return [0.15, 0.15, 0.15]


def scene_data(rec: SceneRecord, scene: dict[str, Any]) -> dict[str, Any]:
    w = World(rec)
    rep = check(rec, scene)
    colours = kit.colours_for([p["name"] for p in scene["people"]])
    hexes = {p["id"]: HEX[colours[p["name"]]] for p in scene["people"]}
    people_pts = [P(m.x, m.y) for m in rec.marks]
    pc = P(sum(p.x for p in people_pts) / len(people_pts), sum(p.y for p in people_pts) / len(people_pts))
    place: list[dict[str, Any]] = []
    for lm in rec.landmarks:
        pts = [P(q.x, q.y) for q in lm.points]
        name = lm.name.lower()
        if lm.kind in ("water", "area") and len(pts) >= 3 and area(pts) > 0.5:
            place.append({"type": "poly", "pts": [[q.x, q.y] for q in pts], "colour": area_colour(lm),
                          "y": 0.012 if area_colour(lm) == "#3a87ab" else 0.003 + 0.001 * len(place)})
        elif lm.kind == "water" and len(pts) > 1:  # an edge: water 4 m deep on the far side from the people
            d = pts[-1] - pts[0]
            n = P(-d.y, d.x).scale(1 / max(d.length(), 1e-6))
            if dot(n, pc - pts[0]) > 0:
                n = n.scale(-1)
            band = [*pts, *[q + n.scale(4) for q in reversed(pts)]]
            place.append({"type": "poly", "pts": [[q.x, q.y] for q in band], "colour": "#3a87ab", "y": 0.012})
        elif lm.kind == "path" and len(pts) > 1:
            place.append({"type": "path", "pts": [[q.x, q.y] for q in pts], "width": lm.width or 1.2,
                          "colour": "#9a7b55"})
        elif lm.kind == "wall" and len(pts) > 1:
            place.append({"type": "wall", "pts": [[q.x, q.y] for q in pts], "colour": "#cfc6b8"})
        elif lm.kind in ("fixed", "furniture", "door") and len(pts) == 1:
            tall = 1.8 if "gate" in name else 0.75 if lm.kind == "furniture" else 2.0 if lm.kind == "door" else 0.9
            colour = "#6b4b34" if "gate" in name else "#8a6a48" if lm.kind == "furniture" else "#9a9a96"
            place.append({"type": "block", "at": [pts[0].x, pts[0].y], "w": lm.width or 1.0,
                          "d": 0.4 if lm.kind != "furniture" else (lm.width or 1.1) * 0.65, "h": tall,
                          "colour": colour, "table": lm.kind == "furniture"})
        elif lm.kind == "fixed" and len(pts) > 1:
            place.append({"type": "wall", "pts": [[q.x, q.y] for q in pts], "colour": "#9a9a96", "h": 0.35})
    key = next((lm for lm in rec.landmarks if lm.id == rec.light.key), None)
    key_at = [key.points[0].x, key.points[0].y] if key else [pc.x + 5, pc.y + 8]
    shots = []
    for s in rec.shots:
        cam = w.cam(s)
        if s.type in ("black", "title") or cam is None:
            continue
        cut = w.cuts[s.start]
        target = w.point_of(cam.looks_at, s.start, s.beat)
        if target is None:
            continue
        aim_h = _target_height(w, s, cut)
        h = CAM_H.get(cam.height, 1.5)
        dist = (target - P(cam.x, cam.y)).length()
        nudge = {"high": -0.25, "low": 0.2}.get(s.angle, 0.0) * dist * math.tan(math.radians(10.125 * 2 / max(cam.lens_mm, 1) * 57.3 / 2))
        people = []
        for p in cut.people:
            m = w.marks.get(p.mark)
            if m is None:
                continue
            at = w.mark_point(m, p.progress)
            body = w.facing_vector(m.facing, at, cut.id, s.beat)
            look = w.facing_vector(p.look_at, at, cut.id, s.beat) if p.look_at else None
            byaw = yaw_of(body) if body is not None and body.length() > 0 else (yaw_of(look) if look else 0.0)
            hyaw = (yaw_of(look) - byaw) if look is not None and look.length() > 0 else 0.0
            hyaw = (hyaw + math.pi) % (2 * math.pi) - math.pi
            people.append({"who": p.who, "colour": hexes.get(p.who, "#888"), "at": [at.x, at.y],
                           "posture": p.posture, "yaw": byaw, "head": max(-1.3, min(1.3, hyaw))})
        props = []
        for prop in sorted(w.props):
            st = w.prop_state(prop, cut.id)
            if st is None or not st.seen:
                continue
            name = next((x["name"] for x in scene["props"] if x["id"] == prop), prop)
            item = {"size": prop_size(name), "id": prop}
            if st.on and st.on in w.land:
                q = w.point_of(st.on, cut.id, s.beat)
                item.update(at=[q.x, q.y], y=0.78 if w.land[st.on].kind == "furniture" else 0.02)
            elif st.holder:
                hold = next((x for x in people if x["who"] == st.holder), None)
                if hold is None:
                    continue
                item.update(holder=st.holder, hand=st.hand or "chest")  # no hand: a pocket, at the chest
            else:
                continue
            props.append(item)
        shots.append({"id": s.id, "subject": s.subject, "angle": s.angle,
                      "cam": [cam.x, h, cam.y], "look": [target.x, aim_h + nudge, target.y],
                      "vfov": math.degrees(2 * math.atan(10.125 / max(cam.lens_mm, 1))), "people": people,
                      "props": props, "size": s.size, "camera": s.camera})
    return {"place": place, "key": key_at, "shots": shots, "night": scene.get("time_of_day") in ("night",),
            "dusk": scene.get("time_of_day") in ("dusk", "evening"), "facts": {k: v for k, v in rep.facts.items()}}


PAGE = r"""<!doctype html><html><head><meta charset='utf-8'><style>
body{margin:0;background:#fff} #grid{display:grid;grid-template-columns:repeat(__COLS__,__W__px);gap:__G__px;padding:0}
canvas{display:block;width:__W__px;height:__H__px}</style></head><body><div id='grid'></div>
<script type='module'>
import * as THREE from '__THREE__';
const D = __DATA__;
const W = __W__, H = __H__;
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
renderer.setSize(W, H); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const P = (x, y, h = 0) => new THREE.Vector3(x, h, -y);            // plan (x east, y north) -> three
const mat = c => new THREE.MeshStandardMaterial({color: c, roughness: 0.75});
function world() {
  const s = new THREE.Scene();
  s.background = new THREE.Color(D.dusk ? '#9aa3b5' : '#c9d0d6');
  s.fog = new THREE.Fog(s.background, 25, 90);
  s.add(new THREE.HemisphereLight('#e8eef4', '#5a4a3a', 1.1));
  const sun = new THREE.DirectionalLight('#fff4e0', D.dusk ? 0.9 : 1.4);
  const k = P(D.key[0], D.key[1], 0);
  sun.position.set(k.x, 12, k.z); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024); Object.assign(sun.shadow.camera, {left: -15, right: 15, top: 15, bottom: -15});
  s.add(sun);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat('#7c6a50'));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; s.add(ground);
  for (const it of D.place) {
    if (it.type === 'poly') {
      const sh = new THREE.Shape(it.pts.map(([x, y]) => new THREE.Vector2(x, y)));
      const m = new THREE.Mesh(new THREE.ShapeGeometry(sh), mat(it.colour));
      m.rotation.x = -Math.PI / 2; m.position.y = it.y; m.receiveShadow = true; s.add(m);
    } else if (it.type === 'path' || it.type === 'wall') {
      for (let i = 0; i + 1 < it.pts.length; i++) {
        const a = P(...it.pts[i]), b = P(...it.pts[i + 1]); const len = a.distanceTo(b);
        const hgt = it.type === 'wall' ? (it.h || 2.6) : 0.02, wid = it.type === 'wall' ? 0.15 : it.width;
        const m = new THREE.Mesh(new THREE.BoxGeometry(wid, hgt, len + (it.type === 'path' ? wid : 0)), mat(it.colour));
        m.position.set((a.x + b.x) / 2, hgt / 2 + 0.004, (a.z + b.z) / 2);
        m.rotation.y = Math.atan2(b.x - a.x, b.z - a.z); m.castShadow = it.type === 'wall'; m.receiveShadow = true; s.add(m);
      }
    } else if (it.type === 'block') {
      const g = new THREE.Group(); const c = P(it.at[0], it.at[1]);
      if (it.table) {
        const top = new THREE.Mesh(new THREE.BoxGeometry(it.w, 0.05, it.d), mat(it.colour)); top.position.y = it.h; g.add(top);
        for (const [dx, dz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
          const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, it.h, 0.05), mat(it.colour));
          leg.position.set(dx * (it.w / 2 - 0.05), it.h / 2, dz * (it.d / 2 - 0.05)); g.add(leg);
        }
      } else {
        const b = new THREE.Mesh(new THREE.BoxGeometry(it.w, it.h, it.d), mat(it.colour)); b.position.y = it.h / 2; g.add(b);
      }
      g.position.copy(c); g.traverse(o => { o.castShadow = true; o.receiveShadow = true; }); s.add(g);
    }
  }
  return s;
}
function cap(r, len, m) { const x = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 4, 10), m); x.castShadow = true; return x; }
// a mannequin: a pelvis group at the hips; local +z is where it faces
const POSE = {  // pelvis height, thigh pitch, knee bend, torso pitch (radians; + leans forward)
  standing: [0.92, 0, 0, 0], walking: [0.9, 0, 0.15, 0.05], seated: [0.47, -1.57, 1.57, 0.05],
  sitting_down: [0.6, -1.2, 1.3, 0.25], kneeling: [0.5, 0, 1.57, 0.05], kneeling_down: [0.62, -0.55, 1.75, 0.35],
  crouching: [0.45, -1.9, 2.3, 0.45], leaning: [0.92, 0, 0, 0.5], rising: [0.7, -0.9, 0.95, 0.35], lying: [0.92, 0, 0, 0]};
function mannequin(p) {
  const m = mat(p.colour), root = new THREE.Group(), pelvis = new THREE.Group();
  const [ph, thighP, knee, lean] = POSE[p.posture] || POSE.standing;
  pelvis.position.y = ph; root.add(pelvis);
  const torso = new THREE.Group(); torso.rotation.x = lean; pelvis.add(torso);
  const body = cap(0.15, 0.4, m); body.position.y = 0.3; torso.add(body);
  const headG = new THREE.Group(); headG.position.y = 0.68; headG.rotation.y = p.head; torso.add(headG);
  root.userData.head = headG; root.userData.pelvis = pelvis; root.userData.chest = body;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 12), m); head.castShadow = true; headG.add(head);
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.07, 8), m); nose.rotation.x = Math.PI / 2; nose.position.set(0, 0, 0.11); headG.add(nose);
  for (const side of [-1, 1]) {
    const hip = new THREE.Group(); hip.position.set(0.09 * side, 0, 0);
    hip.rotation.x = thighP + (p.posture === 'walking' ? 0.35 * side : 0); pelvis.add(hip);
    const th = cap(0.07, 0.32, m); th.position.y = -0.23; hip.add(th);
    const kn = new THREE.Group(); kn.position.y = -0.45; kn.rotation.x = knee; hip.add(kn);
    const sh = cap(0.055, 0.32, m); sh.position.y = -0.22; kn.add(sh);
    const shoulder = new THREE.Group(); shoulder.position.set(0.21 * side, 0.52, 0); torso.add(shoulder);
    shoulder.rotation.z = 0.1 * side; shoulder.rotation.x = -0.15;
    const ua = cap(0.05, 0.22, m); ua.position.y = -0.16; shoulder.add(ua);
    const el = new THREE.Group(); el.position.y = -0.3; el.rotation.x = -0.3; shoulder.add(el);
    const fa = cap(0.045, 0.2, m); fa.position.y = -0.14; el.add(fa);
    const hand = new THREE.Group(); hand.position.y = -0.28; el.add(hand);
    root.userData[side < 0 ? 'right' : 'left'] = hand;   // the figure's right hand is on its -x side
  }
  if (p.posture === 'lying') { root.rotation.x = -Math.PI / 2; root.position.y = 0.16; }
  const yawG = new THREE.Group(); yawG.add(root); yawG.rotation.y = p.yaw + (p.posture === 'lying' ? Math.PI : 0);
  yawG.position.copy(P(p.at[0], p.at[1])); yawG.userData = root.userData;
  return yawG;
}
const grid = document.getElementById('grid');
const base = world();
for (const shot of D.shots) {
  const s = base.clone();
  const figs = {};
  for (const p of shot.people) { const f = mannequin(p); figs[p.who] = f; s.add(f); }
  s.updateMatrixWorld(true);
  const shotProps = {};
  for (const it of shot.props) {
    const box = new THREE.Mesh(new THREE.BoxGeometry(...it.size), mat('#f4f4f2')); box.castShadow = true;
    shotProps[it.id] = box;
    if (it.holder && figs[it.holder] && it.hand === 'chest') {
      const f = figs[it.holder], fwd = new THREE.Vector3(); f.userData.chest.getWorldPosition(box.position);
      f.getWorldDirection(fwd); box.position.addScaledVector(fwd, 0.17); box.position.y += 0.12; }
    else if (it.holder && figs[it.holder]) { const hand = figs[it.holder].userData[it.hand] || figs[it.holder].userData.right;
      hand.getWorldPosition(box.position); }
    else { box.position.copy(P(it.at[0], it.at[1], it.y + it.size[1] / 2)); }
    s.add(box);
  }
  const cam = new THREE.PerspectiveCamera(shot.vfov, W / H, 0.05, 300);
  cam.position.copy(P(shot.cam[0], shot.cam[2], shot.cam[1]));
  // aim at the real thing: a person's head for a close frame, lower for a wider one; a prop where it is drawn
  let aim = P(shot.look[0], shot.look[2], shot.look[1]);
  const fig = figs[shot.subject];
  if (fig) {
    const head = new THREE.Vector3(), pelvis = new THREE.Vector3(), chest = new THREE.Vector3();
    fig.userData.head.getWorldPosition(head); fig.userData.pelvis.getWorldPosition(pelvis);
    fig.userData.chest.getWorldPosition(chest);
    const sz = shot.size;
    if (sz === 'ECU' || sz === 'CU') aim = head;
    else if (sz === 'MCU') aim = head.clone().lerp(chest, 0.45);
    else if (sz === 'MS') aim = chest;
    else aim = head.clone().lerp(pelvis, 0.6);
  } else if (shotProps[shot.subject]) {
    aim = shotProps[shot.subject].position.clone();
  }
  const dist = cam.position.distanceTo(aim);
  const tilt = Math.tan(THREE.MathUtils.degToRad(shot.vfov / 2)) * dist / 3;   // a third of the half frame
  if (shot.angle === 'high') aim.y -= tilt; else if (shot.angle === 'low') aim.y += tilt;
  cam.lookAt(aim);
  renderer.render(s, cam);
  const c = document.createElement('canvas'); c.width = W; c.height = H; c.id = 'shot_' + shot.id;
  c.getContext('2d').drawImage(renderer.domElement, 0, 0); grid.appendChild(c);
}
document.title = 'done';
</script></body></html>"""


def render(rec: SceneRecord, scene: dict[str, Any], out: Path) -> list[str]:
    data = scene_data(rec, scene)
    n = len(data["shots"])
    cols, rows = kit.grid_for(n)
    three = (HERE / "vendor" / "three.module.js").as_uri()
    page = (PAGE.replace("__DATA__", json.dumps({k: v for k, v in data.items() if k != "facts"}))
            .replace("__THREE__", three).replace("__COLS__", str(cols)).replace("__W__", str(CELL_W))
            .replace("__H__", str(CELL_H)).replace("__G__", str(GUTTER)))
    html = out / "previz.html"
    html.write_text(page, encoding="utf-8")
    grid_png = out / "grid.png"
    width, height = cols * CELL_W + (cols - 1) * GUTTER, rows * CELL_H + (rows - 1) * GUTTER
    subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--use-angle=swiftshader",  # noqa: S603
                    "--enable-unsafe-swiftshader", "--allow-file-access-from-files", "--virtual-time-budget=20000",
                    f"--window-size={width},{height}", f"--screenshot={grid_png}", html.as_uri()],
                   check=True, capture_output=True, timeout=180)
    from PIL import Image
    im = Image.open(grid_png)
    ids = [s["id"] for s in data["shots"]]
    for i, sid in enumerate(ids):
        r, c = divmod(i, cols)
        x, y = c * (CELL_W + GUTTER), r * (CELL_H + GUTTER)
        im.crop((x, y, x + CELL_W, y + CELL_H)).save(out / f"frame_{sid}.png")
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    args = ap.parse_args()
    scene = json.loads((HERE / "input" / f"{args.scene}.json").read_text(encoding="utf-8"))
    run = HERE / "runs" / args.run
    rec = SceneRecord.model_validate_json((run / "record.json").read_text(encoding="utf-8"))
    out = run / "previz"
    out.mkdir(parents=True, exist_ok=True)
    ids = render(rec, scene, out)
    shots = {s.id: s for s in rec.shots}
    cards = "".join(
        f"<section><h2>Shot {escape(i)} · camera {escape(shots[i].camera)} · {escape(shots[i].size)} "
        f"{escape(shots[i].type)}</h2><img src='frame_{escape(i)}.png'><p>{escape(shots[i].purpose)}</p></section>"
        for i in ids)
    (out / "review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>3D previz</title><style>body{font-family:system-ui;margin:16px}"
        "section{display:inline-block;vertical-align:top;margin:0 12px 16px 0;width:640px}img{width:640px;"
        "border:1px solid #222}h2{font-size:14px;margin:4px 0}p{font-size:12px;color:#555}</style>"
        f"<h1>3D blocking previz: {escape(scene['title'])}</h1><p>Each shot rendered from its camera on the floor "
        "plan (position, height, lens). Grey place, coloured mannequins, white props. Free, no AI.</p>" + cards,
        encoding="utf-8")
    print(f"{len(ids)} frames -> {out / 'review.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
