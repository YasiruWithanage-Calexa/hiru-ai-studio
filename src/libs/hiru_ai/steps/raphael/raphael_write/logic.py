"""A Raphael result, written as rows (plan/2026-11-08e §7 phase 4).

Pure rows in, rows out: the system hands them to `SceneStore.replace_shots`, which deletes the scene's shots and
writes the
new ones, so a repeat of the same job gives the same rows (idempotent for Cloud Tasks re-delivery). An APPROVED scene is
never touched.

    rows_for     the bin's clips → `shots` rows (one per clip, in the order of the intended cut: moment, must before
                 cinematic, slate) with the plan's fields (role, priority, slate, handles, stage, anchor, blend) and the
                 scene's dialogue lines bound to the clip that PERFORMS them
    fit_report   what `scenes.fit_report` stores, in the classic planner's shape
    write        the scene update: status, fit_report, the stored result (`scenes.raphael`) and the coverage plan

The camera is decided once: the clip's `ir` is finished the way the DoP's is (`serialize.shots.finish`) and the design
is
stored with the pins the shot producer will compute, so `design_stale` is empty for a Raphael shot and neither the
intent
agent, the DoP nor the critic is called for it. The serialize step is reached by id (`core.parts`).

A line is bound to ONE shot: the must clip that performs it (D2: the master and the speaker's single speak). The other
clips
that carry the line play silent or under it: they have no line of their own to say, so Veo is told not to invent speech.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from contracts import sceneplan
from contracts.frame_brief import nearest_option
from contracts.producer import CameraField
from contracts.raphael import state as ledger_state
from contracts.raphael.checks import mentions, strings_of
from contracts.raphael.scene import LONGEST_TAKE_S, norm
from contracts.raphael.stored import StoredRaphael
from contracts.raphael.wire import FRAMING, Clip
from contracts.shotplan import Item, shot_clock
from contracts.stagemap import SceneStaging
from contracts.staging import heard_marked, voice_source
from contracts.timing import default_beats, overrun_seconds, shot_word_target, words_in
from hiru_ai.core import parts

Row = dict[str, Any]
SPOKEN = "dialogue"


def sound_mode_of(clip: Clip, performs: bool, heard_line: bool) -> str:
    """How a clip carries its sound (`contracts.veo.SoundMode`): a line on its speaker is dialogue; a line that is
    heard and not seen (marked so, or bound to this clip while its speaker is not in it) is voiced off screen; no words
    and a call for silence is silent (Veo must be told, or it invents speech); music alone is music only; else
    ambient."""
    if performs:
        return SPOKEN
    if heard_line and clip.lines:
        return "voiceover"
    sound = clip.sound
    if sound is not None and sound.silence:
        return "silent"
    if sound is not None and sound.music and not (sound.ambience or sound.effects):
        return "music_only"
    return "ambient"


def people_by_name(characters: list[Row]) -> dict[str, str]:
    """A character's name and every alias (any case) → their canon id."""
    out: dict[str, str] = {}
    for c in characters:
        for name in [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]]:
            if norm(name):
                out.setdefault(norm(name), str(c["id"]))
    return out


def card_size(size: str) -> str:
    """The clip's size in the vocabulary of the shot card the shared card reader (`serialize.card`) knows."""
    near = FRAMING.get(size, size)
    return {"WIDE": "WS", "TWO": "MS", "OTS": "MS"}.get(near, near)


def card_of(clip: Clip, line_rows: Row) -> Row:
    """The clip's card in the keys the shared card reader knows: the size, the sound design and which lines play over a
    listener. Raphael's camera lives in the IR, so the card names no camera decisions."""
    sound = clip.sound
    return {
        "size": card_size(clip.size),
        "take_s": clip.take_s,
        "use_s": clip.take_s,
        "sound": {
            "ambience": sound.ambience if sound else "",
            "effects": sound.effects if sound else "",
            "music": sound.music if sound else "",
            "silence": bool(sound.silence) if sound else False,
        },
        "lines": [{"line_id": ln, "on_speaker": not clip.over, "over_whom": clip.over} for ln in clip.lines],
        "cut_in": {"link": "cut"},
    }


