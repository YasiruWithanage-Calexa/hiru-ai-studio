"""What the director chat can do, and what it cannot (plan/2026-11-01c, Phases 1, 3 and 4).

One registry, rendered into the STATIC part of every prompt that has to know: the conductor (what an
operation looks like), the options writer (the same, minus a person's own words) and the reply writer
(what may be offered, and what to say when something is not possible here). Before, three hand-written
lists described the rules and the reply writer was never told what the chat cannot do, so it offered
to do things nothing could do.

Pure data and string building (pydantic + stdlib only, like the rest of `contracts`). The text is
byte-identical from call to call: it sits in a cached system prompt.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Capability(BaseModel):
    """One thing the chat can do. `grammar` is how the conductor writes its operations; `says` is the
    one line the reply writer reads."""

    model_config = ConfigDict(frozen=True)

    id: str
    says: str
    ops: tuple[str, ...] = ()
    grammar: str = ""
    group: Literal["shot", "script", "marks"] = "shot"
    permission: Literal["direct", "edit_script"] = "direct"  # Permission.DIRECT / Permission.EDIT_SCRIPT
    staged: bool = False  # never applied in the turn: shown as a card, applied when the person chooses
    person_only: bool = False  # a person's own operation: never a specialist's, never inside an option
    examples: tuple[str, ...] = ()


class Language(BaseModel):
    """A language the chat can name and CHECK: its script's code points, so a translation is verified in code.
    Latin stands for English only (other Latin-script languages are translated but cannot be checked)."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    aliases: tuple[str, ...]
    lo: int = 0  # first and last code point of the script; 0 = Latin
    hi: int = 0


LANGUAGES: tuple[Language, ...] = (
    Language(code="si", name="Sinhala", aliases=("sinhala", "sinhalese", "සිංහල"), lo=0x0D80, hi=0x0DFF),
    Language(code="ta", name="Tamil", aliases=("tamil", "தமிழ்"), lo=0x0B80, hi=0x0BFF),
    Language(code="hi", name="Hindi", aliases=("hindi", "हिन्दी"), lo=0x0900, hi=0x097F),
    Language(code="en", name="English", aliases=("english",)),
)


def language_by_code(code: str) -> Language | None:
    return next((lang for lang in LANGUAGES if lang.code == (code or "").strip().lower()), None)


def language_named(text: str) -> Language | None:
    """The language a word or phrase names ("Sinhala", "tamil please"), None when it names none of the known ones."""
    low = unicodedata.normalize("NFC", str(text)).casefold()
    return next((lang for lang in LANGUAGES if any(re.search(rf"(?<!\w){re.escape(a.casefold())}(?!\w)", low)
                                                    for a in lang.aliases)), None)


class NotHere(BaseModel):
    """A request the chat cannot meet, with the honest reason and the way the person CAN get it done."""

    model_config = ConfigDict(frozen=True)

    id: str
    request: str
    reason: str
    route: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability(id="shot.set", ops=("set",), says="Set a shot's framing, sound mode or title.",
               grammar="set {shot, field: framing|sound_mode|title, value}", examples=("shot 1 wide",)),
    Capability(id="shot.length", ops=("retime", "unlock_length"), says="Change a shot's length (4, 6 or 8 s).",
               grammar="retime {shot, seconds: 4|6|8}; unlock_length {shot}",
               examples=("make shot 3 six seconds",)),
    Capability(id="shot.cuts", ops=("split", "merge", "regroup"), says="Split, merge or move the cuts between shots.",
               grammar="split {shot, at_block, framing?, title?}; merge {shot} (with the next); "
                       "regroup {shot, end_block} (move the cut after it)",
               examples=("split shot 2", "merge shots 4 and 5")),
    Capability(id="shot.join", ops=("set_join",), says="Change how a shot joins the one before it.",
               grammar="set_join {shot, link: cut|continuous|match} (how THIS shot joins the one before it)"),
    Capability(id="shot.beat", ops=("beat.set",), says="Write a shot's camera, director's line or action for a beat.",
               grammar="beat.set {shot, beat: 0-2, field: camera|director_line|action, value}"),
    Capability(id="shot.insert", ops=("insert", "remove"), says="Add a reaction or insert shot, or remove a shot.",
               grammar="insert {after_shot (0 = first), description, framing?, title?} for a reaction or insert shot; "
                       "remove {shot}", examples=("add a reaction of Kamala after shot 2",)),
    Capability(id="scene.envelope", ops=("set_envelope",), says="Change the scene's time envelope.",
               grammar="set_envelope {seconds}"),
    Capability(id="script.line", ops=("block.set", "block.insert", "block.remove"), group="script",
               permission="edit_script", staged=True, person_only=True,
               says="Change a script block's words, only in words the person typed, and only as a card they accept.",
               grammar="block.set {block, field: text|speaker|delivery, value}; block.insert {block: where it goes, "
                       "kind: action|dialogue|sound|beat|cut, value: its text, speaker, delivery}; "
                       "block.remove {block}",
               examples=('change S02\'s line to "sit down and eat"',)),
    Capability(id="dialogue.translate", ops=("block.set",), group="script", permission="edit_script", staged=True,
               person_only=True,
               says="Translate spoken lines into another language ONLY when the person asks (the script otherwise "
                    "stays in its own language): the translator writes them, the person accepts a card showing "
                    "every line before and after, and the original is kept as the source.",
               grammar="Translation is never written by you: answer lane translate with translate {language, code, "
                       "style, shots}",
               examples=("put all the dialogue in Sinhala", "translate S02 to Tamil, formal")),
    Capability(id="shot.marks", ops=("canon.add", "canon.remove", "check.waive", "check.restore", "dop_note.set"),
               group="marks", person_only=True,
               says="Mark who is in a shot, ignore or show a check, set the DoP's note.",
               grammar="canon.add|canon.remove {shot, value: a canon name or code}; check.waive|check.restore "
                       "{shot, value: axis|speaker size|wardrobe|voice pin|all} (ignore or show an advisory); "
                       "dop_note.set {shot, value: the DoP's note, empty clears it}"),
)

