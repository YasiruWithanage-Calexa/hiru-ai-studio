"""Staging: who the camera SEES in a shot, who is only HEARD, and what each shot is for
(plan/2026-11-01/PLAN.md).

One reading, shared by every hop that needs it, so they cannot disagree about who is in frame:
the shot producer (the DoP prompt and the video prompt), frame_render (which reference sheets
are attached and who the "People" line names) and the API (the Production panel's checks).

Who is visible, strongest first:

1. A person's own cast edits: a person they ADDED is visible, one they REMOVED is not in the shot.
2. The shot's INTENT (`shots.intent`), written before the camera design by the intent agent, or by
   a person in the Production panel.
3. The DoP's own answer (`design.on_screen`).
4. Rules: everyone in the shot, minus speakers who are only heard.

At every level, a speaker whose lines are MARKED as heard (on the phone, off screen, voice over)
stays off screen unless a person added them. A face nobody should see is the costliest mistake
a frame can make: a reference sheet attached for a voice puts that person in the picture.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.canon import name_key
from contracts.producer import FRAMING_LABEL, CameraCheck, CameraSettings, PersonEdits, cast_in, pictured_text
from contracts.shotplan import HEARD_MARKS, Item

# Where a voice that is heard but not seen comes from. "" = not said (an ordinary voice off screen).
VoiceSource = Literal["", "phone", "radio", "television", "speaker", "off_screen"]
VOICE_SOURCES: tuple[str, ...] = ("", "phone", "radio", "television", "speaker", "off_screen")
IntentBy = Literal["", "model", "rules", "person", "adam", "david", "jonathan"]
# Who writes an intent or a coverage plan that no agent replaces: a person, or Shot Planner Adam, whose shot card
# already says what the shot is for (plan/2026-11-04b Phase 7), or Shot Planner David, whose one author call also wrote
# the camera design (plan/2026-11-05e §4.5).
# Shot Planner Jonathan (plan/2026-11-06b) writes the camera design in its one author call too.
AUTHORED: tuple[str, ...] = ("person", "adam", "david", "jonathan")

_SOURCE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phone", ("phone", "mobile", "call", "rings", "ringing", "ringtone", "dial")),
    ("radio", ("radio",)),
    ("television", ("television", " tv ", "tv.", "news bulletin")),
    ("speaker", ("intercom", "loudspeaker", "announcement", "public address")),
    ("off_screen", ("off screen", "off-screen", "o.s", "from inside", "another room", "next room", "outside")),
)
# How the prompts say where a heard voice comes from. `{holder}` is the person holding the phone.
SOURCE_PHRASE: dict[str, str] = {
    "phone": "through the phone{holder}, thin and compressed like a real call",
    "radio": "from a radio in the room",
    "television": "from a television in the room",
    "speaker": "over a loudspeaker",
    "off_screen": "from off screen",
    "": "from off screen",
}


def heard_marked(item: Item) -> bool:
    """This line is marked as a voice heard, not seen (a call, off screen, narration)."""
    return item.is_line and any(m in f"{item.delivery} {item.speaker}".lower() for m in HEARD_MARKS)


def voice_source(items: Iterable[Item]) -> str:
    """Where the shot's heard voices come from, read from the lines' deliveries first, then the
    action ("Her phone rings."). "" when nothing says."""
    items = list(items)
    for texts in ([f" {i.delivery.lower()} " for i in items if i.is_line],
                  [f" {i.text.lower()} " for i in items if not i.is_line]):
        blob = " ".join(texts)
        for source, words in _SOURCE_WORDS:
            if any(w in blob for w in words):
                return source
    return ""


def source_phrase(source: str, holder: str = "") -> str:
    phrase = SOURCE_PHRASE.get(source, SOURCE_PHRASE[""])
    return phrase.format(holder=f" held by {holder}" if holder else "")


# ── what a shot is for ─────────────────────────────────────────────────────────────────────


def _stamp(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def intent_basis(shot_version: int, script_hash: str) -> str:
    """What an intent was written against: the shot's version and its material as written."""
    return f"v{int(shot_version)}:{script_hash}"


