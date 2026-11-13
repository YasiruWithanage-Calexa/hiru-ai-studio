"""Fill one production with dummy episodes, scenes, shots, lines, frames, prompts and takes (no model calls).
Writes to the hosted dev project named in the backend's .env. Plan/2026-11-13b PLAN.md section 3.

    python seed.py media     # makes the dummy pictures and MP4s with ffmpeg (media/)
    python seed.py seed      # writes manifest.json beside this file
    python seed.py ids       # writes ids.json for walk.js
    python seed.py clean     # removes everything manifest.json lists (and the bot user), and clean-create's rows
    python seed.py create-prod   # plan/2026-11-13d: a new production traffic-create-<time>, the bot its director
                                 # (written to ../../2026-11-13d/measure/create.json for create.js)
    python seed.py clean-create   # plan/2026-11-13d: every production named traffic-create-*, its files and rows
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _common  # noqa: E402

_common.load_env()
import os  # noqa: E402

import httpx  # noqa: E402

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media"
MANIFEST = HERE / "manifest.json"
P = "bac48f6d-e702-499b-9983-7ca73bf02ba8"
BOT_EMAIL = "traffic-bot@hiru.test"
BOT_PASSWORD = "TrafficBot-" + hashlib.sha1(b"hiru-traffic").hexdigest()[:10]

r = _common.Rest()
URL = os.environ["SUPABASE__URL"].rstrip("/")
H = r.h
rng = random.Random(7)


def ins(table: str, rows: list[dict] | dict) -> list[dict]:
    res = r.c.post(f"{r.rest}/{table}", headers={**H, "Prefer": "return=representation"}, json=rows)
    if res.status_code >= 400:
        raise SystemExit(f"{table}: {res.status_code} {res.text[:500]}")
    return res.json()


def patch(table: str, row_id: str, values: dict) -> None:
    res = r.c.patch(f"{r.rest}/{table}", headers=H, params={"id": f"eq.{row_id}"}, json=values)
    if res.status_code >= 400:
        raise SystemExit(f"{table} patch: {res.status_code} {res.text[:500]}")


def upload(bucket: str, path: str, file: Path, mime: str) -> None:
    res = r.c.post(f"{r.storage}/object/{bucket}/{path}", content=file.read_bytes(),
                   headers={**H, "Content-Type": mime, "x-upsert": "true"})
    if res.status_code >= 400:
        raise SystemExit(f"upload {bucket}/{path}: {res.status_code} {res.text[:300]}")


def bot_user() -> str:
    found = r.get("profiles", email=f"eq.{BOT_EMAIL}", select="id")
    if found:
        uid = found[0]["id"]
    else:
        res = r.c.post(f"{URL}/auth/v1/admin/users", headers=H, json={
            "email": BOT_EMAIL, "password": BOT_PASSWORD, "email_confirm": True,
            "user_metadata": {"display_name": "Traffic Bot"}})
        if res.status_code >= 400:
            raise SystemExit(f"create user: {res.status_code} {res.text[:300]}")
        uid = res.json()["id"]
        if not r.get("profiles", id=f"eq.{uid}", select="id"):
            ins("profiles", {"id": uid, "email": BOT_EMAIL, "display_name": "Traffic Bot"})
    r.c.post(f"{r.rest}/production_members", headers={**H, "Prefer": "resolution=merge-duplicates"},
             json={"production_id": P, "user_id": uid, "role": "director"}).raise_for_status()
    return uid


CHARS = [("C01", "Nimal", "52", "male"), ("C02", "Kumari", "48", "female"), ("C03", "Sahan", "24", "male"),
         ("C04", "Dilini", "21", "female")]
LOCS = [("L01", "Nimal's house - verandah"), ("L02", "Village tea shop")]
LINES = ["ඔයා කොහෙද ගියේ?", "මම කඩේට ගියා.", "ඇයි මෙච්චර පරක්කු?", "පාරේ වැස්ස.", "හරි, ඇතුළට එන්න.",
         "අම්මා කෝ?", "එයා නිදි.", "අපි හෙට යමු.", "ඔව්, ඒක හොඳයි.", "මට බයයි."]
FRAMINGS = ["WIDE", "MS", "MCU", "CU", "TWO", "OTS"]


def seed() -> None:
    if MANIFEST.exists():
        raise SystemExit("manifest.json exists: clean first")
    m: dict = {"production": P, "storage": [], "episodes": [], "canon": [], "bot_email": BOT_EMAIL,
               "bot_password": BOT_PASSWORD}
    uid = bot_user()
    m["bot_id"] = uid
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")

    canon_ids: dict[str, str] = {}
    for code, name, *rest in CHARS + [(c, n) for c, n in LOCS]:
        kind = "character" if code.startswith("C") else "location"
        e = ins("canon_entities", {"production_id": P, "kind": kind, "code": code, "name": name, "core": True})[0]
        card = ({"summary": f"{name}, a character.", "age": rest[0], "gender": rest[1], "appearance": "dark hair",
                 "wardrobe": "cotton sarong and shirt" if rest[1] == "male" else "saree"}
                if kind == "character" else {"summary": name, "look": "whitewashed walls, red clay roof tiles"})
        v = ins("canon_versions", {"entity_id": e["id"], "production_id": P, "version": 1, "card": card,
                                   "card_hash": hashlib.sha1(json.dumps(card).encode()).hexdigest(),
                                   "source": "user"})[0]
        patch("canon_entities", e["id"], {"current_version_id": v["id"]})
        canon_ids[code] = e["id"]
        m["canon"].append(e["id"])
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")

    n_frames = n_takes = 0
    for ep_no in range(1, 4):
        ep = ins("episodes", {"production_id": P, "number": ep_no, "title": f"[traffic seed] Episode {ep_no}",
                              "synopsis": "Dummy episode for traffic measurement.", "status": "ready"})[0]
        m["episodes"].append(ep["id"])
        MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")
        for sc_no in range(1, 5):
            loc = canon_ids["L01" if sc_no % 2 else "L02"]
            scene = ins("scenes", {"production_id": P, "episode_id": ep["id"], "number": sc_no,
                                   "heading": f"EXT. {'VERANDAH' if sc_no % 2 else 'TEA SHOP'} - DAY",
                                   "title": f"Scene {ep_no}.{sc_no}", "location_id": loc, "time_of_day": "day",
                                   "envelope_s": 48, "status": "split"})[0]
            sid = scene["id"]
            speakers = ["C01", "C02"] if sc_no % 2 else ["C03", "C04"]
            line_rows = []
            for o in range(6):
                who = speakers[o % 2]
                text = LINES[(o + sc_no + ep_no) % len(LINES)]
                line_rows.append({"id": str(uuid.uuid4()), "production_id": P, "scene_id": sid, "ord": o,
                                  "speaker": dict((c[0], c[1]) for c in CHARS)[who], "character_id": canon_ids[who],
                                  "text": text, "words": len(text.split())})
            script = [{"kind": "action", "text": "Morning light. A dog barks in the distance."}]
            for ln in line_rows:
                script.append({"kind": "dialogue", "text": "", "line_id": ln["id"]})
            script.append({"kind": "action", "text": "They look at each other in silence."})
            patch("scenes", sid, {"script": script})
            ins("dialogue_lines", line_rows)

            start = 0
            for sh_no in range(1, 7):
                dur = rng.choice([4, 6, 8])
                ln = line_rows[sh_no - 1]
                shot = ins("shots", {"production_id": P, "scene_id": sid, "number": sh_no,
                                     "title": f"Shot {sh_no}", "framing": FRAMINGS[(sh_no + sc_no) % 6],
                                     "duration_s": dur, "start_s": start, "sound_mode": "dialogue",
                                     "speaker_id": ln["character_id"], "block_start": sh_no, "block_end": sh_no + 1,
                                     "words": ln["words"], "status": "prompt",
                                     "beats": [{"start_s": 0, "end_s": dur, "camera": "static",
                                                "action": "speaks the line"}]})[0]
                start += dur
                patch("dialogue_lines", ln["id"], {"shot_id": shot["id"], "beat_index": 0, "start_s": 0})
                # Frames: a draft and a final (accepted) for most shots; the last shot of a scene has none.
                if sh_no == 6:
                    continue
                pic = (ep_no + sc_no + sh_no) % 6
                frame_ids = {}
                for stage in ("draft", "final"):
                    fid = str(uuid.uuid4())
                    path = f"{P}/{shot['id']}/{fid}.png"
                    upload("frames", path, MEDIA / f"frame{pic}.png", "image/png")
                    upload("frames", path + ".thumb.webp", MEDIA / f"frame{pic}.thumb.webp", "image/webp")
                    m["storage"] += [["frames", path], ["frames", path + ".thumb.webp"]]
                    ins("first_frames", {"id": fid, "production_id": P, "shot_id": shot["id"], "status": "done",
                                         "storage_path": path, "prompt": "dummy frame (traffic seed)",
                                         "stage": stage, "draft_id": frame_ids.get("draft"),
                                         "accepted_at": "2026-11-13T00:00:00Z", "accepted_by": uid,
                                         "created_by": uid})
                    frame_ids[stage] = fid
                    n_frames += 1
                prompt = ins("video_prompts", {"production_id": P, "shot_id": shot["id"], "version": 1,
                                               "prose": f"Dummy prompt for shot {sh_no}.", "model": "Veo 3.1",
                                               "frame_id": frame_ids["final"], "created_by": uid})[0]
                # Takes on shots 1-3: two takes, the first accepted.
                if sh_no <= 3:
                    for k in range(2):
                        tid = str(uuid.uuid4())
                        v = (sh_no + k) % 3
                        path = f"{P}/{shot['id']}/{tid}.mp4"
                        upload("takes", path, MEDIA / f"take{v}.mp4", "video/mp4")
                        # No poster: the takes bucket allows video types only, so a real poster is never stored either.
                        m["storage"] += [["takes", path]]
                        ins("takes", {"id": tid, "production_id": P, "shot_id": shot["id"],
                                      "prompt_id": prompt["id"], "prompt_version": 1, "storage_path": path,
                                      "mime": "video/mp4", "bytes": (MEDIA / f"take{v}.mp4").stat().st_size,
                                      "duration_s": 6.0, "status": "accepted" if k == 0 else "uploaded",
                                      "accepted_at": "2026-11-13T00:00:00Z" if k == 0 else None,
                                      "accepted_by": uid if k == 0 else None, "uploaded_by": uid})
                        n_takes += 1
            MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")
            print(f"episode {ep_no} scene {sc_no}: 6 shots", flush=True)
    print(f"done: frames={n_frames} takes={n_takes} storage objects={len(m['storage'])}")


def create_prod() -> None:
    """The creation walk starts from a fresh, empty production. Creating one is an admin's act and the bot is a
    director, so it is made here with the service key, the way POST /v1/productions writes it."""
    import time

    from contracts.production import ProductionCreate

    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    body = ProductionCreate(title=f"traffic-create-{time.strftime('%Y%m%d-%H%M%S')}", orientation="horizontal")
    row = ins("productions", {**body.model_dump(mode="json"), "created_by": m["bot_id"]})[0]
    r.c.post(f"{r.rest}/production_members", headers=H,
             json={"production_id": row["id"], "user_id": m["bot_id"], "role": "director"}).raise_for_status()
    out = HERE.parents[1] / "2026-11-13d" / "measure" / "create.json"
    out.write_text(json.dumps({"P": row["id"], "title": row["title"], "email": m["bot_email"],
                               "password": m["bot_password"]}, indent=1), encoding="utf-8")
    print(f"{row['title']} {row['id']}")


def clean_create() -> None:
    """The creation walk's productions (plan/2026-11-13d section 8). Rows cascade from the production; files do not."""
    for prod in r.get("productions", title="like.traffic-create-*", select="id,title"):
        pid = prod["id"]
        for bucket in ("documents", "frames", "references", "takes"):
            paths: list[str] = []
            stack = [pid]
            while stack:
                prefix = stack.pop()
                res = r.c.post(f"{r.storage}/object/list/{bucket}", headers=H,
                               json={"prefix": prefix + "/", "limit": 1000})
                res.raise_for_status()
                for o in res.json():
                    (paths if o.get("id") else stack).append(f"{prefix}/{o['name']}")
            for i in range(0, len(paths), 100):
                r.c.request("DELETE", f"{r.storage}/object/{bucket}", headers=H,
                            json={"prefixes": paths[i:i + 100]}).raise_for_status()
        r.delete("productions", id=f"eq.{pid}")
        print(f"removed {prod["title"]} ({pid})")


