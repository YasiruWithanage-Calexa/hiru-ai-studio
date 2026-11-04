"""What a split scene turns into: the code halves of `script_split/engine/pipeline.py` that write and report
(plan/2026-11-03 Phase 6): the shot and line rows, the fit report, the staging report, the breath given up for the
envelope, the free continuity checks, and each episode's line in the build log. No model, no store.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from contracts import bridges, stagemap
from contracts import reading as scene_reading
from contracts.sceneplan import fit_report
from contracts.shotplan import FitResult, Item, ProposedShot, fit
from contracts.veo import SoundMode

Row = dict[str, Any]
Rows = list[Row]
EPISODE_KEYS = ("total_s", "envelope_s", "silent_s", "off_screen", "need_s")


def with_breath(result: FitResult, base: list[Item], kept: list[Item], envelope_s: int,
                fixed: int | None) -> FitResult:
    """Say what happened to the reading's breath: which holds were given up for the envelope, and what the scene needs
    with all of it and without the optional part ("needs 42 s, 37 s without optional breath")."""
    if not any(i.hold_s > 0 for i in base):
        return result
    result.breath_dropped = [i.index for i in base if i.hold_s > 0 and kept[i.index].hold_s == 0]
    proposal = [ProposedShot(s.start, s.end, s.framing, s.title, s.sound_mode.value, None, False,
                             s.camera_link.value) for s in result.shots]
    core = list(base)
    for held in scene_reading.optional_breath(base):
        core = scene_reading.release(core, held.index)
    full_s = fit(base, proposal, envelope_s=envelope_s, fixed_seconds=fixed).need_s
    core_s = fit(core, proposal, envelope_s=envelope_s, fixed_seconds=fixed).need_s
    result.breath_extra = {
        "dropped": [{"block": i, "seconds": base[i].hold_s, "kind": base[i].hold_kind,
                     "priority": base[i].hold_priority} for i in result.breath_dropped],
        "needs_s": full_s, "core_need_s": core_s}
    return result


def rows_for(scene: Row, result: FitResult, lines: Rows) -> tuple[Rows, Rows]:
    """-> (the shot rows, the line rows bound to them). New shot ids: a re-split replaces the scene's shots."""
    shot_ids = {s.number: str(uuid4()) for s in result.shots}
    shots = [{
        "id": shot_ids[s.number], "production_id": scene["production_id"], "scene_id": scene["id"],
        "number": s.number, "title": s.title, "framing": s.framing, "duration_s": s.duration_s,
        "start_s": s.start_s, "sound_mode": s.sound_mode.value, "camera_link": s.camera_link.value,
        "frame_strategy": s.frame_strategy.value, "speaker_id": s.speaker_id,
        "beats": [{"start_s": b0, "end_s": b1, "camera": "", "director_line": "", "action": ""} for b0, b1 in s.beats],
        "block_start": s.start, "block_end": s.end, "word_target": s.word_target, "words": s.words,
        "status": "draft", "version": 1,
    } for s in result.shots]
    fitted = {fl.line_id: fl for fl in result.lines}
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for ln in lines:
        fl = fitted.get(str(ln["id"]))
        row = {k: ln.get(k) for k in keep}
        row.update({"words": fl.words if fl else 0, "shot_id": shot_ids[fl.shot_number] if fl else None,
                    "beat_index": fl.beat_index if fl else None, "start_s": fl.start_s if fl else None,
                    "overrun_s": fl.overrun_s if fl else 0})
        line_rows.append(row)
    return shots, line_rows


def report(result: FitResult, planner_name: str, notes: list[str]) -> Row:
    return fit_report(result, planner_name, notes)


def staging_report(staging: stagemap.SceneStaging, items: list[Item], found: list[stagemap.Finding],
                   cast: list[str]) -> Row:
    """What `fit_report.staging` says: the spots, the problems left (a removed move is one), and the steps added."""
    def rows(code: str) -> Rows:
        return [{"message": f.message, "block": f.block, "shot": f.shot, "who": list(f.who), "zone": f.zone}
                for f in found if f.code == code]

    return {"zones": staging.zones, "teleports": rows("teleport"), "line_crossed": rows("line_crossed"),
            "eyeline": rows("eyeline"), "unplaced": stagemap.unplaced(staging, items, cast),
            "moves": [{"block": i.index, "text": i.text} for i in items if bridges.is_move_block(i.bridge)]}


def continuity_notes(label: str, scene: Row, lines: Rows) -> list[str]:
    """Free checks a person should see before directing: a scene with no place, a line nobody in the canon speaks, a
    scene with no script."""
    notes = []
    if not scene.get("location_id"):
        notes.append(f"{label} has no location; frames cannot be matched to a set.")
    unknown = sorted({str(ln["speaker"]) for ln in lines if not ln.get("character_id")})
    if unknown:
        notes.append(f"{label}: {', '.join(unknown)} not linked to a canon character, so no voice pin.")
    if not scene.get("script"):
        notes.append(f"{label} has no script.")
    return notes


def episode_stats(result: FitResult, scene: Row) -> dict[str, int]:
    """What one scene adds to its episode's line in the build log."""
    off_screen = sum(len(s.line_ids) for s in result.shots if s.sound_mode is SoundMode.VOICEOVER)
    return {"total_s": result.total_s, "envelope_s": int(scene["envelope_s"]), "silent_s": result.silent_s,
            "off_screen": off_screen, "need_s": result.need_s}


def episode_line(number: int, stats: dict[str, int]) -> str:
    """"Episode 1: needs 78 s to show its script; target 60 s, 34 s spoken, 2 lines off screen".

    The first figure is what the script needs on screen, pictures and speech together, not what the target squeezed it
    into: a person decides whether to grow the target or cut a beat."""
    need = max(stats["total_s"], stats.get("need_s", 0))
    first = (f"needs {need} s to show its script; target {stats['envelope_s']} s"
             if need > stats["envelope_s"] else f"{need} s")
    parts = [first, f"{stats['total_s'] - stats['silent_s']} s spoken"]
    if stats["off_screen"]:
        parts.append(f"{stats['off_screen']} line{'s' if stats['off_screen'] != 1 else ''} off screen")
    return f"Episode {number}: " + ", ".join(parts)
