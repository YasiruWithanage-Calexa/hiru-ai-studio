"""What the video prompt agent is told about one clip, read from the shot producer's own inputs (plan/2026-11-20b §4.1).

    usable_packet(store, scene_row)                  -> (packet, "") or (None, why there is none)          D5
    line_ids_for(packet, line_rows)                  -> line row id -> its short id, or None when they differ D6
    clip_facts(shot, scene, prod, frame, ...)        -> the JSON `logic` briefs, gates and assembles from

The packet pairs with the line rows as raphael_write pairs them: the n-th spoken block is the line of `ord` n, and the
packet must be made for the scene's current script version (`breakdown_build.packet_for`'s rules, without its stager
call: the producer never pays for a map). The clip facts take the planner's camera from Raphael's stored clip when the
shot is one of his (its angle, lens, technique, why and summary), else from the shot's design; the people in frame are
dressed in the scene's look (`contracts.canon.dressed`), never in clothes the planner wrote; the opening, join and
carried-over sentences are the serializer's own (`serialize` step, by id), so the video prompt says what the first
frame and the cut already are.
"""
from __future__ import annotations

from typing import Any

from contracts.camera_words import camera_line
from contracts.canon import dressed
from contracts.frame_brief import agent_camera
from contracts.producer import is_hold
from hiru_ai.core import parts
from hiru_ai.steps.video_prompt import logic

Row = dict[str, Any]


def usable_packet(store: Any, scene_row: Row) -> tuple[Row | None, str]:
    """The scene's packet when a planner may read it (D5): made for the scene's current script and not waiting for a
    person. None and the reason otherwise, in words for the job's warning."""
    if store is None:
        return None, "the scene's breakdown could not be read: refresh the scene's breakdown"
    try:
        row = store.packet(str(scene_row["id"]))
    except Exception:  # schema v21 not applied, or a broken store
        return None, "the breakdown tables are not there (schema v21)"
    if not row:
        return None, "this scene has no breakdown: build or refresh the scene's breakdown"
    if int(row.get("script_version") or 0) != int(scene_row.get("script_version") or 1):
        return None, "the script changed after the breakdown: refresh the scene's breakdown"
    if row.get("waits"):
        return None, "the scene's breakdown waits for a person: " + "; ".join(str(w) for w in row["waits"])[:240]
    packet = row.get("packet")
    return (packet, "") if isinstance(packet, dict) and packet.get("E_blocks") else (None, "the scene's packet is "
                                                                                          "empty: refresh the scene's "
                                                                                          "breakdown")


def line_ids_for(packet: Row, line_rows: list[Row]) -> dict[str, str] | None:
    """Line row id -> the short id the scene's brief uses (L<block>), pairing the n-th spoken block with the line of
    `ord` n (D6). None when the counts differ: the packet is not this script's."""
    blocks = logic.spoken_blocks(packet)
    rows = sorted(line_rows, key=lambda r: int(r.get("ord") or 0))
    if len(blocks) != len(rows):
        return None
    short = logic.line_ids(packet)
    return {str(r["id"]): short[str(b["id"])] for b, r in zip(blocks, rows, strict=True)}


def _stored_clip(scene: Any, shot: Any) -> Row:
    """Raphael's own clip for this shot (by slate), from the scene's stored result; {} for another planner's shot."""
    stored = (scene.row or {}).get("raphael") or {}
    slate = str(shot.row.get("slate") or "")
    if not slate or not isinstance(stored, dict):
        return {}
    return next((c for c in stored.get("clips") or [] if isinstance(c, dict) and c.get("slate") == slate), {})


def _subject(ir: Row, member: Any) -> Row:
    for s in ir.get("subjects") or []:
        if isinstance(s, dict) and (str(s.get("id") or "") == member.code
                                    or member.name.lower() in str(s.get("description") or "").lower()):
            return s
    return {}


