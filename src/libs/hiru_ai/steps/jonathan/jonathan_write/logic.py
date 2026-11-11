"""A Jonathan plan, written as rows (plan/2026-11-05e §4.3 `jonathan_write`, §4.5).

Pure rows in, rows out: the system hands them to `SceneStore.replace_shots`, which deletes the scene's shots and writes
the new ones, so a repeat of the same job gives the same rows (idempotent for Cloud Tasks re-delivery). An APPROVED
scene
is never touched.

    rows_for     the plan's shots → `shots` rows (card, intent, IR and a design with current pins) and the scene's
                 dialogue lines bound to them
    fit_report   what `scenes.fit_report` stores, in the classic planner's shape
    scene_fields the scene update: status, fit_report, the stored plan (`scenes.jonathan`) and the coverage plan

The camera is decided once (§4.5): the author's IR is finished the way the DoP's is (`serialize.shots.finish`), and the
design is stored with the pins the shot producer will compute, so `design_stale` is empty for a Jonathan shot and
neither
the intent agent, the DoP nor the critic is called for it. The serialize step is reached by id (`core.parts`).
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from contracts import sceneplan
from contracts.frame_brief import nearest_option
from contracts.jonathan.checks import mentions, strings
from contracts.jonathan.plan import Problem, norm
from contracts.jonathan.stored import StoredPlan
from contracts.jonathan.wire import JonathanWire, ShotW, card_size
from contracts.producer import CameraField
from contracts.shotplan import Item, shot_clock
from contracts.staging import heard_marked, voice_source
from contracts.timing import default_beats, overrun_seconds, shot_word_target, words_in
from hiru_ai.core import parts

Row = dict[str, Any]
SPOKEN = "dialogue"


def sound_mode_of(shot: ShotW, spoken_here: bool, spoken_over: bool) -> str:
    """How a shot carries its sound (`contracts.veo.SoundMode`): a line on its speaker is dialogue; a line played over a
    listener is voiced off screen; no words and a call for silence is silent (Veo must be told, or it invents
    speech); music alone is music only; else ambient."""
    if spoken_here:
        return SPOKEN
    if spoken_over:
        return "voiceover"
    if shot.sound.silence:
        return "silent"
    if shot.sound.music and not (shot.sound.ambience or shot.sound.effects):
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


def card_of(shot: ShotW) -> Row:
    """The shot's director's card in the keys the shared card reader knows (`serialize.card`): the size, the sound
    design
    and which lines play over a listener. Jonathan's camera lives in the IR, so the card names no camera decisions."""
    return {"size": card_size(shot.size), "take_s": shot.take_s, "use_s": shot.use_s,
            "sound": {"ambience": shot.sound.ambience, "effects": shot.sound.effects, "music": shot.sound.music,
                      "silence": shot.sound.silence},
            "lines": [{"line_id": ln, "on_speaker": not shot.over, "over_whom": shot.over} for ln in shot.lines],
            "cut_in": {"link": shot.link}}


def camera_hint(ir: Row) -> Row:
    """The panel's words for what the author's IR says about the camera, where there is an exact equivalent: the angle
    from `angle`, the lens and the stop from the rig in `camera`, the move from `movement` (the rig only when the
    movement says nothing). A value the panel does not know is left out (the default for the size stands)."""
    raw = ir.get("cinematography")
    cine: Row = raw if isinstance(raw, dict) else {}
    rig, angle_text, move_text = (norm(str(cine.get(k) or "")) for k in ("camera", "angle", "movement"))
    out: Row = {}
    angle = ("Low angle" if "low" in angle_text else "High angle" if "high" in angle_text
             else "Overhead" if "overhead" in angle_text else "")
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


def shot_texts(shot: ShotW) -> list[str]:
    return [*strings(shot.ir.get("subjects")), *strings(shot.ir.get("first_frame"))]


# A part of a person: "Anudi's hand" puts Anudi (in part) in the frame; "Kasun's canopy" is a thing of his, not Kasun
BODY = re.compile(r"(?:hands?|fingers?|fingertips?|face|eyes?|shoulders?|arms?|wrists?|feet|foot|legs?|back|"
                  r"silhouette|profile|knuckles?|lips?|mouth|hair|figure|head|neck|palms?|reflection|shadow)\b")