NOT_HERE: tuple[NotHere, ...] = (
    NotHere(id="dialogue.write", request="Write, improve or rephrase dialogue",
            reason="I can't write or reword dialogue: a line only ever uses words you typed. I can translate it when "
                   "you ask.",
            route="Send me the exact new line, or open Script → Edit and change it there."),
    NotHere(id="canon.change", request="Change a character's look, voice or age",
            reason="Characters are kept in the Canon, not in this scene's shot list.",
            route="Open Canon, change the character there, then ask me to look at the shots again."),
    NotHere(id="render", request="Make frames, prompts or video",
            reason="I plan the shot list; I don't render anything.",
            route="Use the Production panel for frames, prompts and video."),
    NotHere(id="other_scene", request="Change another scene or episode",
            reason="Each chat works on one scene.", route="Open that scene and ask there."),
)

# Not listed in the prompts: translation is a capability. This is what is said when the translator cannot run.
TRANSLATOR_DOWN = NotHere(id="dialogue.translate", request="Translate dialogue, or put it in another language",
                          reason="I can't translate dialogue right now: the translator is not available.",
                          route="Open Script → Edit and change the lines there.")

GENERIC = NotHere(id="other", request="", reason="That isn't something I can do here.",
                  route='Name a change to the shot list, for example "make shot 3 six seconds".')


def by_id(not_here_id: str) -> NotHere:
    if not_here_id == TRANSLATOR_DOWN.id:
        return TRANSLATOR_DOWN
    return next((n for n in NOT_HERE if n.id == not_here_id), GENERIC)


def render_for_prompt(scope: Literal["conductor", "options", "reply"]) -> str:
    """The registry as prompt text. `conductor`: every operation's shape and who may write it.
    `options`: only the operations an option may carry. `reply`: what may be offered, and what is not
    possible here."""
    if scope == "options":
        shots = "; ".join(c.grammar for c in CAPABILITIES if not c.person_only)
        return f"Operations (unused fields null): {shots}."
    if scope == "reply":
        can = " ".join(c.says for c in CAPABILITIES)
        cannot = " ".join(f"{n.request}: no. {n.route}" for n in NOT_HERE)
        return (f"What this chat can do: {can} A change to a script block's words is only ever shown as a card "
                f"the person accepts; nothing else waits on a confirmation.\n"
                f"What it cannot do: {cannot}")
    shots = "; ".join(c.grammar for c in CAPABILITIES if c.group == "shot")
    script = " ".join(f"{c.grammar}." for c in CAPABILITIES if c.group == "script")
    marks = " ".join(f"{c.grammar}." for c in CAPABILITIES if c.group == "marks")
    cannot = "; ".join(f"{n.request} [{n.id}]" for n in NOT_HERE)
    return (f"Operations (unused fields null): {shots}.\nScript: {script}\nMarks on a shot: {marks}\n"
            f"Not possible in this chat: {cannot}.")