def clip_facts(shot: Any, scene: Any, prod: Any, frame: Row | None, *, lids: dict[str, str],
               wardrobe: dict[str, str] | None = None) -> Row:
    """Everything the brief, the gates and the assembly read about one clip, as JSON. `lids`: line row id -> the
    scene brief's short id (`line_ids_for`)."""
    serialize = parts.step("serialize", "schema").get_schema()
    continuity = parts.step("serialize", "continuity")
    positions_text = parts.step("feeling").positions_text
    clip = _stored_clip(scene, shot)
    ir: Row = dict(shot.row.get("ir") or {})
    raw_cine = ir.get("cinematography")
    cine: Row = raw_cine if isinstance(raw_cine, dict) else {}
    camera = shot.camera(scene)
    technique = str(clip.get("technique") or camera.movement or "")
    # plan/2026-11-20c D13: the camera sentence is the Camera agent's while a person has not changed a camera field,
    # else code's from the fields; `locked_off` reads the design's move (the panel as it stands)
    sentence = camera_line(camera, shot.recommended(scene), agent_camera(shot.row))
    wear = dict(wardrobe or {})
    in_frame = []
    for c in shot.seen:
        s = _subject(ir, c)
        described = dressed(str(s.get("description") or c.name).strip().rstrip(" ."), wear.get(c.code, ""))
        in_frame.append({"name": c.name, "description": f"{described}.", "position": str(s.get("position") or ""),
                         "action": str(s.get("action") or "")})
    heard_ids = set(shot.staged.heard_only)
    items = [i for i in shot.items if i.is_line]
    lines = []
    for ln, item in zip(shot.lines, items, strict=False):
        who = next((c for c in shot.cast if c.id == ln.character_id), None)
        base = lids.get(ln.id, "L?")
        lines.append({"lid": f"{base}.{item.part}" if item.is_part else base, "id": ln.id, "text": ln.text,
                      "speaker": who.name if who else (ln.speaker.title() or "The speaker"),
                      "character_id": ln.character_id or "", "heard": bool(ln.character_id in heard_ids),
                      "part": item.part, "parts": item.parts})
    stored = (scene.row or {}).get("raphael") or {}
    real = stored.get("line_ids") if isinstance(stored, dict) else {}
    edit_lines = list(dict.fromkeys(lids[real[s]] for s in clip.get("lines") or []
                                    if isinstance(real, dict) and real.get(s) in lids))
    previous = next((s for s in scene.shots if s.number == shot.number - 1), None)
    carried = shot.frame_strategy == "carry_last_frame" and previous is not None
    opening, note = "", ""
    if carried and previous is not None:
        opening = serialize.rule("opening_carried").format(previous=previous.code)
        note = f"on the last frame of {previous.code}'s take"
    elif frame is not None:
        opening, note = serialize.rule("opening_frame"), "on the accepted first frame"
    link = shot.camera_link
    join = "" if link == "cut" else serialize.render_rules.get("join_continuous" if link == "continuous"
                                                               else "join_match", "")
    join_note = "" if link == "cut" or previous is None else (
        f"a continuous take from {previous.code}" if link == "continuous" else f"a matched re-angle of {previous.code}")
    carried_text = continuity.carried_state(previous.code, previous.row.get("ir"),
                                            positions_text(previous.feeling.end)) if previous and link != "cut" else ""
    card = shot.row.get("card") if isinstance(shot.row.get("card"), dict) else {}
    sound = clip.get("sound") if isinstance(clip.get("sound"), dict) else (card or {}).get("sound") or {}
    return {
        "code": shot.code, "slate": str(shot.row.get("slate") or ""), "role": str(clip.get("role") or
                                                                                    shot.row.get("role") or ""),
        "size": str(clip.get("size") or shot.framing), "framing_words": str(cine.get("framing") or ""),
        "angle": str(clip.get("angle") or camera.angle or ""), "lens": str(clip.get("lens") or camera.lens or ""),
        "technique": technique, "movement": str(cine.get("movement") or camera.movement or ""),
        "locked_off": is_hold(camera), "camera_sentence": sentence,
        "take_s": shot.duration_s, "why": str(clip.get("why") or (shot.intent.purpose if shot.intent else "") or ""),
        "summary": str(clip.get("summary") or ""), "setting": str(ir.get("setting") or ""),
        "light": str(ir.get("lighting") or ""), "in_frame": in_frame,
        "heard_people": [c.name for c in shot.heard], "voice_source": str(shot.staged.voice_source or ""),
        "over": str(clip.get("over") or ""), "hands": shot.hands,
        "beats": [{k: str(b.get(k) or "") for k in ("time", "director_line", "action", "performance")}
                  for b in ir.get("beats") or [] if isinstance(b, dict)],
        "sound": {k: str((sound or {}).get(k) or "") for k in ("ambience", "effects", "music")},
        "sound_mode": shot.sound_mode, "lines": lines, "edit_lines": edit_lines,
        "opening": opening, "opening_note": note, "carried_from": previous.code if carried and previous else "",
        "join": join, "join_note": join_note, "carried": carried_text,
        "voices_missing": [c.name for c in shot.cast if c.id in shot.speaker_ids and not c.voice_pin],
        "aspect_ratio": prod.aspect_ratio,
    }