def names_person(text: str, name: str) -> bool:
    """`text` shows the person called `name`: it names them, other than as the owner of a thing ("Kasun's canopy"). A
    part of them counts ("Anudi's fingertips")."""
    for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
        owner = re.match(r"['’]s?\s+(?:\w+\s+)?(\w+)", text[m.end():])
        if owner is None or BODY.match(owner.group(1).lower()):
            return True
    return False


def subject_texts(shot: ShotW) -> list[tuple[str, str]]:
    """(who it is, the subject's code) for each subject the author lists: the IR's subjects (their description, not
    their action: "looks at Kasun" does not put Kasun in the frame) and the first frame's subjects."""
    out: list[tuple[str, str]] = []
    for s in shot.ir.get("subjects") or []:
        if isinstance(s, dict):
            out.append((str(s.get("description") or ""), str(s.get("id") or "")))
        elif isinstance(s, str):
            out.append((s, ""))
    frame = shot.ir.get("first_frame")
    for s in (frame.get("subjects") if isinstance(frame, dict) else None) or []:
        out.append((str(s), ""))
    return out


def on_screen_of(shot: ShotW, people: dict[str, str], codes: dict[str, str] | None = None) -> list[str]:
    """Canon ids of the people the shot shows (PromptMotion's `_prune_subjects` rule: the author's subjects decide):
    a subject that names the person (or a part of them), a subject with no name but their code, and the listener of a
    shot that plays a line over one. A name in passing ("near Kasun's three-wheeler") is not a person in the frame.
    Never the speaker of a line played over a listener."""
    seen: list[str] = []
    codes = {norm(k): v for k, v in (codes or {}).items()}

    def add(ident: str) -> None:
        if ident and ident not in seen:
            seen.append(ident)

    for text, code_ in subject_texts(shot):
        named = [ident for name, ident in people.items() if names_person(text, name)]
        for ident in named:
            add(ident)
        owned = any(mentions(text, name) for name in people)  # "Kasun's canopy colour": a thing, not a person
        if not named and not owned and norm(code_) in codes:
            add(codes[norm(code_)])
    if shot.over and norm(shot.over) in people:
        add(people[norm(shot.over)])
    return seen


def intent_of(shot: ShotW, items: list[Item], people: dict[str, str], line_rows: dict[str, Row],
              codes: dict[str, str] | None = None) -> Row:
    """The shot as its intent (`contracts.staging.ShotIntent`), written `by = "jonathan"`: what it is for, what we see,
    who is in frame and who is only heard. An intent no agent replaces, so the intent agent is skipped. Who speaks a
    line on camera is seen; a voice is a phone only when the SCRIPT says so (the line's delivery, "Her phone rings"),
    never because the author's own words mention a phone ("she sees the phone in his hand")."""
    on_screen = on_screen_of(shot, people, codes)
    if not shot.over:  # the speaker of a line said on camera is in the frame, unless the script marks it heard
        by_id = {str(r.get("id")): r for r in line_rows.values() if r}
        for item in items:
            row = by_id.get(str(item.line_id)) if item.is_line else None
            who = str(row.get("character_id") or "") if row else ""
            if who and who not in on_screen and not heard_marked(item):
                on_screen.append(who)
    heard: list[str] = []
    for ln in shot.lines:
        row = line_rows.get(ln)
        who = str(row["character_id"]) if row and row.get("character_id") else ""
        if who and who not in on_screen and who not in heard:
            heard.append(who)
    source = (voice_source(items) or "off_screen") if heard else ""
    sees = "; ".join(str(b.get("action") or "") for b in shot.ir.get("beats") or [] if isinstance(b, dict)
                     and b.get("action"))
    return {"purpose": shot.why[:400], "what_we_see": (sees or shot.why)[:700], "emotional_beat": "",
            "on_screen": on_screen, "heard_only": heard, "voice_source": source, "by": "jonathan", "made_for": "",
            "written_at": None}


def title_of(shot: ShotW) -> str:
    words = shot.why.split()
    return " ".join(words[:8]).rstrip(".,;:") or f"Shot {shot.n}"


