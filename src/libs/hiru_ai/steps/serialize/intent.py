"""The intent agent: what each shot of a scene is FOR, what the camera SEES, who is only HEARD, and
the scene's coverage plan. One call per scene, BEFORE the camera design (plan/2026-11-01 §B).

Ported in spirit from PromptMotion Nova's producer, which writes `purpose`, `visual_intent`,
`emotional_beat` per shot and a `ScenePlan` per scene, so the DoP realises a decision instead of
guessing one from raw script lines. Hiru's script and shot list are already approved, so this
agent READS them: it never adds an event, changes a size or touches the words.

Absent-safe: without a key, or when the call fails, the rules write a plainer intent from the
script (the actions, who is heard) and the scene plan states only the size progression.
A person's own intent or plan is never replaced (`by == "person"`).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from contracts.producer import FRAMING_LABEL
from contracts.shotplan import Item, timeline_text
from contracts.staging import VOICE_SOURCES, ScenePlan, ShotIntent, heard_marked, source_phrase
from hiru_ai.steps.serialize.model import ProductionInput, SceneInput, ShotInput

_logger = logging.getLogger(__name__)
Row = dict[str, Any]
_SINHALA = re.compile(r"[඀-෿‌‍]+(?:[\s,.!?'\"“”‘’]*[඀-෿‌‍]+)*")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean(text: object, limit: int) -> str:
    return " ".join(_SINHALA.sub(" ", str(text or "")).split())[:limit]


# ── the prompt ─────────────────────────────────────────────────────────────────────────────


def production_block(prod: ProductionInput) -> str:
    """Identical for every scene of a job (prompt cache)."""
    cast = "\n".join(f"- {c.code} {c.name}" + (f" ({c.gender})" if c.gender else "") for c in prod.cast) \
        or "- none identified"
    return (f"<production>\nPRODUCTION: {prod.title or 'untitled'}\nCAST:\n{cast}\n</production>")


def context_block(scene: SceneInput) -> str:
    """Where the scene sits in the story. Shared with the DoP's scene prompt."""
    bits = [f"EPISODE {scene.episode_number}" + (f": {scene.episode_title}" if scene.episode_title else ""),
            f"EPISODE SYNOPSIS: {scene.synopsis}" if scene.synopsis else "",
            f"THE SCENE BEFORE: {scene.before}" if scene.before else "",
            f"THIS SCENE: {scene.title}" if scene.title else "",
            f"DIRECTOR'S NOTE ON THE SCENE: {scene.note}" if scene.note.strip() else "",
            f"THE SCENE AFTER: {scene.after}" if scene.after else ""]
    return "\n".join(b for b in bits if b)


def block_label(i: Item) -> str:
    """How an action block is named in a prompt: filmed, implied, told another way, or not filmed."""
    if i.kind != "action":
        return i.kind.upper()
    if i.screen == "inner":
        return "STORY NOTE (not filmed)"
    if i.screen == "info":
        return "THE VIEWER LEARNS"
    return "ACTION (implied)" if i.implied else "ACTION"


def block_text(i: Item) -> str:
    text = i.text.strip()
    return f"{text} (show it with an insert, a line or a look)" if i.kind == "action" and i.screen == "info" else text


def _listing(shot: ShotInput) -> str:
    out = []
    for i in shot.items:
        if i.is_line:
            who = next((c for c in shot.cast if c.id == i.speaker_id), None)
            label = f"{who.name} ({who.code})" if who else i.speaker
            delivery = f" ({i.delivery})" if i.delivery else ""
            out.append(f"  [{i.index}] LINE {label}{delivery}: {i.text}")
        elif i.text.strip():
            out.append(f"  [{i.index}] {block_label(i)}: {block_text(i)}")
    return "\n".join(out)


def _timeline(shot: ShotInput) -> str:
    names = {c.id: c.name for c in shot.cast}
    return timeline_text(shot.items, lambda i: names.get(i.speaker_id or "", i.speaker.title()))