class ShotIntent(BaseModel):
    """What a shot is FOR and what the camera SEES (`shots.intent`). Written by the intent agent
    before the camera design (`by` = model | rules), or by a person (`by` = person); an agent never
    overwrites a person's intent. People are canon entity ids."""

    model_config = ConfigDict(extra="ignore")

    purpose: str = Field(default="", max_length=400)
    what_we_see: str = Field(default="", max_length=700)
    emotional_beat: str = Field(default="", max_length=200)
    on_screen: list[str] = Field(default_factory=list)
    heard_only: list[str] = Field(default_factory=list)
    voice_source: VoiceSource = ""
    # The agent found the shot cannot be played as one take: the last block of the first part, and why.
    # Advice only: a person decides (the director chat's split operation does the cutting).
    split_after: int | None = None
    split_reason: str = Field(default="", max_length=200)
    by: IntentBy = ""
    made_for: str = ""  # `intent_basis` when it was written
    written_at: str | None = None

    @classmethod
    def of(cls, shot: Mapping[str, Any] | None) -> ShotIntent | None:
        """From a stored shot row; none, empty or damaged JSON reads as no intent."""
        raw = (shot or {}).get("intent") or {}
        if not raw:
            return None
        try:
            intent = cls.model_validate(raw)
        except ValueError:
            return None
        return intent if intent.by else None

    def stamp(self) -> str:
        """Changes when what the camera is asked for changes (not when it was written)."""
        return _stamp([self.purpose, self.what_we_see, self.emotional_beat, sorted(self.on_screen),
                       sorted(self.heard_only), self.voice_source])

    def stale(self, basis: str) -> bool:
        return bool(self.made_for) and self.made_for != basis


class ScenePlan(BaseModel):
    """A scene's coverage plan (`scenes.coverage`): what cannot be said shot by shot. Authored
    prose, never a menu: an axis is "stay on the street side of the three-wheeler", not a label."""

    model_config = ConfigDict(extra="ignore")

    axis: str = Field(default="", max_length=300)
    motif: str = Field(default="", max_length=300)
    progression: str = Field(default="", max_length=300)
    by: IntentBy = ""
    made_for: int = 0  # the scene's script_version when it was written
    written_at: str | None = None

    @classmethod
    def of(cls, scene: Mapping[str, Any] | None) -> ScenePlan | None:
        raw = (scene or {}).get("coverage") or {}
        if not raw:
            return None
        try:
            plan = cls.model_validate(raw)
        except ValueError:
            return None
        return plan if plan.by else None

    def text(self) -> str:
        bits = [f"Axis: {self.axis}" if self.axis else "", f"Motif: {self.motif}" if self.motif else "",
                f"Progression: {self.progression}" if self.progression else ""]
        return "\n".join(b for b in bits if b)


class IntentUpdate(BaseModel):
    """A person's change to a shot's intent (PATCH). Only the fields sent change; `reset` hands
    the shot back to the intent agent (its next run writes a new one)."""

    model_config = ConfigDict(extra="forbid")

    purpose: str | None = Field(default=None, max_length=400)
    what_we_see: str | None = Field(default=None, max_length=700)
    emotional_beat: str | None = Field(default=None, max_length=200)
    on_screen: list[str] | None = None
    voice_source: VoiceSource | None = None
    reset: bool = False


class CoverageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: str | None = Field(default=None, max_length=300)
    motif: str | None = Field(default=None, max_length=300)
    progression: str | None = Field(default=None, max_length=300)
    reset: bool = False


# ── who is in the shot, who is seen ────────────────────────────────────────────────────────


def shot_cast(items: Iterable[Item], characters: Sequence[Mapping[str, Any]],
              shot: Mapping[str, Any] | None) -> list[str]:
    """Every character a shot is made against, seen or heard, in canon order: who speaks, who
    the action names, who the intent puts on screen, then a person's own edits. Pins, the voice
    casting and the checks read this list; WHO IS SEEN is `staging()`."""
    edits = PersonEdits.of(shot)
    intent = ShotIntent.of(shot)
    ids = set(cast_in(items, characters, edits))
    known = {str(c["id"]) for c in characters}
    if intent is not None:
        ids |= {c for c in intent.on_screen if c in known}
    ids -= set(edits.cast.remove)
    return [str(c["id"]) for c in characters if str(c["id"]) in ids]


@dataclass
class Staging:
    on_screen: list[str] = field(default_factory=list)  # character ids, canon order
    heard_only: list[str] = field(default_factory=list)  # speakers in the shot who are not seen
    source: str = "rules"  # person | intent | design | rules: what decided it
    voice_source: str = ""

    def visible(self, character_id: str) -> bool:
        return character_id in self.on_screen


