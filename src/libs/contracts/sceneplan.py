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
from dataclasses import replace
from typing import Any
from uuid import uuid4

from contracts import beats
from contracts import reading as scene_reading
from contracts.beats import BLOCK_EXTRA
from contracts.shotplan import FitResult, Item, ProposedShot
from contracts.veo import SoundMode

Row = dict[str, Any]
BEAT_TEXT = ("camera", "director_line", "action")
# What a video prompt is written from: a change to any of these makes the shot a new version.
MATERIAL = ("title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end", "beats",
            "words")
LINE_KEEP = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
# A translated line keeps the words it was written in (plan/2026-11-01c, Phase 4). Written only when set, so a
# database that has not got the columns yet still saves every other line.
LINE_SOURCE = ("source_text", "source_lang")


def items_for(script: list[Row], lines: list[Row]) -> list[Item]:
    """The scene's script blocks as kernel items. A dialogue block whose line no longer exists
    is dropped (nothing to bind), so block indexes are positions in THIS list.

    An action block that nobody has read yet (`contracts.beats`) is read by the free rules, so the
    picture clock always runs; a stored reading (a model's, or a person's) wins."""
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
                              line.get("delivery") or "", str(line["id"]),
                              skip=tuple(str(k) for k in block.get("skip_bridges") or ())))
        else:
            items.append(Item(len(items), kind, str(block.get("text", "")), screen=str(block.get("screen") or "act"),
                              events=max(1, int(block.get("events") or 1)), implied=bool(block.get("implied")),
                              by=str(block.get("by") or ""), for_version=int(block.get("for_version") or 0),
                              skip=tuple(str(k) for k in block.get("skip_bridges") or ()),
                              bridge=str(block.get("bridge") or "")))
    return _read_unread(items)


def scene_items(scene: Mapping[str, Any], lines: list[Row], script: list[Row] | None = None) -> list[Item]:
    """The scene's kernel items WITH the time its reading gives them (holds, turns). Every place that times a scene
    from its stored rows (the API, the director, the prompts) reads items through here, so they agree with the split.
    A scene with no reading times exactly as `items_for` does."""
    items = items_for(scene.get("script") or [] if script is None else script, lines)
    return scene_reading.apply(items, scene_reading.SceneReading.of(scene))


def _read_unread(items: list[Item]) -> list[Item]:
    """Fill in the free rules' reading on action blocks that carry none."""
    unread = [i for i in items if i.kind == "action" and not i.implied and not i.for_version and i.by != "person"]
    if not unread:
        return items
    readings = beats.read_by_rules(items)
    return [replace(i, screen=r.screen, events=r.events) if i in unread and (r := readings.get(i.index)) else i
            for i in items]


def item_row(item: Item) -> Row:
    """A kernel item as the director's working copy holds it (the inverse of `Item`'s fields)."""
    row: Row = {"kind": item.kind, "text": item.text, "line_id": item.line_id, "speaker": item.speaker,
                "speaker_id": item.speaker_id, "delivery": item.delivery}
    if item.hold_s:  # feeling's time travels with its block through the director's edits
        row |= {"hold_s": item.hold_s, "hold_kind": item.hold_kind, "hold_priority": item.hold_priority,
                "hold_who": item.hold_who}
    if item.turn:
        row["turn"] = True
    if item.skip:  # a removed step is remembered on the block it belonged to (a line, or the block after a move)
        row["skip_bridges"] = list(item.skip)
    if item.kind == "action":
        if item.screen != "act" or item.events != 1 or item.for_version:
            row |= {"screen": item.screen, "events": item.events}
        if item.for_version:
            row["for_version"] = item.for_version
        if item.by:
            row["by"] = item.by
        if item.implied:
            row |= {"implied": True, "bridge": item.bridge}
    return row