def scene_prompt(scene: SceneInput, shots: list[ShotInput]) -> str:
    blocks = []
    for s in shots:
        named = ", ".join(f"{c.name} ({c.code})" for c in s.cast) or "nobody identified"
        blocks.append(f"SHOT {s.code} — number {s.number}, {s.duration_s} s, "
                      f"{FRAMING_LABEL.get(s.framing, s.framing)}, sound {s.sound_mode}"
                      + (f", titled \"{s.title}\"" if s.title else "")
                      + f"\nPEOPLE THE SCRIPT CONNECTS TO IT: {named}"
                      + f"\nSCRIPT (block numbers in brackets):\n{_listing(s)}"
                      + (f"\nTIMELINE (seconds from the start of the shot): {_timeline(s)}" if _timeline(s) else ""))
    place = scene.location.name if scene.location else ""
    reading = scene.reading.text() if scene.reading else ""
    head = [f"SCENE {scene.number}: {scene.heading}", f"PLACE: {place}" if place else "",
            f"TIME: {scene.time_of_day}" if scene.time_of_day else "", context_block(scene),
            "READING OF THE SCENE (decided before the shots):\n" + reading if reading else "",
            "WHERE EVERYONE IS (the staging map):\n" + scene.staging.text()
            if scene.staging and scene.staging.marks else ""]
    numbers = ", ".join(str(s.number) for s in shots)
    return ("<scene>\n" + "\n".join(h for h in head if h) + "\n\n" + "\n\n".join(blocks) + "\n</scene>\n\n"
            f"Return one entry per shot, numbered {numbers}, and the scene's coverage.")


# ── the answer ─────────────────────────────────────────────────────────────────────────────


def _ids(codes: object, by_code: dict[str, str]) -> list[str]:
    out: list[str] = []
    for code in codes if isinstance(codes, list) else []:
        cid = by_code.get(str(code).strip().upper())
        if cid and cid not in out:
            out.append(cid)
    return out


def _names(text: str, prod: ProductionInput) -> str:
    for c in sorted(prod.cast, key=lambda c: len(c.code), reverse=True):
        if c.code and c.name:
            text = re.sub(rf"\b{re.escape(c.code)}\b", c.name, text)
    return text


def from_model(entry: Row, shot: ShotInput, prod: ProductionInput) -> ShotIntent:
    by_code = {c.code.upper(): c.id for c in prod.cast}
    # A line MARKED as heard (on the phone, off screen) is heard whatever the model said.
    marked = {i.speaker_id for i in shot.items if i.speaker_id and heard_marked(i)}
    heard = list(dict.fromkeys([*_ids(entry.get("heard_only"), by_code), *[c.id for c in shot.cast if c.id in marked]]))
    on = [c for c in _ids(entry.get("on_screen"), by_code) if c not in heard]
    source = str(entry.get("voice_source") or "")
    return ShotIntent(purpose=_names(_clean(entry.get("purpose"), 400), prod),
                      what_we_see=_names(_clean(entry.get("what_we_see"), 700), prod),
                      emotional_beat=_names(_clean(entry.get("emotional_beat"), 200), prod),
                      on_screen=on, heard_only=heard,
                      voice_source=source if (source in VOICE_SOURCES and heard) else "",  # type: ignore[arg-type]
                      split_after=_split_after(entry.get("split_after"), shot),
                      split_reason=_clean(entry.get("split_reason"), 200) if _split_after(
                          entry.get("split_after"), shot) is not None else "",
                      by="model", made_for=shot.basis, written_at=_now())


def _split_after(value: object, shot: ShotInput) -> int | None:
    """A block the shot can be cut after: inside it, never its last block, and never a bare number
    the model made up."""
    try:
        at = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    indexes = [i.index for i in shot.items]
    return at if at in indexes[:-1] else None


def listener(scene: SceneInput, shot: ShotInput) -> list[str]:
    """Who hears a voice when the shot names nobody present: the nearest person seen speaking on
    camera in the scene, before the shot first, then after it ([] when nobody is)."""
    def speaking(s: ShotInput) -> list[str]:
        return [c.id for c in s.seen if c.id in s.speaker_ids and c.id not in shot.staged.heard_only]

    # The person the last actions before the voice are about holds the phone ("Anudi smiles back.
    # Her phone rings." then the call): a name beats "whoever spoke last".
    pool = {c.id: c for s in scene.shots for c in s.cast if c.id not in shot.staged.heard_only}
    before_items = [i for s in scene.shots if s.number <= shot.number for i in s.items
                    if s.number < shot.number or i.index < shot.items[0].index]
    spoke = max((i.index for i in before_items if i.is_line and i.speaker_id not in shot.staged.heard_only),
                default=-1)  # a line spoken since then settles who is there
    earlier = [i for i in before_items if i.kind == "action" and i.text.strip() and i.index > spoke]
    for item in reversed(earlier[-3:]):
        named = [c for c in pool.values() if c.name and re.search(rf"\b{re.escape(c.name)}\b", item.text, re.I)]
        if named:
            return [named[-1].id]

    before = [s for s in scene.shots if s.number < shot.number and speaking(s)]
    after = [s for s in scene.shots if s.number > shot.number and speaking(s)]
    nearest = before[-1] if before else after[0] if after else None
    return speaking(nearest)[:1] if nearest else []