def heard_by_rule(items: Iterable[Item], characters: Sequence[Mapping[str, Any]], sound_mode: str) -> list[str]:
    """Speakers heard but not seen, by rule: every line of theirs here is marked as heard, or the
    shot is a voiceover and the action never names them."""
    items = list(items)
    action = name_key(pictured_text(items))
    padded = f" {action} "
    out: list[str] = []
    for c in characters:
        cid = str(c["id"])
        lines = [i for i in items if i.is_line and i.speaker_id == cid]
        if not lines:
            continue
        named = any(k and f" {k} " in padded
                    for k in (name_key(n) for n in [str(c["name"]), *(c.get("aliases") or [])]))
        if all(heard_marked(ln) for ln in lines) or (sound_mode == "voiceover" and not named):
            out.append(cid)
    return out


def staging(items: Iterable[Item], characters: Sequence[Mapping[str, Any]], shot: Mapping[str, Any],
            *, cast_ids: Sequence[str] | None = None) -> Staging:
    """Who the camera sees in this shot, and who is only heard (module docstring for the order)."""
    items = list(items)
    edits = PersonEdits.of(shot)
    intent = ShotIntent.of(shot)
    cast = list(cast_ids) if cast_ids is not None else shot_cast(items, characters, shot)
    sound_mode = str(shot.get("sound_mode") or "ambient")
    forced = set(edits.cast.add)
    marked = {i.speaker_id for i in items if i.speaker_id and heard_marked(i)}
    marked = {s for s in marked if all(heard_marked(i) for i in items if i.is_line and i.speaker_id == s)}
    by_rule = set(heard_by_rule(items, characters, sound_mode))
    raw_design = (shot.get("design") or {}).get("on_screen")
    design_on: set[str] | None = {str(x) for x in raw_design} if isinstance(raw_design, list) else None

    seen: set[str]
    if intent is not None:
        listed = set(intent.on_screen) | set(intent.heard_only)
        seen = {c for c in cast if c in intent.on_screen}
        # A model left someone out: the rules decide for them. Not a person's list, and not Jonathan's: its author
        # lists who the frame shows, and a name in passing ("near Kasun's three-wheeler") must not add a face
        # (PromptMotion's `_prune_subjects`: the list is authoritative, even when it is short).
        if intent.by not in ("person", "jonathan"):
            seen |= {c for c in cast if c not in listed and c not in by_rule}
        source = "person" if intent.by == "person" else "intent"
    elif design_on is not None:
        seen = {c for c in cast if c in design_on}
        source = "design"
    else:
        seen = {c for c in cast if c not in by_rule}
        source = "rules"
    seen -= marked  # a call is never a face …
    seen |= {c for c in cast if c in forced}  # … unless a person put them in the shot
    if forced & set(cast):
        source = "person" if source == "rules" else source
    speakers = list(dict.fromkeys(i.speaker_id for i in items if i.is_line and i.speaker_id))
    on = [c for c in cast if c in seen]
    heard = [s for s in speakers if s in cast and s not in seen]
    vsource = (intent.voice_source if intent is not None and intent.voice_source else "") or (
        voice_source(items) if heard else "")
    return Staging(on_screen=on, heard_only=heard, source=source, voice_source=vsource)


def unseen_sentence(staged: Staging, names: Mapping[str, str]) -> str:
    """For a frame prompt: who is only heard, said so the image model leaves them out."""
    heard = [names[c] for c in staged.heard_only if c in names]
    if not heard:
        return ""
    holder = names.get(staged.on_screen[0], "") if staged.on_screen and staged.voice_source == "phone" else ""
    return (f"{' and '.join(heard)} is not in this place and not in the frame (heard "
            f"{source_phrase(staged.voice_source, holder)}).")


# ── free checks (the camera card) ──────────────────────────────────────────────────────────


def _named(text: str, name: str) -> bool:
    key = name_key(name)
    return bool(key) and f" {key} " in f" {name_key(text)} "


_STOP = frozenset("a an the and or but with in of to for on at by from her his their its she he they it is was "
                  "are were as that this then than into out up down over under again back one more".split())
_BIG = ("two-shot", "two shot", "wide", "walks away", "walk away", "walking away", "crosses", "runs", "drives",
        "all of them", "group")


def _stem(word: str) -> str:
    word = word.lower().strip(".,;:!?\"'()")
    for tail in ("ing", "ed", "es", "s"):
        if len(word) > len(tail) + 3 and word.endswith(tail):
            return word[: -len(tail)]
    return word


