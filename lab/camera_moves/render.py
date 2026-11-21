"""First-frame renders of the Camera agent's design on the person's own scene (db_url_scene): does Omni perform the
moves when it starts from the shot's accepted first frame with the people's face and look sheets, as the product
renders (plan/2026-11-18: variant C, `reference_to_video`)?

    .venv/Scripts/python.exe lab/camera_moves/render.py --slates 2B-1,2I-1            fetch (GET only) + dry requests
    .venv/Scripts/python.exe lab/camera_moves/render.py --slates 2B-1,2I-1 --yes      PAID: one 360p take each

The prompt is the shot's own latest video prompt from the database, word for word, with ONLY its `Camera:` line
swapped for the Camera agent's sentence (runs/db_url_scene/answer.json). Reading is GET only (lab/portrait_board Rest);
nothing is written to the database. The request body and the send are lab/omni_refs' own (`build.request_b` with
task reference_to_video, `run.send`). Writes runs/render/<slate>/: frame.png, face_*.png, look_*.png, shot.json,
prompt_before.txt, prompt.txt, request.json, take.mp4, usage.json, stills/. A slate with a take is never sent again.
Money: wallet.py omni ($2.00, counted at the 720p ceiling rate $0.10/s).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "lab" / "portrait_board"), str(ROOT / "src" / "libs"),
                str(ROOT / "src" / "services" / "video_render")]

from fetch import Rest  # noqa: E402  lab/portrait_board's read-only helper (GET only); before omni_refs is loaded
from wallet import Wallet  # noqa: E402

RATE_720P = 0.10
OUT = HERE / "runs" / "render"
# CAPABILITY TESTS (not the agent's choice, labelled so in the report): moves Omni has never been measured on, on
# this scene's own first frames. 2I-1: a small push that stays in close-up (the agent chose a hold). 2A-1: an arc
# around two people (the agent chose a push; only 2A-1, 2I-1 and 2B-1 have a video prompt in the database).
TESTS = {
    "2I-1": "Eye-level close-up of the visitor; the camera creeps slowly closer as he gives his small nod, staying a "
            "close-up with his face a little larger in the frame.",
    "2A-1": "Eye-level two-shot; the camera arcs slowly to the right around the two managers as the welcome begins, "
            "the office sliding past behind them, ending on a three-quarter two-shot.",
}


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod  # a dataclass looks its module up while the module runs
    spec.loader.exec_module(mod)
    return mod


def _asset(assets: list[dict], kind: str) -> str | None:
    return next((a["path"] for a in assets or [] if a.get("kind") == kind and a.get("path")), None)


def fetch(rest, shot_id: str, out: Path) -> dict:
    """lab/omni_refs/fetch.py's reading (GET only), written into this lab's folder."""
    shot = rest.rows("shots", {"id": f"eq.{shot_id}", "select": "id,number,production_id,ir,duration_s"})[0]
    prod = rest.rows("productions", {"id": f"eq.{shot['production_id']}", "select": "*"})[0]
    prompt = rest.rows("video_prompts", {"shot_id": f"eq.{shot_id}", "select": "id,version,prose",
                                         "order": "version.desc", "limit": "1"})[0]
    frames = rest.rows("first_frames", {"shot_id": f"eq.{shot_id}", "status": "eq.done", "select": "*",
                                        "order": "accepted_at.desc.nullslast,created_at.desc"})
    frame = next((f for f in frames if f.get("accepted_at")), frames[0])
    (out / "frame.png").write_bytes(rest.file("frames", frame["storage_path"]))
    codes = [s["id"] for s in (shot.get("ir") or {}).get("subjects") or [] if s.get("id")]
    people = []
    if codes:
        canon = rest.rows("canon_entities", {
            "production_id": f"eq.{shot['production_id']}", "code": f"in.({','.join(codes)})",
            "select": "id,name,code,kind,current:canon_versions!canon_entities_current_version_fkey(version,"
                      "reference_assets)"})
        pinned = ((frame.get("pins") or {}).get("looks")) or {}
        for code in codes:
            row = next((r for r in canon if r["code"] == code), None)
            if row is None or row["kind"] != "character":
                continue
            assets = (row.get("current") or {}).get("reference_assets") or []
            face = _asset(assets, "face") or _asset(assets, "sheet")
            look_id = (pinned.get(row["id"]) or {}).get("id")
            look = rest.rows("canon_looks", {"id": f"eq.{look_id}", "select": "*"})[0] if look_id else None
            look_path = _asset(look["sheet_assets"], "look") if look else _asset(assets, "sheet")
            if not face or not look_path:
                continue
            (out / f"face_{code}.png").write_bytes(rest.file("references", face))
            (out / f"look_{code}.png").write_bytes(rest.file("references", look_path))
            people.append({"code": code, "name": row["name"], "look_name": look["name"] if look else "base sheet",
                           "outfit": look.get("outfit") if look else None,
                           "accessories": look.get("accessories") if look else None})
    video = ((prod.get("settings") or {}).get("video") or {})
    return {"shot_id": shot_id, "shot_number": shot["number"], "duration_s": shot["duration_s"],
            "aspect_ratio": video.get("aspect_ratio") or prod.get("aspect_ratio") or "9:16",
            "prompt_id": prompt["id"], "prompt_version": prompt["version"], "prose": prompt["prose"],
            "frame_id": frame["id"], "people": people}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slates", required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    slates = [s.strip() for s in args.slates.split(",") if s.strip()]
    scene = json.loads((HERE / "runs" / "db_url_scene" / "scene.json").read_text(encoding="utf-8"))
    design = {c["slate"]: c for c in
              json.loads((HERE / "runs" / "db_url_scene" / "answer.json").read_text(encoding="utf-8"))["answer"]["clips"]}
    shot_of = {s.get("slate"): s for s in scene["shots"]}
    build = _module("omni_build", ROOT / "lab" / "omni_refs" / "build.py")
    sender = _module("omni_run", ROOT / "lab" / "omni_refs" / "run.py")
    rest = Rest()
    todo = []
    for slate in slates:
        out = OUT / slate
        out.mkdir(parents=True, exist_ok=True)
        meta_file = out / "shot.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        else:
            meta = fetch(rest, shot_of[slate]["id"], out)
            meta_file.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        c = design[slate]
        sentence = TESTS.get(slate) or c["camera_sentence"]
        before = meta["prose"]
        after, n = re.subn(r"^Camera: .*$", lambda _m: f"Camera: {sentence}", before, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{slate}: no Camera: line in its prompt")
        (out / "prompt_before.txt").write_text(before, encoding="utf-8")
        req = build.request_b({**meta, "prose": after}, task="reference_to_video")
        (out / "prompt.txt").write_text(req["prompt"], encoding="utf-8")
        (out / "request.json").write_text(json.dumps(build.body(req, out, with_bytes=False), indent=1,
                                                     ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{slate}: {meta['duration_s']} s {meta['aspect_ratio']}, {len(req['images'])} image(s); {c['moment']} "
              f"{c['intensity']}: {c['move']} {c['speed']}, {c['angle']}/{c['height']}"
              f"{'  [have take]' if have else ''}")
        print(f"   Camera{' (CAPABILITY TEST)' if slate in TESTS else ''}: {sentence}")
        if not have:
            todo.append((slate, req, out, int(meta["duration_s"])))
    cost = sum(s for *_, s in todo) * RATE_720P
    wallet = Wallet("omni")
    if not wallet.allow_usd(cost, f"{len(todo)} take(s)") or not args.yes:
        return 0
    for slate, req, out, secs in todo:
        usage = sender.send(req, out, out)
        wallet.add_usd(f"render {slate}", secs * RATE_720P, {"tokens": usage["tokens"]})
        print(f"  {slate} done in {usage['seconds_waited']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
