"""A plan, written as rows (plan/2026-11-04b §5.3 `adam_write`).

Pure rows in, rows out: the system hands them to `SceneStore.replace_shots`, which deletes the scene's shots and
writes the new ones, so a repeat of the same job gives the same rows (idempotent for Cloud Tasks re-delivery). An
APPROVED scene is never touched: the system skips it before it ever asks for a plan, and `write` refuses it here too.

    rows_for     the plan's cards → `shots` rows (with `card`, `planner`) and the scene's dialogue lines bound to them
    fit_report   what `scenes.fit_report` stores, in the classic planner's shape, so the screens that read it work
    scene_fields the scene update: status, fit_report and the stored plan (`scenes.adam`)
    apply_removed  elaborations a person took out are never added back, whatever the re-plan writes
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from contracts.adam.mapping import card_to_row
from contracts.adam.plan import AdamPlan, Moment, ShotCard, norm, people_of, subject_of
from contracts.adam.stored import Removed, StoredPlan
from contracts.timing import shot_word_target

Row = dict[str, Any]
SPOKEN = "dialogue"


def sound_mode_of(card: ShotCard, said_on_screen: bool, said_off_screen: bool) -> str:
    """How a shot carries its sound (`contracts.veo.SoundMode`). A line on its speaker is dialogue; a line played over a
    listener is voiced off screen, so the shot is a voice-over and the speaker is never shown talking; a card with no
    words is silent when it asks for silence (Veo must be told, or it invents speech), music only when it has music
    and nothing else, else ambient."""
    if said_on_screen:
        return SPOKEN
    if said_off_screen:
        return "voiceover"
    if card.sound.silence:
        return "silent"
    if card.sound.music and not (card.sound.ambience or card.sound.effects):
        return "music_only"
    return "ambient"


def beats_of(card: ShotCard) -> list[Row]:
    """The card's beats as the shot's `beats` column (windows in seconds, what the camera does, what is acted)."""
    if not card.beats:
        return [{"start_s": 0, "end_s": card.take_s, "camera": "", "director_line": "", "action": "",
                 "performance": ""}]
    out = []
    for b in card.beats:
        start, end = (b.window[0], b.window[1]) if len(b.window) >= 2 else (0, card.take_s)
        out.append({"start_s": start, "end_s": end, "camera": b.camera, "director_line": "", "action": b.action,
                    "performance": b.performance})
    return out


def _beat_of(card: ShotCard, at_s: float) -> int:
    for i, b in enumerate(card.beats):
        if len(b.window) >= 2 and b.window[0] <= at_s < b.window[1]:
            return i
    return 0


def rows_for(scene: Row, lines: list[Row], plan: AdamPlan, line_ids: dict[str, str], fit: dict[str, Any],
             people: dict[str, str] | None = None) -> tuple[list[Row], list[Row]]:
    """-> (the shot rows, the line rows bound to them). New shot ids, as a re-split makes them. `line_ids` maps the
    id an agent used (L1) to the dialogue line's real id; `fit` is `adam_fit`'s answer for the same plan (where each
    line starts inside its take); `people` maps a character's name (any case) to their canon id, for the intent."""
    rows_by_id = {str(ln["id"]): ln for ln in lines}
    people = people or {}
    by_short = {short: rows_by_id[real] for short, real in line_ids.items() if real in rows_by_id}
    clock = {c["number"]: {ln["line_id"]: ln for ln in c["lines"]} for c in fit.get("cards") or []}
    shot_ids = {c.number: str(uuid4()) for c in plan.cards}
    shots: list[Row] = []
    bound: dict[str, Row] = {}
    start_s, previous_end = 0, 0
    for card in plan.cards:
        mapped = card_to_row(card, plan.moments, fallback=(previous_end, previous_end))
        previous_end = mapped["block_end"]
        on: list[tuple[Any, Row]] = []
        off: list[tuple[Any, Row]] = []
        for cl in card.lines:
            real = rows_by_id.get(line_ids.get(cl.line_id, ""))
            if real is not None:
                (on if cl.on_speaker else off).append((cl, real))
        mode = sound_mode_of(card, bool(on), bool(off))
        words = sum(int(clock.get(card.number, {}).get(cl.line_id, {}).get("words", 0)) for cl, _ in on + off)
        speakers = {str(r["character_id"]) for _, r in on if r.get("character_id")}
        shots.append({
            "id": shot_ids[card.number], "production_id": scene["production_id"], "scene_id": scene["id"],
            "number": card.number, "title": mapped["title"], "framing": mapped["framing"],
            "duration_s": mapped["duration_s"], "start_s": start_s, "sound_mode": mode,
            "camera_link": mapped["camera_link"],
            "frame_strategy": "carry_last_frame" if mapped["camera_link"] == "continuous" and card.number > 1
            else "generate",
            "speaker_id": next(iter(speakers)) if len(speakers) == 1 else None,
            "beats": beats_of(card), "block_start": mapped["block_start"], "block_end": mapped["block_end"],
            "word_target": shot_word_target(card.take_s) if mode in (SPOKEN, "voiceover") else 0, "words": words,
            "status": "draft", "version": 1, "planner": "adam", "card": mapped["card"],
            "intent": intent_of(card, plan, people, by_short)})
        start_s += card.take_s
        for cl, real in on + off:
            heard = clock.get(card.number, {}).get(cl.line_id, {})
            at = float(heard.get("start_s", 0.0))
            bound[str(real["id"])] = {"shot_id": shot_ids[card.number], "beat_index": _beat_of(card, at),
                                      "start_s": round(shots[-1]["start_s"] + at, 2),
                                      "overrun_s": float(heard.get("overrun_s", 0.0)),
                                      "words": int(heard.get("words", 0))}
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for ln in lines:
        row = {k: ln.get(k) for k in keep}
        row.update(bound.get(str(ln["id"]), {"shot_id": None, "beat_index": None, "start_s": None, "overrun_s": 0,
                                             "words": 0}))
        line_rows.append(row)
    return shots, line_rows