def rows_for(scene: Row, lines: list[Row], stored: StoredPlan, characters: list[Row]
             ) -> tuple[list[Row], list[Row], list[Row]]:
    """-> (the shot rows without IR and design, the line rows bound to them, the per-shot clock facts). New shot ids,
    as a
    re-split makes them. The lines' words are the script's: a line is bound by id and never copied from the plan."""
    plan: JonathanWire = stored.plan
    items = sceneplan.scene_items(scene, lines)
    by_index = {i.index: i for i in items}
    rows_by_id = {str(ln["id"]): ln for ln in lines}
    by_short = {short: rows_by_id[real] for short, real in stored.line_ids.items() if real in rows_by_id}
    people = people_by_name(characters)
    codes = {str(c["code"]): str(c["id"]) for c in characters if c.get("code")}
    shot_ids = {s.n: str(uuid4()) for s in plan.shots}
    shots: list[Row] = []
    facts: list[Row] = []
    bound: dict[str, Row] = {}
    start_s, previous_end = 0, 0
    for s in plan.shots:
        own = [by_index[b] for b in s.blocks if b in by_index]
        slots, need = shot_clock(own)
        starts = {slot.index: slot.start_s for slot in slots if slot.is_line}
        windows = default_beats(s.take_s)
        block_start, block_end = (min(s.blocks), max(s.blocks) + 1) if s.blocks else (previous_end, previous_end)
        previous_end = block_end
        spoken = [by_short[ln] for ln in s.lines if ln in by_short]
        mode = sound_mode_of(s, bool(spoken) and not s.over, bool(spoken) and bool(s.over))
        words = sum(_words(r) for r in spoken)
        speakers = {str(r["character_id"]) for r in spoken if r.get("character_id")}
        link = "cut" if s.n == 1 and s.link == "continuous" else s.link
        shots.append({
            "id": shot_ids[s.n], "production_id": scene["production_id"], "scene_id": scene["id"], "number": s.n,
            "title": title_of(s), "framing": s.framing, "duration_s": s.take_s, "start_s": start_s, "sound_mode": mode,
            "camera_link": link, "frame_strategy": "carry_last_frame" if link == "continuous" else "generate",
            "speaker_id": next(iter(speakers)) if len(speakers) == 1 and not s.over else None,
            "beats": [{"start_s": a, "end_s": b, "camera": "", "director_line": "", "action": "", "performance": ""}
                      for a, b in windows],
            "block_start": block_start, "block_end": block_end,
            "word_target": shot_word_target(s.take_s) if mode in (SPOKEN, "voiceover") else 0, "words": words,
            "status": "draft", "version": 1, "planner": "jonathan", "card": card_of(s),
            "intent": intent_of(s, own, people, by_short, codes)})
        line_facts = []
        for ln in s.lines:
            row, block = by_short.get(ln), next((i for i in own if i.line_id == stored.line_ids.get(ln)), None)
            if row is None or block is None:
                continue
            at = starts.get(block.index, 0.0)
            over = overrun_seconds(start_sec=start_s + at, words=_words(row),
                                   shot_end_sec=start_s + s.take_s, delivery=str(row.get("delivery") or ""))
            beat = next((i for i, (a, b) in enumerate(windows) if a <= at < b), len(windows) - 1)
            bound[str(row["id"])] = {"shot_id": shot_ids[s.n], "beat_index": beat, "start_s": round(start_s + at, 2),
                                     "overrun_s": round(over, 2), "words": _words(row)}
            line_facts.append({"line_id": ln, "start_s": round(at, 2), "overrun_s": round(over, 2)})
        facts.append({"number": s.n, "take_s": s.take_s, "need_s": round(need, 2), "lines": line_facts})
        start_s += s.take_s
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for source in lines:
        row = {k: source.get(k) for k in keep}
        row.update(bound.get(str(source["id"]), {"shot_id": None, "beat_index": None, "start_s": None, "overrun_s": 0,
                                                 "words": 0}))
        line_rows.append(row)
    return shots, line_rows, facts


def _words(row: Row) -> int:
    return words_in(str(row.get("text") or ""))


