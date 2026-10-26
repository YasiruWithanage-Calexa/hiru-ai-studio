"""A scene's STORED plan ↔ the shot-plan kernel (`contracts.shotplan`).

The API (a person changes a shot's length, sound or framing, or edits the script) and the
`director_chat` function (a turn's operations) both re-fit a scene that already has shots, and
both must write the result back the same way:

* shots keep their ids (first frames, prompts and takes hang off them in Phase 4);
* a shot the kernel had to split (its speech cannot fit the longest rung) keeps its id on the
  first part; the follow-on part is a new shot;
* a shot's `version` goes up only when something a prompt depends on changed, so Phase 4 can
  tell which prompts are out of date;
* every line is re-bound to its shot and beat, verbatim.

Pure standard library (the `contracts` rule), so both sides share one implementation.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from contracts.shotplan import FitResult, Item, ProposedShot

Row = dict[str, Any]
BEAT_TEXT = ("camera", "director_line", "action")
# What a video prompt is written from: a change to any of these makes the shot a new version.
MATERIAL = ("title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end", "beats",
            "words")
LINE_KEEP = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")


def items_for(script: list[Row], lines: list[Row]) -> list[Item]:
    """The scene's script blocks as kernel items. A dialogue block whose line no longer exists
    is dropped (nothing to bind), so block indexes are positions in THIS list."""
    by_id = {str(ln["id"]): ln for ln in lines}
    items: list[Item] = []
    for block in script or []:
        kind = str(block.get("kind", "action"))
        line = by_id.get(str(block.get("line_id"))) if kind == "dialogue" else None
        if kind == "dialogue" and line is None:
            continue
        if line is not None:
            items.append(Item(len(items), "dialogue", line["text"], line["speaker"],
                              str(line["character_id"]) if line.get("character_id") else None,
                              line.get("delivery") or "", str(line["id"])))
        else:
            items.append(Item(len(items), kind, str(block.get("text", ""))))
    return items


def script_rows(items: Sequence[Mapping[str, Any]]) -> list[Row]:
    """Script blocks as the kernel holds them → what `scenes.script` stores (a dialogue block
    points at its line; the words live in `dialogue_lines`)."""
    return [{"kind": "dialogue", "text": "", "line_id": str(i["line_id"])} if i["kind"] == "dialogue"
            else {"kind": str(i["kind"]), "text": str(i.get("text") or ""), "line_id": None} for i in items]


def lines_from_items(scene: Row, items: Sequence[Mapping[str, Any]]) -> list[Row]:
    """The scene's `dialogue_lines` rows (the fields `rows_after_fit` keeps) for the kernel's
    items: one per dialogue block, in script order."""
    out: list[Row] = []
    for i in items:
        if i["kind"] == "dialogue":
            out.append({"id": str(i["line_id"]), "production_id": str(scene["production_id"]),
                        "scene_id": str(scene["id"]), "ord": len(out), "speaker": str(i.get("speaker") or ""),
                        "character_id": i.get("speaker_id"), "text": str(i.get("text") or ""),
                        "delivery": str(i.get("delivery") or "")})
    return out


def plan_from_rows(shots: list[Row]) -> list[Row]:
    """Stored shot rows → the plan form the kernel and `rows_after_fit` work on."""
    return [{"id": str(s["id"]), "start": int(s["block_start"]), "end": int(s["block_end"]),
             "title": s.get("title", ""), "framing": s.get("framing", "MS"), "sound_mode": s.get("sound_mode"),
             "duration": int(s["duration_s"]), "duration_locked": bool(s.get("duration_locked")),
             "camera_link": s.get("camera_link", "cut"), "status": s.get("status", "draft"),
             "version": int(s.get("version") or 1), "person_edits": s.get("person_edits") or {},
             "beat_notes": [{k: str(b.get(k, "")) for k in BEAT_TEXT} for b in s.get("beats") or []]}
            for s in sorted(shots, key=lambda r: int(r["number"]))]


def proposal_for(plan: list[Row]) -> list[ProposedShot]:
    return [ProposedShot(int(s["start"]), int(s["end"]), s.get("framing") or "MS", s.get("title", ""),
                         s.get("sound_mode"), s.get("duration"), bool(s.get("duration_locked")),
                         s.get("camera_link") or "cut") for s in plan]


def fit_report(result: FitResult, planner: str, notes: list[str] | None = None) -> Row:
    """What `scenes.fit_report` stores (the same shape `script_split` writes)."""
    return {"total_s": result.total_s, "envelope_s": result.envelope_s, "planner": planner,
            "critic_notes": list(notes or []),
            "issues": [{"code": i.code, "message": i.message, "shot": i.shot_number, "line_id": i.line_id}
                       for i in result.issues]}


def rows_after_fit(scene: Row, plan: list[Row], result: FitResult, lines: list[Row], *,
                   before: dict[str, Row] | None = None,
                   new_id: Callable[[], str] = lambda: str(uuid4())) -> tuple[list[Row], list[Row], list[str]]:
    """→ (shot rows to upsert, line rows to upsert, ids of stored shots to delete).

    `plan` is what the fit ran on (each with `start`, optional `id`, `beat_notes`, `status`,
    `version`, `duration_locked`); `before` the stored rows by id, to decide version bumps."""
    before = before or {}
    by_start = {int(s["start"]): s for s in plan}
    shots: list[Row] = []
    ids: dict[int, str] = {}
    for f in result.shots:
        src = by_start.get(f.start)  # None: the follow-on part of a shot the kernel split
        shot_id = str(src["id"]) if src and src.get("id") else new_id()
        ids[f.number] = shot_id
        notes = (src or {}).get("beat_notes") or []
        row: Row = {
            "id": shot_id, "production_id": str(scene["production_id"]), "scene_id": str(scene["id"]),
            "number": f.number, "title": f.title, "framing": f.framing, "duration_s": f.duration_s,
            "start_s": f.start_s, "sound_mode": f.sound_mode.value, "camera_link": f.camera_link.value,
            "frame_strategy": f.frame_strategy.value, "speaker_id": f.speaker_id,
            "beats": [{"start_s": b0, "end_s": b1, **{k: (notes[i].get(k, "") if i < len(notes) else "")
                                                      for k in BEAT_TEXT}} for i, (b0, b1) in enumerate(f.beats)],
            "block_start": f.start, "block_end": f.end, "word_target": f.word_target, "words": f.words,
            "duration_locked": bool(src and src.get("duration_locked")),
            "status": (src or {}).get("status", "draft"), "version": int((src or {}).get("version") or 1),
            # A person's own marks (cast, ignored checks, the DoP note) travel with the shot's id.
            "person_edits": (src or {}).get("person_edits") or {},
        }
        old = before.get(shot_id)
        if old is not None and any(_norm(old.get(k)) != _norm(row[k]) for k in MATERIAL):
            row["version"] = int(old.get("version") or 1) + 1
        shots.append(row)

    fitted = {fl.line_id: fl for fl in result.lines}
    line_rows = []
    for ln in lines:
        fl = fitted.get(str(ln["id"]))
        line_rows.append({**{k: ln.get(k) for k in LINE_KEEP}, "words": fl.words if fl else 0,
                          "shot_id": ids[fl.shot_number] if fl else None,
                          "beat_index": fl.beat_index if fl else None, "start_s": fl.start_s if fl else None,
                          "overrun_s": fl.overrun_s if fl else 0})
    kept = {r["id"] for r in shots}
    removed = [sid for sid in before if sid not in kept]
    return shots, line_rows, removed


def _norm(value: Any) -> Any:
    """Compare stored JSON and fresh values alike (beats as lists of plain dicts)."""
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    return value
