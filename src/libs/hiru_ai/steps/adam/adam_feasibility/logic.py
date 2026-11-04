"""What Veo renders badly, flagged before it is generated (plan/2026-11-04b §5.3, §7 "Veo feasibility notes").

Veo renders faces, slow push-ins, hands on simple props, shallow focus and golden light well. It renders readable text
on a screen, mirrors, fast complicated hand work, crowds and two people touching badly. A flag is a WARNING with the
known fix; it is `addressed` when the card's `veo_notes` already says how it is handled (a reaction instead of the
text, "added in post", a locked-off wide), so a designer can answer a flag and the score can see that it did.

The detectors read the words of the plan (what a card shows), not its pictures, so they are a net for the common
cases and not a promise: a person and the live runs have the last word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from contracts.adam.plan import Moment, SceneScript, ShotCard, norm
from contracts.timing import speech_seconds, words_in
from contracts.veo import VEO_DURATIONS

HIGH, MEDIUM = "high", "medium"
CROWD_PEOPLE = 4  # more faces than this in one frame drift between takes


@dataclass(frozen=True)
class Rule:
    code: str
    risk: str
    pattern: re.Pattern[str]
    why: str
    fix: str
    answers: tuple[str, ...] = ()  # words in `veo_notes` that show the card answers the flag


RULES: tuple[Rule, ...] = (
    Rule("screen_text", HIGH,
         re.compile(r"\b(screen (?:shows|reads|lights|displays)|caller[- ]?id|name on (?:the )?(?:screen|phone)|"
                    r"the (?:message|text|sms|email|letter|sign|note|headline) (?:reads|says)|readable|"
                    r"subtitles?|on the (?:screen|display))\b", re.I),
         "readable text on a screen or page is rendered as gibberish",
         "show the person's reaction instead of the text, or add the text in post",
         ("post", "reaction instead", "no readable", "unreadable", "blurred", "out of focus", "added later")),
    Rule("mirror", HIGH, re.compile(r"\b(mirrors?|reflections?|reflected)\b", re.I),
         "a mirror or reflection is rendered inconsistently",
         "shoot the person, not the reflection; or use a dark window",
         ("no mirror", "not the reflection", "window", "post")),
    Rule("fast_hands", HIGH,
         re.compile(r"\b(typing|knitting|shuffl\w+|counting (?:the )?(?:notes|money|cash)|sewing|playing the "
                    r"(?:guitar|piano|violin|drums|sitar)|chopping (?:quickly|fast)|dealing cards|"
                    r"(?:quick|fast|rapid)(?:ly)? (?:hand|finger)\w*)\b", re.I),
         "fast, complicated hand work drifts and deforms",
         "cut away to the face, or keep the hands slow and simple",
         ("slow", "simple", "cut away", "face", "post")),
    Rule("touching", MEDIUM,
         re.compile(r"\b(hug\w*|embrac\w+|kiss\w*|holds? (?:her|his|their) hand|holding hands|takes? (?:her|his) "
                    r"hand|touches?|grabs?|pushes?|slaps?)\b", re.I),
         "two people touching often merge limbs",
         "frame the contact from behind or in a close-up of one hand; keep it slow",
         ("close-up", "from behind", "one hand", "slow", "post")),
    Rule("crowd", HIGH, re.compile(r"\b(crowds?|everyone|the whole (?:village|town|family|room|hall)|audience|"
                                   r"passers-?by|bystanders)\b", re.I),
         "many faces in one frame drift between takes",
         "keep the crowd soft, behind, or shot from behind; keep two or three faces sharp",
         ("soft", "behind", "out of focus", "blurred", "silhouette", "post")),
)


def _text_of(card: ShotCard, moments: dict[str, Moment]) -> str:
    parts = [card.title, card.blocking_in_shot, card.composition.foreground, card.purpose]
    parts += [f"{b.action} {b.performance}" for b in card.beats]
    for ident in card.moments:
        if m := moments.get(ident):
            parts += [m.seen, m.heard]
    return " ".join(p for p in parts if p)


def flags_for(card: ShotCard, moments: dict[str, Moment]) -> list[dict[str, Any]]:
    text = _text_of(card, moments)
    notes = norm(card.veo_notes)
    out: list[dict[str, Any]] = []

    def add(rule_code: str, risk: str, why: str, fix: str, answers: tuple[str, ...]) -> None:
        out.append({"card": card.number, "code": rule_code, "risk": risk, "why": why, "fix": fix,
                    "addressed": bool(notes) and any(a in notes for a in answers)})

    for rule in RULES:
        if rule.pattern.search(text):
            add(rule.code, rule.risk, rule.why, rule.fix, rule.answers)
    people = {norm(w) for ident in card.moments if (m := moments.get(ident)) for w in m.who}
    if len(people) > CROWD_PEOPLE or (card.arrangement == "group" and len(people) > 3):
        add("many_faces", HIGH, f"{len(people)} people in one frame drift between takes",
            "frame two or three faces sharply and keep the rest soft", ("soft", "behind", "blurred", "silhouette"))
    return out


def long_lines(scene: SceneScript, cards: list[ShotCard]) -> list[dict[str, Any]]:
    """A line that cannot be said inside the longest take, or that is bound to two takes."""
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    facts = {b.line_id: b for b in scene.lines}
    for card in cards:
        for cl in card.lines:
            if cl.line_id in seen:
                out.append({"card": card.number, "code": "line_spans_takes", "risk": HIGH,
                            "why": f"line {cl.line_id} is also in card {seen[cl.line_id]}: "
                                   "a line never spans two takes",
                            "fix": "keep the whole line in one take", "addressed": False})
            seen.setdefault(cl.line_id, card.number)
            b = facts.get(cl.line_id)
            if b and speech_seconds(words_in(b.text), b.delivery) > max(VEO_DURATIONS) - 1.0:
                out.append({"card": card.number, "code": "line_too_long", "risk": HIGH,
                            "why": f"line {cl.line_id} takes {speech_seconds(words_in(b.text), b.delivery):.1f} s "
                                   "to say, "
                                   "more than the longest take holds",
                            "fix": "a person decides: the line is never cut by code", "addressed": False})
    return out


def check(scene: SceneScript, moments: list[Moment], cards: list[ShotCard]) -> dict[str, Any]:
    by_id = {m.id: m for m in moments}
    flags: list[dict[str, Any]] = []
    for card in cards:
        flags += flags_for(card, by_id)
    flags += long_lines(scene, cards)
    open_flags = [f for f in flags if not f["addressed"]]
    by_card: dict[int, int] = {}
    for f in open_flags:
        by_card[int(f["card"])] = by_card.get(int(f["card"]), 0) + 1
    return {"ok": not any(f["risk"] == HIGH for f in open_flags), "flags": flags, "unaddressed": len(open_flags),
            "unaddressed_high": sum(f["risk"] == HIGH for f in open_flags), "by_card": by_card}