def _keys(text: str) -> set[str]:
    return {_stem(w) for w in text.split() if w.lower().strip(".,;:!?\"'()") not in _STOP and len(w) > 2}


def skipped_beats(items: Sequence[Item], intent: ShotIntent | None) -> list[str]:
    """Visible blocks (a picture with seconds on the clock) whose key words are missing from what the
    intent says we see: the agent compressed the shot and dropped a step. → the dropped texts."""
    if intent is None or not intent.what_we_see.strip() or intent.by == "person":
        return []
    seen = _keys(intent.what_we_see)
    out = []
    for i in items:
        if i.kind != "action" or i.picture_s <= 0:
            continue
        words = _keys(i.text)
        # a block counts as shown when most of its key words, or its verb, are in what we see
        if words and len(words & seen) / len(words) < 0.5 and not any(len(w) > 4 and w in seen for w in words):
            out.append(i.text.strip().rstrip("."))
    return out


def staging_checks(*, staged: Staging, names: Mapping[str, str], sound_mode: str, speaker_ids: Sequence[str],
                   ir: Mapping[str, Any] | None = None, design_on_screen: Sequence[str] | None = None,
                   intent: ShotIntent | None = None, items: Sequence[Item] | None = None,
                   framing: str = "") -> list[CameraCheck]:
    """Does the design agree with who is seen? Each advisory names what to look at."""
    checks: list[CameraCheck] = []
    if intent is not None and items is not None:
        for text in skipped_beats(items, intent)[:2]:
            checks.append(CameraCheck(label=f"What we see skips a beat \u00b7 {text}", tone="advisory",
                                      code="staging"))
        said = intent.what_we_see.lower()
        if framing in ("MCU", "CU") and any(w in said for w in _BIG):
            size = FRAMING_LABEL.get(framing, framing).lower()
            checks.append(CameraCheck(label=f"The intent describes more than a {size} can show (two people, a wide, "
                                            f"a move through space)", tone="advisory", code="coverage"))
    name = names.get
    for cid in staged.heard_only:
        where = staged.voice_source.replace("_", " ") or "off screen"
        checks.append(CameraCheck(label=f"Heard only · {name(cid, 'a speaker')} ({where})", tone="pass",
                                  code="staging"))
    if sound_mode in ("dialogue", "sung"):
        for sid in speaker_ids:
            if sid in staged.heard_only:
                checks.append(CameraCheck(label=f"Speaker not on screen · {name(sid, 'a speaker')}",
                                          tone="advisory", code="staging"))
    frame = (ir or {}).get("first_frame") if isinstance((ir or {}).get("first_frame"), Mapping) else {}
    opening = " ".join([str((frame or {}).get("composition") or ""),
                        *[str(s) for s in ((frame or {}).get("subjects") or []) if isinstance(s, str)]])
    for cid in staged.heard_only:
        if opening.strip() and _named(opening, name(cid, "")):
            checks.append(CameraCheck(label=f"First frame shows {name(cid, 'someone')}, who is only heard",
                                      tone="advisory", code="staging"))
    if intent is not None and design_on_screen is not None:
        drift = (set(design_on_screen) ^ set(intent.on_screen)) & set(names)
        if drift:
            who = ", ".join(sorted(name(c, "") for c in drift))
            checks.append(CameraCheck(label=f"The DoP and the intent differ on who is seen · {who}",
                                      tone="advisory", code="staging"))
    return checks


def coverage_checks(framings: Sequence[str], cameras: Sequence[CameraSettings],
                    codes: Sequence[str]) -> list[list[CameraCheck]]:
    """Per shot: a scene that is one size throughout (said once, on its first shot), and a shot
    that repeats the previous shot's setup (size, lens and move)."""
    out: list[list[CameraCheck]] = [[] for _ in framings]
    if len(framings) >= 3 and len(set(framings)) == 1:
        size = FRAMING_LABEL.get(framings[0], framings[0])
        out[0].append(CameraCheck(label=f"Every shot in the scene is a {size.lower()}", tone="advisory",
                                  code="coverage"))
    for i in range(1, len(framings)):
        a, b = cameras[i - 1], cameras[i]
        if framings[i] == framings[i - 1] and a.lens == b.lens and a.movement == b.movement and a.angle == b.angle:
            out[i].append(CameraCheck(label=f"Same setup as {codes[i - 1]}", tone="advisory", code="coverage"))
    return out