def camera_hint(ir: Row) -> Row:
    """The panel's words for what the clip's IR says about the camera, where there is an exact equivalent: the angle
    from
    `angle`, the lens and the stop from the rig in `camera`, the move from `movement` (the rig only when the movement
    says
    nothing). A value the panel does not know is left out (the default for the size stands)."""
    raw = ir.get("cinematography")
    cine: Row = raw if isinstance(raw, dict) else {}
    rig, angle_text, move_text = (norm(str(cine.get(k) or "")) for k in ("camera", "angle", "movement"))
    out: Row = {}
    angle = (
        "Low angle"
        if "low" in angle_text
        else "High angle"
        if "high" in angle_text
        else "Overhead"
        if "overhead" in angle_text
        else ""
    )
    # plan/2026-11-11b §4.5: the panel's nearest lens and stop (65mm → 50mm), not nothing; the brief keeps the
    # planner's own words for the picture
    lens = nearest_option(CameraField.LENS, rig)
    stop = nearest_option(CameraField.APERTURE, rig)

    def move_of(text: str) -> str:
        if any(w in text for w in ("push in", "dolly in", "push-in")):
            return "Dolly in"
        if any(w in text for w in ("pull out", "dolly out", "pull back", "pull-out")):
            return "Dolly out"
        if " pan" in f" {text}":
            return "Pan"
        if "handheld" in text:
            return "Handheld"
        return "Static" if any(w in text for w in ("locked", "static", "sticks", "tripod")) else ""

    move = move_of(move_text) or move_of(rig)
    for key, value in (("angle", angle), ("lens", lens), ("aperture", stop), ("movement", move)):
        if value:
            out[key] = value
    if move and move != "Static":
        out["speed"] = "Slow"
    return out


# A part of a person: "Anudi's hand" puts Anudi (in part) in the frame; "Kasun's canopy" is a thing of his, not Kasun
BODY = re.compile(
    r"(?:hands?|fingers?|fingertips?|face|eyes?|shoulders?|arms?|wrists?|feet|foot|legs?|back|"
    r"silhouette|profile|knuckles?|lips?|mouth|hair|figure|head|neck|palms?|reflection|shadow)\b"
)


def names_person(text: str, name: str) -> bool:
    """`text` shows the person called `name`: it names them, other than as the owner of a thing ("Kasun's canopy"). A
    part of
    them counts ("Anudi's fingertips")."""
    for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
        owner = re.match(r"['’]s?\s+(?:\w+\s+)?(\w+)", text[m.end() :])
        if owner is None or BODY.match(owner.group(1).lower()):
            return True
    return False


def subject_texts(clip: Clip) -> list[tuple[str, str]]:
    """(who it is, the subject's code) for each subject the clip lists: the IR's subjects (their description, not their
    action: "looks at Kasun" does not put Kasun in the frame) and the first frame's subjects."""
    ir = clip.ir or {}
    out: list[tuple[str, str]] = []
    for s in ir.get("subjects") or []:
        if isinstance(s, dict):
            out.append((str(s.get("description") or ""), str(s.get("id") or "")))
        elif isinstance(s, str):
            out.append((s, ""))
    frame = ir.get("first_frame")
    for s in (frame.get("subjects") if isinstance(frame, dict) else None) or []:
        out.append((str(s), ""))
    return out


def on_screen_of(clip: Clip, people: dict[str, str], codes: dict[str, str] | None = None) -> list[str]:
    """Canon ids of the people the clip shows: a subject that names the person (or a part of them), a subject with no
    name
    but their code, and the listener of a clip that plays a line over one. A name in passing is not a person in the
    frame."""
    seen: list[str] = []
    codes = {norm(k): v for k, v in (codes or {}).items()}

    def add(ident: str) -> None:
        if ident and ident not in seen:
            seen.append(ident)

    for text, code_ in subject_texts(clip):
        named = [ident for name, ident in people.items() if names_person(text, name)]
        for ident in named:
            add(ident)
        owned = any(mentions(text, name) for name in people)  # "Kasun's canopy colour": a thing, not a person
        if not named and not owned and norm(code_) in codes:
            add(codes[norm(code_)])
    if clip.over and norm(clip.over) in people:
        add(people[norm(clip.over)])
    return seen