def clean() -> None:
    clean_create()
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_bucket: dict[str, list[str]] = {}
    for bucket, path in m["storage"]:
        by_bucket.setdefault(bucket, []).append(path)
    for bucket, paths in by_bucket.items():
        for i in range(0, len(paths), 100):
            r.c.request("DELETE", f"{r.storage}/object/{bucket}", headers=H,
                        json={"prefixes": paths[i:i + 100]}).raise_for_status()
    for eid in m["episodes"]:
        r.delete("episodes", id=f"eq.{eid}")
    for cid in m["canon"]:
        r.delete("canon_entities", id=f"eq.{cid}")
    if m.get("bot_id"):
        r.delete("production_members", production_id=f"eq.{P}", user_id=f"eq.{m['bot_id']}")
        httpx.delete(f"{URL}/auth/v1/admin/users/{m['bot_id']}", headers=H).raise_for_status()
    MANIFEST.unlink()
    print("cleaned")


def media() -> None:
    MEDIA.mkdir(exist_ok=True)
    colors = ["0x3b5b7a", "0x7a3b4f", "0x4f7a3b", "0x7a6a3b", "0x3b7a74", "0x5b3b7a"]
    q = ["ffmpeg", "-loglevel", "error", "-y"]
    for i, c in enumerate(colors):
        png = str(MEDIA / f"frame{i}.png")
        subprocess.run([*q, "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=1", "-f", "lavfi", "-i",
                        f"color=c={c}:size=1280x720", "-filter_complex", "[0][1]blend=all_mode=overlay:all_opacity=0.6",
                        "-frames:v", "1", png], check=True)
        subprocess.run([*q, "-i", png, "-vf", "scale=640:-1", "-c:v", "libwebp", "-quality", "70",
                        str(MEDIA / f"frame{i}.thumb.webp")], check=True)
    for i in range(3):
        subprocess.run([*q, "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24", "-f", "lavfi", "-i",
                        f"sine=frequency={300 + i * 120}:sample_rate=44100", "-t", "6", "-c:v", "libx264", "-preset",
                        "veryfast", "-crf", "35", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k", "-movflags",
                        "+faststart", str(MEDIA / f"take{i}.mp4")], check=True)
    print("media ready")


def ids() -> None:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    eps = r.get("episodes", production_id=f"eq.{P}", select="id,number", order="number")
    scenes = r.get("scenes", production_id=f"eq.{P}", select="id,episode_id,number", order="number")
    shots = r.get("shots", production_id=f"eq.{P}", select="id,scene_id,number", order="number")
    canon = r.get("canon_entities", production_id=f"eq.{P}", select="id,code", order="code")
    out = {"P": P, "email": m["bot_email"], "password": m["bot_password"], "canon": [c["id"] for c in canon],
           "episodes": [{"id": e["id"], "scenes": [
               {"id": s["id"], "shots": [x["id"] for x in shots if x["scene_id"] == s["id"]]}
               for s in scenes if s["episode_id"] == e["id"]]} for e in eps]}
    (HERE / "ids.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("ids.json written")


if __name__ == "__main__":
    {"seed": seed, "clean": clean, "media": media, "ids": ids, "create-prod": create_prod,
     "clean-create": clean_create}[sys.argv[1]]()
