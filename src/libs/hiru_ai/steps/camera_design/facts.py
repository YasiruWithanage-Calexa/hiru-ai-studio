"""What the Camera agent is told about a scene and its clips, read from the shot producer's own inputs (the `serialize`
step's `SceneInput` / `ShotInput`, reached by id) and Raphael's stored clips (plan/2026-11-20c §4).

    scene_text(scene, packet, prod)        -> the <scene> part: the packet's (the video prompt step's own scene brief)
                                              when the scene has one, else one from the scene's rows
    lids_of(scene, packet, line_rows)      -> line row id -> the short id the scene part uses (L<n>)
    clip_facts(shot, scene, lids, mood)    -> the dict `brief`, `kb` and `gates` read for one clip

Raphael's stored clip (by slate) gives the planner's finer size (MWS, ECU ...), setup letter, angle, lens, technique,
why and summary; a shot of another planner, or one a chat turn made, reads them from its own rows.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hiru_ai.core import parts
from hiru_ai.steps.camera_design import merge

Row = dict[str, Any]


def stored_clip(scene: Any, shot: Any) -> Row:
    stored = (scene.row or {}).get("raphael") or {}
    slate = str(shot.row.get("slate") or "")
    if not slate or not isinstance(stored, Mapping):
        return {}
    return next((dict(c) for c in stored.get("clips") or [] if isinstance(c, Mapping) and c.get("slate") == slate), {})


def lids_of(scene: Any, packet: Row | None, line_rows: list[Row]) -> dict[str, str]:
    """Line row id -> L<n>: the packet's own ids when it pairs with the lines (the video prompt brief's), else the
    block number of each line in the scene's items."""
    if packet is not None:
        got = parts.step("video_prompt", "facts").line_ids_for(packet, line_rows)
        if got is not None:
            return dict(got)
    return {str(i.line_id): f"L{i.index}" for i in scene.items if i.is_line and i.line_id}


def scene_text(scene: Any, packet: Row | None, prod: Any) -> str:
    """The <scene> part. With a packet: the video prompt step's own scene brief (who wants and feels what, every block
    in order with its line id). Without: the heading, the episode around it and the script's blocks in order."""
    if packet is not None:
        return str(parts.step("video_prompt", "logic").scene_brief(
            {"packet": packet, "genre": getattr(prod, "genre", ""), "style_note": getattr(prod, "style_note", "")}))
    out = ["<scene>", f"Scene {scene.number}: {scene.heading}" + (f" — {scene.title}" if scene.title else "")]
    if scene.synopsis:
        out.append(f"The episode: {scene.synopsis}")
    if scene.before:
        out.append(f"Just before: {scene.before}")
    if scene.after:
        out.append(f"Next: {scene.after}")
    names = list(dict.fromkeys(c.name for s in scene.shots for c in s.cast))
    if names:
        out.append(f"People: {', '.join(names)}.")
    out.append("Script, in order (a line's id is the name you use for it):")
    for i in scene.items:
        if i.is_line:
            out.append(f"L{i.index} {str(i.speaker or '').title()}" + (f" ({i.delivery})" if i.delivery else ""))
        elif i.text:
            out.append(f"[{i.kind}] {i.text}")
    out.append("</scene>")
    return "\n".join(out)


def _subjects(ir: Row) -> list[Row]:
    return [{k: str(s.get(k) or "") for k in ("description", "position", "action")}
            for s in ir.get("subjects") or [] if isinstance(s, Mapping)]


def clip_facts(shot: Any, scene: Any, lids: Mapping[str, str], *, mood: str = "") -> Row:
    """Everything the brief, the gates and the knowledge-base search read about one clip, as JSON."""
    speech_s = parts.step("video_prompt", "logic").speech_s
    clip = stored_clip(scene, shot)
    row = shot.row
    ir: Row = dict(row.get("ir") or {})
    raw = ir.get("cinematography")
    cine: Row = dict(raw) if isinstance(raw, Mapping) else {}
    heard_ids = set(shot.staged.heard_only)
    seen_ids = {c.id for c in shot.seen}
    items = [i for i in shot.items if i.is_line]
    spoken = []
    for ln, item in zip(shot.lines, items, strict=False):
        who = next((c for c in shot.cast if c.id == ln.character_id), None)
        base = lids.get(ln.id, "L?")
        text = item.text if item.is_part else ln.text
        spoken.append({"lid": f"{base}.{item.part}" if item.is_part else base,
                       "speaker": who.name if who else (ln.speaker.title() or "The speaker"),
                       "heard": bool(ln.character_id in heard_ids), "seconds": speech_s(text),
                       "delivery": ln.delivery})
    speaks = any(not s["heard"] for s in spoken) and any(ln.character_id in seen_ids for ln in shot.lines)
    raw_first = ir.get("first_frame")
    first: Row = dict(raw_first) if isinstance(raw_first, Mapping) else {}
    raw_design = row.get("design")
    design: Row = dict(raw_design) if isinstance(raw_design, Mapping) else {}
    raw_rec = design.get("recommended")
    rec: Row = dict(raw_rec) if isinstance(raw_rec, Mapping) else {}
    heading = str(scene.heading or "").strip().upper()
    return {
        "slate": str(row.get("slate") or shot.code), "id": shot.id, "code": shot.code,
        "setup": str(clip.get("setup") or row.get("setup") or ""),
        "role": str(clip.get("role") or row.get("role") or ""),
        "size": str(clip.get("size") or shot.framing), "framing_words": str(cine.get("framing") or ""),
        "take_s": shot.duration_s, "handle_in_s": row.get("handle_in_s") or 0, "handle_out_s": row.get("handle_out_s")
        or 0, "sound_mode": shot.sound_mode,
        "technique": str(clip.get("technique") or ""), "cine_camera": str(cine.get("camera") or ""),
        "angle": str(clip.get("angle") or cine.get("angle") or ""),
        "lens": str(clip.get("lens") or rec.get("lens") or ""),
        "movement": str(cine.get("movement") or ""), "depth": str(cine.get("depth_of_field") or ""),
        "cinematic": int(row.get("stage") or clip.get("stage") or 1) == 2,
        "why": str(clip.get("why") or (shot.intent.purpose if shot.intent else "") or ""),
        "summary": str(clip.get("summary") or ""),
        "in_frame": _subjects(ir) if shot.seen else [],
        "heard": [c.name for c in shot.heard], "opening": str(first.get("composition") or ""),
        "beats": [{"time": str(b.get("time") or ""), "action": str(b.get("action") or "")}
                  for b in ir.get("beats") or [] if isinstance(b, Mapping)],
        "spoken": spoken, "speaks": speaks,
        "exterior": heading.startswith(("EXT", "I/E", "INT/EXT")),
        "said": " ".join(s["delivery"] for s in spoken if s.get("delivery")), "mood": mood,
        "current": merge.current_of(design),
    }