def intent_of(
    clip: Clip,
    items: list[Item],
    people: dict[str, str],
    line_rows: dict[str, Row],
    codes: dict[str, str] | None = None,
    *,
    story: tuple[str, str] = ("", ""),
    states: tuple[str, str] = ("", ""),
) -> Row:
    """The clip as its intent (`contracts.staging.ShotIntent`), written `by = "raphael"`: what it is for, what we see,
    who is
    in frame and who is only heard. An intent no agent replaces, so the intent agent is skipped."""
    on_screen = on_screen_of(clip, people, codes)
    # the speaker of a line performed on camera is in the frame, unless it is marked heard
    if clip.speaks and not clip.over:
        by_id = {str(r.get("id")): r for r in line_rows.values() if r}
        for item in items:
            row = by_id.get(str(item.line_id)) if item.is_line else None
            who = str(row.get("character_id") or "") if row else ""
            if who and who not in on_screen and not heard_marked(item):
                on_screen.append(who)
    heard: list[str] = []
    for ln in clip.lines:
        row = line_rows.get(ln)
        who = str(row["character_id"]) if row and row.get("character_id") else ""
        if who and who not in on_screen and who not in heard:
            heard.append(who)
    source = (voice_source(items) or "off_screen") if heard else ""
    ir = clip.ir or {}
    sees = "; ".join(
        str(b.get("action") or "") for b in ir.get("beats") or [] if isinstance(b, dict) and b.get("action")
    )
    out: Row = {
        "purpose": clip.why[:400],
        "what_we_see": (sees or clip.why)[:700],
        "emotional_beat": story[1][:200],  # plan/2026-11-09: the moment's feeling (it was saved "")
        "on_screen": on_screen,
        "heard_only": heard,
        "voice_source": source,
        "by": "raphael",
        "made_for": "",
        "written_at": None,
    }
    # plan/2026-11-09: what happens (the moment's `what`) and the state the clip opens and ends in (the ledger's, code)
    for key, value, limit in (("story", story[0], 300), ("opens", states[0], 400), ("ends", states[1], 400)):
        if value:
            out[key] = value[:limit]
    return out


def states_text(staging: SceneStaging | None, items: list[Item], clip: Clip, clips: list[Clip]) -> tuple[str, str]:
    """A clip's opening and closing state as text (plan/2026-11-09 phase 5), from the scene's map; "" without one.
    Code, never the model: no output tokens."""
    if staging is None:
        return "", ""
    opens, ends = ledger_state.states_of(staging, items, ledger_state.clip_blocks(clip, clips))
    return opens.text()[: ledger_state.STATE_TEXT_CHARS], ends.text()[: ledger_state.STATE_TEXT_CHARS]


def title_of(clip: Clip) -> str:
    words = clip.why.split()
    return " ".join(words[:8]).rstrip(".,;:") or clip.slate


def order(clips: list[Clip]) -> list[Clip]:
    """The order of the intended cut: moment, must before cinematic, then the clip's id (the shooting order)."""
    return sorted(clips, key=lambda c: (c.moment, c.stage, c.id))


def performers(clips: list[Clip]) -> dict[str, str]:
    """Line id (L4) → the id of the clip that performs it: the first must clip that speaks it, else (a line heard and
    not
    seen) the first must clip that carries it."""
    out: dict[str, str] = {}
    for c in order([c for c in clips if c.priority == "must"]):
        for ln in c.lines:
            if c.speaks and ln not in out:
                out[ln] = c.id
    for c in order([c for c in clips if c.priority == "must"]):
        for ln in c.lines:
            out.setdefault(ln, c.id)
    return out


