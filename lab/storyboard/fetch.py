"""Read ONE scene out of the hosted dev database into `input/<name>/` (read-only: GET requests only).

What is kept is what a storyboard writer needs, never a first-frame prompt: the scene (heading, script, mood, the camera
axis, the staging map), every shot's plan (role, size, lens, angle, purpose, setting, composition, subjects, light,
beats), the canon the shots name (people with their look for this scene, the place and its spots, the props) and the
reference pictures (look sheets, the location plate, prop sheets). Pictures are saved once; a second fetch reuses them.

    .venv/Scripts/python.exe lab/storyboard/fetch.py --scene <scene id> --name scene1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts.frame_brief import black_plate  # noqa: E402


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class Db:
    def __init__(self) -> None:
        e = env()
        self.url = e["SUPABASE__URL"].rstrip("/")
        key = e["SUPABASE__SERVICE_ROLE_KEY"]
        self.http = httpx.Client(headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60)

    def rows(self, table: str, query: str) -> list[dict[str, Any]]:
        r = self.http.get(f"{self.url}/rest/v1/{table}?{query}")
        r.raise_for_status()
        return list(r.json())

    def file(self, bucket: str, path: str) -> bytes:
        r = self.http.get(f"{self.url}/storage/v1/object/{bucket}/{path}")
        r.raise_for_status()
        return r.content


def _last_asset(assets: Any) -> str:
    items = [a for a in (assets or []) if isinstance(a, dict) and a.get("path")]
    return str(items[-1]["path"]) if items else ""


def fetch(scene_id: str, name: str) -> Path:
    db = Db()
    out = HERE / "input" / name
    (out / "refs").mkdir(parents=True, exist_ok=True)

    scene = db.rows("scenes", f"id=eq.{scene_id}&select=*")[0]
    shots = db.rows("shots", f"scene_id=eq.{scene_id}&select=*&order=number")
    script = scene.get("script") or []
    canon = db.rows("canon_entities", f"production_id=eq.{scene['production_id']}&select=*")
    versions = {r["id"]: r for r in db.rows(
        "canon_versions", f"production_id=eq.{scene['production_id']}&select=id,entity_id,card,reference_assets")}
    looks_by_entity = {r["entity_id"]: r for r in db.rows("scene_looks", f"scene_id=eq.{scene_id}&select=*")}
    look_rows = {r["id"]: r for r in db.rows(
        "canon_looks", f"production_id=eq.{scene['production_id']}&select=*")}
    by_id = {c["id"]: c for c in canon}
    # The spoken lines, by shot: who says what, verbatim (the board never draws them; they tell the writer who is
    # talking in a panel, which decides faces, eyelines and whether a mouth is open).
    spoken: dict[str, list[dict[str, str]]] = {}
    for d in db.rows("dialogue_lines", f"scene_id=eq.{scene_id}&select=shot_id,speaker,text,delivery&order=ord"):
        if d.get("shot_id"):
            spoken.setdefault(str(d["shot_id"]), []).append(
                {k: str(d[k]) for k in ("speaker", "text", "delivery") if d.get(k)})

    def card(eid: str) -> dict[str, Any]:
        v = versions.get(str(by_id[eid].get("current_version_id") or ""))
        return (v or {}).get("card") or {}

    def plate(eid: str) -> str:
        v = versions.get(str(by_id[eid].get("current_version_id") or ""))
        return _last_asset((v or {}).get("reference_assets"))

    # Who and what the shots name.
    named: set[str] = set()
    plan_shots = []
    all_shots = []  # every shot of the scene in order, painted or not: the numbered sheet holds them all
    for s in shots:
        blocks = list(range(int(s.get("block_start") or 0), int(s.get("block_end") or 0)))
        texts = [str(script[b].get("text") or "") for b in blocks if b < len(script)]
        painted = not black_plate(texts)
        all_shots.append({"number": s["number"], "slate": s.get("slate"), "painted": painted, "text": " ".join(texts)})
        if not painted:
            continue  # a cut to black or a title card is made by code, never painted
        ir, intent = s.get("ir") or {}, s.get("intent") or {}
        named.update(str(x) for x in intent.get("on_screen") or [])
        plan_shots.append({
            "number": s["number"], "slate": s.get("slate"), "role": s.get("role"), "size": s.get("framing"),
            "duration_s": s.get("duration_s"), "script_lines": texts, "spoken": spoken.get(str(s["id"]), []),
            "story": intent.get("story", ""), "purpose": intent.get("purpose", ""),
            "on_screen": [by_id[c]["name"] for c in intent.get("on_screen") or [] if c in by_id],
            "setting": ir.get("setting", ""),
            "composition": (ir.get("first_frame") or {}).get("composition", ""),
            "opening_picture": (ir.get("first_frame") or {}).get("subjects", []),
            "subjects": [{k: v for k, v in sub.items() if k in ("id", "action", "position")}
                         for sub in ir.get("subjects") or []],
            "cinematography": ir.get("cinematography") or {},
            "lighting": ir.get("lighting", ""),
            "beats": [b.get("action", "") for b in ir.get("beats") or []],
        })

    # People: the look this scene puts them in (outfit, hair) and the look sheet; the condition is the scene's.
    people, refs = [], []
    for eid in sorted(named):
        c = by_id.get(eid)
        if not c or c["kind"] != "character":
            continue
        cd = card(eid)
        sl = looks_by_entity.get(eid)
        lk = look_rows.get(str(sl["look_id"])) if sl else None
        people.append({"name": c["name"], "appearance": cd.get("appearance", ""),
                       "outfit": (lk or {}).get("outfit", ""), "hair": (lk or {}).get("hair", ""),
                       "accessories": (lk or {}).get("accessories", ""),
                       "scene_condition": (sl or {}).get("condition", "")})
        path = _last_asset((lk or {}).get("sheet_assets")) if lk else ""
        if path:
            refs.append({"role": "look", "name": c["name"], "bucket": "references", "path": path})

    # The place: the scene's set, its spots (no plates: spots are never painted), and the set's plate.
    loc_id = str(scene["location_id"])
    place = {"name": by_id[loc_id]["name"], "look": card(loc_id).get("look", ""),
             "spots": [{"name": c["name"], "look": card(c["id"]).get("look", "")}
                       for c in canon if c.get("parent_id") == loc_id and c.get("class") == "spot"]}
    if plate(loc_id):
        refs.append({"role": "place", "name": place["name"], "bucket": "references", "path": plate(loc_id)})

    # Props the shots carry: every prop with a sheet that a shot's text names.
    blob = json.dumps(plan_shots, ensure_ascii=False).lower()
    props = []
    for c in canon:
        if c["kind"] == "prop" and c["name"].lower() in blob:
            cd = card(c["id"])
            props.append({"name": c["name"], "details": cd.get("details", "")})
            if plate(c["id"]):
                refs.append({"role": "prop", "name": c["name"], "bucket": "references", "path": plate(c["id"])})

    for n, ref in enumerate(refs, start=1):
        target = out / "refs" / f"{n:02d}_{ref['role']}_{ref['name'].replace(' ', '_')}.png"
        if not target.exists():
            target.write_bytes(db.file(ref["bucket"], ref["path"]))
        ref["file"] = str(target.relative_to(HERE)).replace("\\", "/")

    bundle = {
        "scene": {"id": scene_id, "heading": scene["heading"], "title": scene.get("title"),
                  "time_of_day": scene.get("time_of_day"), "script": [s.get("text") for s in script if s.get("text")],
                  "mood": (scene.get("raphael") or {}).get("mood", []),
                  "axis": (scene.get("coverage") or {}).get("axis", ""),
                  "staging": [{k: m[k] for k in ("who", "zone", "block", "posture", "holding") if m.get(k)}
                              for m in (scene.get("staging") or {}).get("marks", [])]},
        "people": people, "place": place, "props": props, "shots": plan_shots, "all_shots": all_shots,
        "references": refs,
    }
    (out / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    out = fetch(a.scene, a.name)
    b = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
    print(f"{out}: {len(b['shots'])} shots, {len(b['references'])} references")
    for r in b["references"]:
        print("  ", r["role"], r["name"], r["file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