PHONE = ("phone", "call", "receiver", "line", "mobile")
OBJECT_SHOTS = ("hands", "implied_action")


def intent_of(card: ShotCard, plan: AdamPlan, people: dict[str, str], line_rows: dict[str, Row]) -> Row:
    """The card as the shot's intent (`contracts.staging.ShotIntent`), written `by = "adam"`: what the shot is for, what
    we see, who is in frame and who is only heard. An intent no agent replaces, so the intent agent is skipped
    (Phase 7).
    A line whose speaker is not in frame makes that speaker heard-only: the phone voice of someone not in the scene, or
    a line the card plays over a listener's face (the speaker is never shown talking)."""
    by_id = {m.id: m for m in plan.moments}
    subject = subject_of(card, by_id)
    if card.size == "INSERT":
        shown = [subject] if subject and any(by_id[i].kind in OBJECT_SHOTS for i in card.moments if i in by_id) else []
    elif card.arrangement in ("single", "pov"):
        shown = [subject] if subject else []
    else:
        shown = sorted(people_of(card, by_id))
    on_screen = [people[n] for n in shown if n in people]
    heard: list[str] = []
    for cl in card.lines:
        row = line_rows.get(cl.line_id)
        who = str(row["character_id"]) if row and row.get("character_id") else ""
        if who and who not in on_screen and who not in heard:
            heard.append(who)
    said = norm(" ".join(f"{by_id[i].seen} {by_id[i].heard}" for i in card.moments if i in by_id))
    source = ("phone" if any(w in said for w in PHONE) else "off_screen") if heard else ""
    sees = "; ".join(b.action for b in card.beats if b.action) or card.title
    return {"purpose": card.purpose[:400], "what_we_see": sees[:700], "emotional_beat": card.emotional_beat[:200],
            "on_screen": on_screen, "heard_only": heard, "voice_source": source, "by": "adam", "made_for": "",
            "written_at": None}


def coverage_of(plan: AdamPlan, script_version: int) -> Row:
    """The scene's coverage plan (`scenes.coverage`, `contracts.staging.ScenePlan`) from the chosen treatment, so the
    scene's plan is not asked of the intent agent either."""
    t = plan.treatment
    behaviour = "; ".join(s.camera_behaviour for s in t.sections if s.camera_behaviour)
    motif = t.motif or (t.plant.object if t.plant else "")
    progression = f"sizes {' > '.join(t.size_arc)}" + (f"; sound: {t.sound_concept}" if t.sound_concept else "")
    return {"axis": f"{t.pov}. {behaviour}".strip(". ")[:300], "motif": motif[:300], "progression": progression[:300],
            "by": "adam", "made_for": script_version, "written_at": None}


def fit_report(plan: AdamPlan, fit: dict[str, Any], notes: list[str]) -> Row:
    """`scenes.fit_report` in the classic planner's shape (see `contracts.sceneplan.fit_report`), so the screens that
    read it work for an Adam scene too. Adam's own reports are in `scenes.adam.report`."""
    issues = [{"code": i["code"], "message": i["message"], "shot": i.get("card"), "line_id": i.get("line_id")}
              for i in fit.get("issues") or []]
    crowded = [i["shot"] for i in issues if i["code"] == "crowded" and i["shot"] is not None]
    runtime = float(fit.get("runtime_s") or 0)
    need = sum(max(float(c.get("take_s", 0)), float(c.get("need_s", 0))) for c in fit.get("cards") or [])
    voiced = [c.number for c in plan.cards if any(not ln.on_speaker for ln in c.lines)]
    envelope = fit.get("envelope_s")
    return {"total_s": int(runtime), "envelope_s": int(envelope) if envelope else 0, "planner": "adam",
            "silent_s": sum(c.take_s for c in plan.cards if not c.lines), "silent_share": round(
                sum(c.take_s for c in plan.cards if not c.lines) / runtime, 2) if runtime else 0.0,
            "multi_speaker": [], "crowded": crowded, "need_s": int(need + 0.999), "voiceover": voiced,
            "critic_notes": list(notes), "issues": issues}


def apply_removed(moments: list[Moment], removed: list[Removed]) -> tuple[list[Moment], list[str]]:
    """The moments without any elaboration a person already took out. -> (moments, ids of those dropped). A script
    moment is never dropped here."""
    gone = [m.id for m in moments if any(r.matches(m) for r in removed)]
    return [m for m in moments if m.id not in set(gone)], gone


def scene_fields(stored: StoredPlan, report: Row, script_version: int = 1) -> Row:
    return {"status": "split", "fit_report": report, "adam": stored.data(),
            "coverage": coverage_of(stored.plan(), script_version)}


def write(scene: Row, lines: list[Row], stored: StoredPlan, fit: dict[str, Any], notes: list[str],
          people: dict[str, str] | None = None) -> tuple[list[Row], list[Row], Row]:
    """-> (shots, line rows, the scene's fields). Refuses an approved scene."""
    if scene.get("status") == "approved":
        raise PermissionError("an approved scene is never touched")
    plan = stored.plan()
    shots, line_rows = rows_for(scene, lines, plan, stored.line_ids, fit, people)
    return shots, line_rows, scene_fields(stored, fit_report(plan, fit, notes), int(scene.get("script_version") or 1))


def describe(removed: Removed) -> str:
    return f"{removed.kind} on {', '.join(f'b{b}' for b in removed.blocks) or 'the scene'}" + (
        f" ({removed.seen})" if norm(removed.seen) else "")