def rows_for(
    scene: Row, lines: list[Row], stored: StoredRaphael, characters: list[Row]
) -> tuple[list[Row], list[Row], list[Row]]:
    """-> (the shot rows without IR and design, the line rows bound to them, the per-clip clock facts). New shot ids,
    as a
    re-split makes them. The lines' words are the script's: a line is bound by id and never copied from the plan."""
    clips = [c for c in order(stored.clips) if c.ir is not None]
    items = sceneplan.scene_items(scene, lines)
    by_index = {i.index: i for i in items}
    rows_by_id = {str(ln["id"]): ln for ln in lines}
    by_short = {short: rows_by_id[real] for short, real in stored.line_ids.items() if real in rows_by_id}
    people = people_by_name(characters)
    codes = {str(c["code"]): str(c["id"]) for c in characters if c.get("code")}
    shot_ids = {c.id: str(uuid4()) for c in clips}
    perform = performers(clips)
    # plan/2026-11-09: the scene's state ledger (a map the system saved with these shots), read by code
    staging = SceneStaging.of(scene)
    moments = {m.n: (m.what, m.feeling) for m in (stored.edit.moments if stored.edit else [])}
    long = {
        i.index: s
        for i, s in ((i, shot_clock([i])[1]) for i in items if i.kind == "action")
        if s > LONGEST_TAKE_S + 1e-9
    }
    slates = {c.id: c.slate for c in stored.clips}
    shots: list[Row] = []
    facts: list[Row] = []
    bound: dict[str, Row] = {}
    start_s = 0
    for n, c in enumerate(clips, 1):
        own = [by_index[b] for b in c.blocks if b in by_index]
        slots, need = shot_clock(own)
        starts = {slot.index: slot.start_s for slot in slots if slot.is_line}
        windows = default_beats(c.take_s)
        block_start, block_end = (min(c.blocks), max(c.blocks) + 1) if c.blocks else (0, 0)
        mine = [ln for ln in c.lines if perform.get(ln) == c.id]
        spoken = [by_short[ln] for ln in c.lines if ln in by_short]
        # A line bound to this clip whose speaker is not seen in it is heard here, whatever its delivery says: the
        # script often leaves a recording or a call unmarked ("Aruni's voice message plays." then a bare line), and a
        # clip with words must never be written silent (the prompt would say "nobody speaks" over a spoken line).
        heard_line = (bool(mine) and not c.speaks) or any(
            (blk := next((i for i in own if i.line_id == stored.line_ids.get(ln)), None)) is not None
            and heard_marked(blk)
            for ln in c.lines
        )
        mode = sound_mode_of(c, bool(mine) and c.speaks, heard_line)
        words = sum(_words(by_short[ln]) for ln in mine if ln in by_short)
        speakers = {str(r["character_id"]) for r in spoken if r.get("character_id")}
        shots.append(
            {
                "id": shot_ids[c.id],
                "production_id": scene["production_id"],
                "scene_id": scene["id"],
                "number": n,
                "title": title_of(c),
                "framing": FRAMING.get(c.size, c.size),
                "duration_s": c.take_s,
                "start_s": start_s,
                "sound_mode": mode,
                "camera_link": "cut",
                "frame_strategy": "generate",
                "speaker_id": next(iter(speakers)) if len(speakers) == 1 and c.speaks and not c.over else None,
                "beats": [
                    {"start_s": a, "end_s": b, "camera": "", "director_line": "", "action": "", "performance": ""}
                    for a, b in windows
                ],
                "block_start": block_start,
                "block_end": block_end,
                "word_target": shot_word_target(c.take_s) if mode in (SPOKEN, "voiceover") else 0,
                "words": words,
                "status": "draft",
                "version": 1,
                "planner": "raphael",
                "card": card_of(c, {}),
                "intent": intent_of(
                    c,
                    own,
                    people,
                    by_short,
                    codes,
                    story=ledger_state.story_of(c, moments, long, clips),
                    states=states_text(staging, items, c, clips),
                ),
                "role": c.role,
                "priority": c.priority,
                "slate": c.slate,
                "handle_in_s": c.handle_in_s,
                "handle_out_s": c.handle_out_s,
                "stage": c.stage,
                "anchor": [slates[a] for a in c.anchor if a in slates],  # the slates a person (and the editor) read
                "blend": c.blend,
            }
        )
        line_facts = []
        for ln in mine:
            row, block = by_short.get(ln), next((i for i in own if i.line_id == stored.line_ids.get(ln)), None)
            if row is None or block is None:
                continue
            at = starts.get(block.index, 0.0)
            over = overrun_seconds(
                start_sec=start_s + at,
                words=_words(row),
                shot_end_sec=start_s + c.take_s,
                delivery=str(row.get("delivery") or ""),
            )
            beat = next((i for i, (a, b) in enumerate(windows) if a <= at < b), len(windows) - 1)
            bound[str(row["id"])] = {
                "shot_id": shot_ids[c.id],
                "beat_index": beat,
                "start_s": round(start_s + at, 2),
                "overrun_s": round(over, 2),
                "words": _words(row),
            }
            line_facts.append({"line_id": ln, "start_s": round(at, 2), "overrun_s": round(over, 2)})
        facts.append({"number": n, "take_s": c.take_s, "need_s": round(need, 2), "lines": line_facts})
        start_s += c.take_s
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for source in lines:
        row = {k: source.get(k) for k in keep}
        row.update(
            bound.get(
                str(source["id"]), {"shot_id": None, "beat_index": None, "start_s": None, "overrun_s": 0, "words": 0}
            )
        )
        line_rows.append(row)
    return shots, line_rows, facts