def _from_reading(scene: SceneInput | None, shot: ShotInput) -> tuple[str, str]:
    """→ (what the shot serves, how the feeling moves), straight from the scene's reading, for the rules' intent:
    what each person in the shot wants, and the turn when the shot holds one. ("", "") without a reading."""
    reading = scene.reading if scene is not None else None
    if reading is None:
        return "", ""
    wants = "; ".join(f"{who} {verb}" for who, verb in shot.feeling.person_wants.items())
    turns = bool(shot.feeling.turn_beats)
    purpose = ("where the feeling turns" if turns else "") + (f" ({wants})" if wants and turns else wants)
    moves = f"{reading.value.start} to {reading.value.end}" if reading.value.start and reading.value.end else ""
    return purpose.strip(), (moves if turns and moves else reading.tone)


def by_rules(shot: ShotInput, scene: SceneInput | None = None) -> ShotIntent:
    """A plainer intent from the script itself: its actions, who is only heard, and (when a voice
    plays over nobody) the person nearest in the scene who is there to hear it."""
    # Only what the camera shows: a thought is not filmed and information is told another way (plan 2026-11-01b).
    actions = [i.text.strip().rstrip(".") for i in shot.items
               if i.kind == "action" and i.text.strip() and i.screen not in ("info", "inner")]
    heard = shot.heard
    seen = shot.seen
    added = listener(scene, shot) if (scene is not None and heard and not seen) else []
    if added:
        by_id = {c.id: c for s in scene.shots for c in s.cast} if scene is not None else {}
        seen = [by_id[c] for c in added if c in by_id]
    holder = seen[0].name if seen and shot.staged.voice_source == "phone" else ""
    picture = ". ".join(actions[:3])
    purpose, beat = _from_reading(scene, shot)
    if heard:
        picture += (". " if picture else "") + (
            f"{' and '.join(c.name for c in heard)} is heard {source_phrase(shot.staged.voice_source, holder)}"
            " and is not in the place")
    why = shot.title or (actions[0] if actions else "")
    return ShotIntent(purpose=_clean(" — ".join(p for p in (why, purpose) if p), 400),
                      what_we_see=_clean(picture + ("." if picture else ""), 700), emotional_beat=_clean(beat, 200),
                      on_screen=list(dict.fromkeys([*shot.staged.on_screen, *added])),
                      heard_only=list(shot.staged.heard_only),
                      voice_source=shot.staged.voice_source if heard else "",  # type: ignore[arg-type]
                      by="rules", made_for=shot.basis, written_at=_now())


def plan_by_rules(scene: SceneInput) -> ScenePlan:
    sizes = [FRAMING_LABEL.get(s.framing, s.framing).lower() for s in scene.shots]
    steps = [s for n, s in enumerate(sizes) if n == 0 or s != sizes[n - 1]]
    return ScenePlan(progression=" → ".join(steps), by="rules", made_for=scene.script_version, written_at=_now())


def plan_from_model(raw: object, scene: SceneInput, prod: ProductionInput) -> ScenePlan | None:
    if not isinstance(raw, dict):
        return None
    plan = ScenePlan(axis=_names(_clean(raw.get("axis"), 300), prod), motif=_names(_clean(raw.get("motif"), 300), prod),
                     progression=_names(_clean(raw.get("progression"), 300), prod), by="model",
                     made_for=scene.script_version, written_at=_now())
    return plan if plan.axis or plan.progression else None


def write(ask: Callable[[str, str], Row] | None, scene: SceneInput, shots: list[ShotInput], prod: ProductionInput, *,
          plan: bool) -> tuple[dict[int, ShotIntent], ScenePlan | None]:
    """-> ({shot number: intent} for every shot in `shots`, the scene plan when `plan`).
    Matched BY NUMBER; a shot the model skipped gets the rules' intent. `ask(production, scene)` is the `shot_intent`
    agent's answer (None = no model)."""
    answered: dict[int, Row] = {}
    raw_plan: object = None
    if ask is not None and shots:
        try:
            answer = ask(production_block(prod), scene_prompt(scene, shots))
            wanted = {s.number for s in shots}
            for entry in answer.get("shots") or []:
                try:
                    number = int(entry.get("number"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if number in wanted and number not in answered:
                    answered[number] = entry
            raw_plan = answer.get("coverage")
        except Exception:
            _logger.warning("scene %s intent call failed", scene.id, exc_info=True)
    intents = {s.number: (from_model(answered[s.number], s, prod) if s.number in answered else by_rules(s, scene))
               for s in shots}
    scene_plan = (plan_from_model(raw_plan, scene, prod) or plan_by_rules(scene)) if plan else None
    return intents, scene_plan