# ── intents: what a card's label promises, checked against the scene (Phase 3) ───────────────

SCRIPT_SHARE = 0.8  # of a line's letters, in the language's script, for the line to count as that language
SINHALA_SHARE = SCRIPT_SHARE  # the original name, kept for what imports it


def _share(letters: list[str], lang: Language) -> float:
    inside = sum(c.isascii() for c in letters) if not lang.lo else sum(lang.lo <= ord(c) <= lang.hi for c in letters)
    return inside / len(letters)


def script_of(text: str) -> str:
    """The code of the language whose script holds at least 80% of a line's letters ("si", "ta", "hi", "en"),
    "mixed" when none does, or "none" when it has no letters."""
    letters = [c for c in unicodedata.normalize("NFC", str(text)) if c.isalpha()]
    if not letters:
        return "none"
    return next((lang.code for lang in LANGUAGES if _share(letters, lang) >= SCRIPT_SHARE), "mixed")


def dialogue_counts(items: Sequence[dict[str, object]]) -> dict[str, int]:
    """Spoken lines by script: {"si": n, "ta": n, "hi": n, "en": n, "mixed": n, "none": n}."""
    out = {**{lang.code: 0 for lang in LANGUAGES}, "mixed": 0, "none": 0}
    for item in items:
        if item.get("kind") == "dialogue":
            out[script_of(str(item.get("text") or ""))] += 1
    return out


def dialogue_script(items: Sequence[dict[str, object]]) -> str:
    """The script every spoken line is in ("si", "en", ...), "mixed" when they differ, "none" without lines."""
    counts = dialogue_counts(items)
    present = [k for k, n in counts.items() if n]
    return present[0] if len(present) == 1 else ("none" if not present else "mixed")


class Intent(BaseModel):
    """A goal a card can claim. `claim` finds it in an option's LABEL (empty: only a model can name it);
    `met` is the post-condition over the scene once the card's operations are applied."""

    model_config = ConfigDict(frozen=True)

    id: str
    says: str
    claim: str = ""  # regex over the label


def _dialogue_claim(lang: Language) -> str:
    name = "|".join(re.escape(a) for a in lang.aliases if a.isascii())
    return (rf"\b(?:switch|translate|convert|change|make|put|turn|render|set)\b[^.]{{0,40}}"
            rf"\b(?:dialogues?|lines?|everything)\b[^.]{{0,40}}\b(?:{name})\b"
            rf"|\b(?:dialogues?|lines?)\b[^.]{{0,30}}\b(?:to|into)\s+(?:{name})\b"
            + (r"|\btranslat\w*\b[^.]{0,40}\b(?:dialogues?|lines?)\b" if lang.code == "si" else ""))


INTENTS: tuple[Intent, ...] = (
    *(Intent(id=f"dialogue.{lang.code}", says=f"every spoken line is in {lang.name}", claim=_dialogue_claim(lang))
      for lang in LANGUAGES),
    Intent(id="shot.framing", says="the option sets a shot's framing"),
)


def intent_by_id(intent_id: str) -> Intent | None:
    return next((i for i in INTENTS if i.id == intent_id), None)


def claimed_intent(label: str) -> str:
    """The intent an option's LABEL claims ("Switch all dialogue to Sinhala"), "" when it claims none."""
    for intent in INTENTS:
        if intent.claim and re.search(intent.claim, label, re.I):
            return intent.id
    return ""


def met(intent_id: str, *, items: Sequence[dict[str, object]],
        ops: Sequence[dict[str, object]] = ()) -> tuple[bool, str]:
    """Does the scene (its items after the operations) satisfy the intent? → (yes/no, a sentence about
    the scene). An unknown intent claims nothing and holds."""
    if intent_id.startswith("dialogue.") and (lang := language_by_code(intent_id.split(".", 1)[1])) is not None:
        counts = dialogue_counts(items)
        total = sum(counts.values())
        state = f"{counts[lang.code]} of {total} spoken lines are in {lang.name}"
        return counts[lang.code] == total and total > 0, state + "."
    if intent_id == "shot.framing":
        sets = [o for o in ops if o.get("op") == "set" and o.get("field") == "framing"]
        return bool(sets), ("The edit sets a framing." if sets else "The edit sets no framing.")
    return True, ""