def _words(row: Row) -> int:
    return words_in(str(row.get("text") or ""))


def design_all(
    scene: Row,
    shots: list[Row],
    line_rows: list[Row],
    clips: list[Clip],
    canon: list[Row],
    production: Row,
    job_id: str,
) -> None:
    """Finish each shot's IR the way the DoP's is and store it with a design whose pins are the ones the shot producer
    will
    compute from these same rows, so `design_stale` is empty. Mutates `shots`."""
    model = parts.step("serialize", "model")
    shots_mod = parts.step("serialize", "shots")
    design = parts.step("serialize", "design")
    prod = model.production_input(production, canon, None)
    scene_in = model.scene_input(scene, shots, line_rows, canon, prod)
    by_number = {n: c for n, c in enumerate(order([c for c in clips if c.ir is not None]), 1)}
    for shot_in, row in zip(scene_in.shots, shots, strict=True):
        clip = by_number[int(row["number"])]
        on_screen = list(row["intent"]["on_screen"])
        entry = {**(clip.ir or {}), "recommendation": camera_hint(clip.ir or {}), "rationale": clip.why}
        ir, rec, why = shots_mod.finish(entry, shot_in, scene_in, prod)
        row["ir"] = ir
        row["design"] = design.design_row(shot_in, ir, rec, why, "raphael", on_screen, job_id)


def fit_report(stored: StoredRaphael, facts: list[Row], envelope_s: Any) -> Row:
    """`scenes.fit_report` in the classic planner's shape, so the screens that read it work for a Raphael scene too.
    Raphael's own report is in `scenes.raphael`. The runtime is the whole bin's takes; the length against the target
    and the
    cap is in the stored seconds."""
    clips = [c for c in stored.clips if c.ir is not None]
    runtime = sum(c.take_s for c in clips)
    issues = [
        {"code": "crowded", "message": item.sentence, "shot": None, "line_id": None}
        for item in stored.left
        if item.code == "clock"
    ]
    silent = sum(c.take_s for c in clips if not c.lines)
    need = sum(max(float(f["take_s"]), float(f["need_s"])) for f in facts)
    return {
        "total_s": runtime,
        "use_s": runtime,
        "envelope_s": int(float(envelope_s)) if envelope_s else 0,
        "planner": "raphael",
        "silent_s": silent,
        "silent_share": round(silent / runtime, 2) if runtime else 0.0,
        "multi_speaker": [],
        "crowded": [],
        "need_s": int(need + 0.999),
        "voiceover": [],
        "critic_notes": [],
        "issues": issues,
    }


def coverage_of(stored: StoredRaphael, script_version: int) -> Row:
    """The scene's coverage plan (`scenes.coverage`) from the intended cut's treatment, so the scene's plan is not
    asked of
    the intent agent either: the axis is the geography, the motif the key image, the progression the arc."""
    t = stored.edit.treatment if stored.edit else None
    arc = " → ".join(f"{a.beat} ({a.feeling})" for a in t.arc) if t else ""
    return {
        "axis": (t.geography if t else "")[:300],
        "motif": (t.key_image if t else "")[:300],
        "progression": arc[:300],
        "by": "raphael",
        "made_for": script_version,
        "written_at": None,
    }


def write(
    scene: Row, lines: list[Row], stored: StoredRaphael, canon: list[Row], production: Row, job_id: str = ""
) -> tuple[list[Row], list[Row], Row]:
    """-> (shots, line rows, the scene's fields). Refuses an approved scene."""
    if scene.get("status") == "approved":
        raise PermissionError("an approved scene is never touched")
    characters = [c for c in canon if c.get("kind") == "character"]
    shots, line_rows, facts = rows_for(scene, lines, stored, characters)
    design_all(scene, shots, line_rows, stored.clips, canon, production, job_id)
    fields = {
        "status": "split",
        "fit_report": fit_report(stored, facts, scene.get("envelope_s")),
        "raphael": stored.data(),
        "coverage": coverage_of(stored, int(scene.get("script_version") or 1)),
    }
    return shots, line_rows, fields


__all__ = ["fit_report", "rows_for", "strings_of", "write"]