def item_of(index: int, row: Mapping[str, Any]) -> Item:
    """A working-copy row → a kernel item at `index`."""
    return Item(index, row["kind"], row.get("text", ""), row.get("speaker", ""), row.get("speaker_id"),
                row.get("delivery", ""), row.get("line_id"), str(row.get("screen") or "act"),
                max(1, int(row.get("events") or 1)), bool(row.get("implied")), str(row.get("by") or ""),
                int(row.get("for_version") or 0), tuple(row.get("skip_bridges") or ()), str(row.get("bridge") or ""),
                float(row.get("hold_s") or 0.0), str(row.get("hold_kind") or ""), int(row.get("hold_priority") or 0),
                str(row.get("hold_who") or ""), bool(row.get("turn")))


def script_rows(items: Sequence[Mapping[str, Any]]) -> list[Row]:
    """Script blocks as the kernel holds them → what `scenes.script` stores (a dialogue block
    points at its line; the words live in `dialogue_lines`). A reading is stored only when it was
    made for a script version or marks an implied step; the free rules' in-memory reading is not."""
    out: list[Row] = []
    for i in items:
        if i["kind"] == "dialogue":
            row: Row = {"kind": "dialogue", "text": "", "line_id": str(i["line_id"])}
            if i.get("skip_bridges"):
                row["skip_bridges"] = list(i["skip_bridges"])
        else:
            row = {"kind": str(i["kind"]), "text": str(i.get("text") or ""), "line_id": None}
            if i.get("for_version") or i.get("implied"):
                row |= {k: i[k] for k in BLOCK_EXTRA if k in i}
            if i.get("skip_bridges"):
                row["skip_bridges"] = list(i["skip_bridges"])
        out.append(row)
    return out


def lines_from_items(scene: Row, items: Sequence[Mapping[str, Any]]) -> list[Row]:
    """The scene's `dialogue_lines` rows (the fields `rows_after_fit` keeps) for the kernel's
    items: one per dialogue block, in script order."""
    out: list[Row] = []
    for i in items:
        if i["kind"] == "dialogue":
            out.append({"id": str(i["line_id"]), "production_id": str(scene["production_id"]),
                        "scene_id": str(scene["id"]), "ord": len(out), "speaker": str(i.get("speaker") or ""),
                        "character_id": i.get("speaker_id"), "text": str(i.get("text") or ""),
                        "delivery": str(i.get("delivery") or ""),
                        **{k: str(i[k]) for k in LINE_SOURCE if i.get(k)}})
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


def fit_report(result: FitResult, planner: str, notes: list[str] | None = None, *,
               breath: Row | None = None) -> Row:
    """What `scenes.fit_report` stores (`script_split` writes it too).

    `multi_speaker`, `crowded` and `voiceover` are shot numbers: the shots a person should look at,
    the shots that hold more than they can show, and the shots whose voice is heard rather than seen.
    `need_s` is what the scene needs on screen to show and say everything in it. `breath` (plan/2026-11-01d) is the
    time the reading gave the scene: `kept_s` always; `dropped` and `core_need_s` when the split had to give some
    up to fit the envelope ("needs 42 s, 37 s without optional breath")."""
    report: Row = {"total_s": result.total_s, "envelope_s": result.envelope_s, "planner": planner,
            "silent_s": result.silent_s, "silent_share": round(result.silent_share, 2),
            "multi_speaker": [i.shot_number for i in result.issues if i.code == "multi_speaker"],
            "crowded": result.crowded, "need_s": result.need_s,
            "voiceover": [s.number for s in result.shots if s.sound_mode is SoundMode.VOICEOVER],
            "critic_notes": list(notes or []),
            "issues": [{"code": i.code, "message": i.message, "shot": i.shot_number, "line_id": i.line_id}
                       for i in result.issues]}
    extra = result.breath_extra if breath is None else breath
    if result.breath_s or extra:
        report["breath"] = {"kept_s": round(result.breath_s, 2), **extra}
    return report


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
        line_rows.append({**{k: ln.get(k) for k in LINE_KEEP}, **{k: ln[k] for k in LINE_SOURCE if ln.get(k)},
                          "words": fl.words if fl else 0,
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