def design_all(scene: Row, shots: list[Row], line_rows: list[Row], plan: JonathanWire, canon: list[Row],
               production: Row, job_id: str) -> None:
    """Finish each shot's IR the way the DoP's is and store it with a design whose pins are the ones the shot producer
    will compute from these same rows, so `design_stale` is empty (§4.5). Mutates `shots`."""
    model = parts.step("serialize", "model")
    shots_mod = parts.step("serialize", "shots")
    design = parts.step("serialize", "design")
    prod = model.production_input(production, canon, None)
    scene_in = model.scene_input(scene, shots, line_rows, canon, prod)
    by_number = {s.n: s for s in plan.shots}
    for shot_in, row in zip(scene_in.shots, shots, strict=True):
        wire = by_number[int(row["number"])]
        on_screen = list(row["intent"]["on_screen"])
        entry = {**wire.ir, "recommendation": camera_hint(wire.ir), "rationale": wire.why}
        ir, rec, why = shots_mod.finish(entry, shot_in, scene_in, prod)
        row["ir"] = ir
        row["design"] = design.design_row(shot_in, ir, rec, why, "jonathan", on_screen, job_id)


def fit_report(plan: JonathanWire, facts: list[Row], envelope_s: Any, problems: list[Problem]) -> Row:
    """`scenes.fit_report` in the classic planner's shape (see `contracts.sceneplan.fit_report`), so the screens that
    read
    it work for a Jonathan scene too. Jonathan's own report is in `scenes.jonathan`."""
    runtime = sum(s.take_s for s in plan.shots)
    issues = [{"code": "crowded" if p.code == "clock" else p.code, "message": p.sentence, "shot": p.shots[0]
               if p.shots else None, "line_id": None} for p in problems if p.fix == "report"
              and p.code in ("clock", "envelope")]
    silent = sum(s.take_s for s in plan.shots if not s.lines)
    need = sum(max(float(f["take_s"]), float(f["need_s"])) for f in facts)
    kept = sum(s.use_s for s in plan.shots)  # what the edit keeps of the takes: the length the envelope is a budget for
    if envelope_s and kept > float(envelope_s) * 1.2:  # the producer's budget is met within about 20% (the lab's rule)
        issues.append({"code": "envelope", "message": f"The edit keeps {kept} s of {runtime} s of takes; the scene's "
                       f"budget is {int(float(envelope_s))} s ({kept - int(float(envelope_s))} s over).", "shot": None,
                       "line_id": None})
    return {"total_s": runtime, "use_s": kept, "envelope_s": int(float(envelope_s)) if envelope_s else 0,
            "planner": "jonathan",
            "silent_s": silent, "silent_share": round(silent / runtime, 2) if runtime else 0.0, "multi_speaker": [],
            "crowded": [i["shot"] for i in issues if i["code"] == "crowded" and i["shot"] is not None],
            "need_s": int(need + 0.999), "voiceover": [s.n for s in plan.shots if s.over], "critic_notes": [],
            "issues": issues}


def coverage_of(plan: JonathanWire, script_version: int) -> Row:
    """The scene's coverage plan (`scenes.coverage`, `contracts.staging.ScenePlan`) from the author's treatment, so the
    scene's plan is not asked of the intent agent either: the axis is the geography, the motif the key image, the
    progression the arc."""
    t = plan.treatment
    arc = " → ".join(f"{a.beat} ({a.feeling})" for a in t.arc)
    return {"axis": t.geography[:300], "motif": t.key_image[:300], "progression": arc[:300], "by": "jonathan",
            "made_for": script_version, "written_at": None}


def write(scene: Row, lines: list[Row], stored: StoredPlan, canon: list[Row], production: Row,
          job_id: str = "") -> tuple[list[Row], list[Row], Row]:
    """-> (shots, line rows, the scene's fields). Refuses an approved scene."""
    if scene.get("status") == "approved":
        raise PermissionError("an approved scene is never touched")
    characters = [c for c in canon if c.get("kind") == "character"]
    shots, line_rows, facts = rows_for(scene, lines, stored, characters)
    design_all(scene, shots, line_rows, stored.plan, canon, production, job_id)
    report = fit_report(stored.plan, facts, scene.get("envelope_s"), stored.problems)
    fields = {"status": "split", "fit_report": report, "jonathan": stored.data(),
              "coverage": coverage_of(stored.plan, int(scene.get("script_version") or 1))}
    return shots, line_rows, fields

