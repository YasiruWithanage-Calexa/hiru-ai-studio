"""Scenes for the camera_moves lab, in ONE shape, from (a) a saved scene packet + a Raphael result (the product's
planner output, saved by earlier labs: no planner call) or (b) a scene read from the database (scene_read.py, GET only).

The shape (plain dicts):
    sid, title, heading, summary, purpose, place, exterior, mood[], direction[] (the production's own style lines),
    people[{name, presence, wants, start, end}], script[{n, kind, who, to, text, intent, delivery}],
    clips[{slate, setup, role, size, take_s, h_in, h_out, sound, speaks, technique, movement, rig, angle, lens,
           why, summary, subjects[{desc, where, does}], heard[], opening, beats[{time, action}],
           spoken[{id, who, secs}]}],
    camera_line{slate: today's `Camera:` text} (database scenes only)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
Row = dict[str, Any]

# name -> (packets json, raphael result json, packet key)
SAVED: dict[str, tuple[Path, Path, str]] = {
    "ekama_s01": (ROOT / "lab/two_memories/runs/pipeline_ekama_run2/09_packets.json",
                  ROOT / "lab/two_memories/runs/pipeline_ekama_run3/12_raphael/E01-S01.json", "E01-S01"),
    "ekama_s02": (ROOT / "lab/two_memories/runs/pipeline_ekama_run2/09_packets.json",
                  ROOT / "lab/two_memories/runs/pipeline_ekama_run3/12_raphael/E01-S02.json", "E01-S02"),
    "ekama_s03": (ROOT / "lab/two_memories/runs/pipeline_ekama_run2/09_packets.json",
                  ROOT / "lab/two_memories/runs/pipeline_ekama_run3/12_raphael/E01-S03.json", "E01-S03"),
    "apidenna_s02": (ROOT / "lab/llm_reader/runs/e2e/05_packets.json",
                     ROOT / "lab/llm_reader/runs/e2e/12_raphael/E01-S02.json", "E01-S02"),
    "apidenna_s04": (ROOT / "lab/llm_reader/runs/e2e/05_packets.json",
                     ROOT / "lab/llm_reader/runs/e2e/12_raphael/E01-S04.json", "E01-S04"),
    "chase": (HERE / "story/chase_packet.json", HERE / "runs/chase_raphael/12_raphael/E09-S01.json", "E09-S01"),
}
CAMERA_DIRECTION = re.compile(r"locked[- ]off|static|handheld|smooth camera|camera movement|tripod|steadicam|"
                              r"long takes?|tracking|dolly|crane", re.I)


def secs(text: str) -> float:
    """lab/sinhala_pace: Omni starts near 1 s, ~2.6 words/s, ~0.8 s between sentences."""
    body = text.strip().strip("\"“”").strip()
    sentences = max(1, len(re.findall(r"[.?!…]+", body)))
    return round(1.0 + len(body.split()) / 2.6 + 0.8 * (sentences - 1), 1)


def _text(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("value") or v.get("empty") or "")
    return str(v or "")


def from_saved(name: str) -> Row:
    packets_file, result_file, key = SAVED[name]
    packet = json.loads(packets_file.read_text(encoding="utf-8"))[key]
    saved = json.loads(result_file.read_text(encoding="utf-8"))
    result = saved["result"]
    names = {k: v.get("name", k) for k, v in (packet.get("ids") or {}).items()}
    for p in packet["B_people"]:
        names.setdefault(p["id"], p["name"])
    presence = {p["id"]: p.get("presence", "") for p in packet["B_people"]}
    blocks = packet["E_blocks"]
    by_block = {b["id"]: b for b in blocks}
    short = {v: k for k, v in (saved.get("ids") or {}).items() if k.startswith("L")}  # block id -> L4
    line_block = {k: by_block.get(v) for k, v in (saved.get("ids") or {}).items() if k.startswith("L")}
    a = packet["A_scene"]
    script = []
    for i, b in enumerate(blocks):
        script.append({"n": short.get(b["id"], f"b{i}"), "kind": b["kind"], "who": names.get(b.get("speaker"), ""),
                       "to": names.get(b.get("addressee"), ""), "text": b["text"], "intent": b.get("intent", ""),
                       "delivery": b.get("delivery_hint", ""),
                       "through": b.get("device", "") or ("phone" if b.get("presence") == "phone" else "")})
    clips = []
    for c in cut_order(result):  # the product's own cut order (raphael_write.order)
        ir = c.get("ir") or {}
        cine = ir.get("cinematography") or {}
        spoken = []
        heard = []
        for lid in c.get("lines") or []:
            b = line_block.get(str(lid))
            if not b:
                continue
            who = names.get(b.get("speaker"), "")
            if c.get("speaks"):
                spoken.append({"id": str(lid), "who": who, "secs": secs(b["text"])})
            if presence.get(b.get("speaker")) not in ("on_screen", "") and who not in heard:
                heard.append(who)
        clips.append(_clip(c, ir, cine, spoken, heard))
    heading = a.get("heading", "")
    return {"sid": f"{name} ({key})", "title": a.get("title", ""), "heading": heading,
            "summary": a.get("summary", ""), "purpose": a.get("purpose", ""),
            "place": _text(packet["C_place"].get("name")), "exterior": _exterior(heading),
            "mood": list((packet.get("F_feeling") or {}).get("mood") or []),
            "direction": [" ".join(d["text"].split()) for d in packet.get("G_direction") or []],
            "people": [{"name": p["name"], "presence": p.get("presence", ""), "wants": p.get("wants", ""),
                        "start": p.get("feeling_start", ""), "end": p.get("feeling_end", "")}
                       for p in packet["B_people"]],
            "script": script, "clips": clips, "camera_line": {}}


def cut_order(result: Row) -> list[Row]:
    """The clips in the order of the intended cut, by the product's `raphael_write.order` (moment, must before
    cinematic, a cinematic clip whose blend note opens a moment ahead of it)."""
    import sys

    sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src")]
    from contracts.raphael.stored import StoredRaphael
    from hiru_ai.steps.raphael.raphael_write.logic import order

    stored = StoredRaphael.model_validate(result)
    by_id = {str(c.get("id")): c for c in result["clips"]}
    return [by_id[c.id] for c in order(stored.clips, stored.blend_notes)]


def _exterior(heading: str) -> bool:
    h = heading.upper()
    return " EXT" in f" {h}" or h.startswith(("EXT", "I/E")) or "EXT." in h


def _clip(c: Row, ir: Row, cine: Row, spoken: list[Row], heard: list[str]) -> Row:
    ff = ir.get("first_frame") or {}
    return {"slate": str(c.get("slate")), "setup": str(c.get("setup") or str(c.get("slate", "?"))[1:2]),
            "role": str(c.get("role") or ""), "size": str(c.get("size") or ""), "take_s": float(c.get("take_s") or 0),
            "h_in": float(c.get("handle_in_s") or 0), "h_out": float(c.get("handle_out_s") or 0),
            "sound": "dialogue" if c.get("speaks") else "ambient", "speaks": bool(c.get("speaks")),
            "technique": str(c.get("technique") or ""), "movement": str(cine.get("movement") or ""),
            "rig": str(cine.get("camera") or ""), "angle": str(c.get("angle") or cine.get("angle") or ""),
            "lens": str(c.get("lens") or ""), "why": str(c.get("why") or ""), "summary": str(c.get("summary") or ""),
            "subjects": [{"desc": s.get("description", ""), "where": s.get("position", ""), "does": s.get("action", "")}
                         for s in ir.get("subjects") or []],
            "heard": heard, "opening": str(ff.get("composition") or ""),
            "beats": [{"time": b.get("time", ""), "action": b.get("action", "")} for b in ir.get("beats") or []],
            "spoken": spoken}


def from_db(name: str) -> Row:
    """A scene read by scene_read.py (GET only)."""
    d = json.loads((HERE / "runs" / f"db_{name}" / "scene.json").read_text(encoding="utf-8"))
    scene, shots, lines = d["scene"], d["shots"], d["lines"]
    names = {c["id"]: c["name"] for c in d["canon"]}
    by_line = {ln["id"]: ln for ln in lines}
    script = []
    for i, b in enumerate(scene.get("script") or []):
        ln = by_line.get(b.get("line_id") or "")
        script.append({"n": f"L{ln['ord'] + 1}" if ln else f"b{i}", "kind": b.get("kind", ""),
                       "who": (ln or {}).get("speaker", ""), "to": "", "text": (ln or {}).get("text") or b.get("text", ""),
                       "intent": "", "delivery": (ln or {}).get("delivery", ""), "through": ""})
    clips, camera_line = [], {}
    for s in shots:
        ir = s.get("ir") or {}
        cine = ir.get("cinematography") or {}
        own = (scene.get("script") or [])[int(s.get("block_start") or 0): int(s.get("block_end") or 0) + 1]
        spoken = [{"id": f"L{by_line[b['line_id']]['ord'] + 1}", "who": by_line[b["line_id"]]["speaker"],
                   "secs": secs(by_line[b["line_id"]]["text"])}
                  for b in own if b.get("line_id") in by_line] if s.get("sound_mode") in ("dialogue", "voiceover") \
            else []
        intent = s.get("intent") or {}
        c = {"slate": s.get("slate") or f"#{s['number']}", "setup": str(s.get("slate") or "?")[1:2],
             "role": s.get("role") or "", "size": s.get("framing") or "", "take_s": s.get("duration_s") or 0,
             "handle_in_s": s.get("handle_in_s") or 0, "handle_out_s": s.get("handle_out_s") or 0,
             "speaks": bool(spoken), "technique": cine.get("movement", ""), "angle": cine.get("angle", ""),
             "lens": ((s.get("design") or {}).get("recommended") or {}).get("lens", ""),
             "why": intent.get("purpose", ""), "summary": intent.get("story", "") + " " + intent.get("what_we_see", "")}
        heard = [names.get(h, h) for h in intent.get("heard_only") or []]
        clip = _clip(c, ir, cine, spoken, heard)
        clip["sound"] = s.get("sound_mode") or clip["sound"]
        clips.append(clip)
        prose = (s.get("prompt") or {}).get("prose") or ""
        m = re.search(r"^Camera: .*$", prose, re.M)
        camera_line[clip["slate"]] = m.group(0) if m else ""
    people = [{"name": names.get(cid, cid), "presence": "on_screen", "wants": "", "start": "", "end": ""}
              for cid in dict.fromkeys(x for s in shots for x in ((s.get("intent") or {}).get("on_screen") or []))]
    heading = scene.get("heading", "")
    direction = [b["text"] for b in scene.get("script") or [] if b.get("kind") == "action"
                 and CAMERA_DIRECTION.search(b.get("text", ""))]
    return {"sid": f"db {name}", "title": scene.get("title", ""), "heading": heading,
            "summary": d["production"].get("summary") or "", "purpose": "", "place": "",
            "exterior": _exterior(heading), "mood": [], "direction": direction, "people": people, "script": script,
            "clips": clips, "camera_line": camera_line}


def load(name: str) -> Row:
    return from_db(name[3:]) if name.startswith("db_") else from_saved(name)
