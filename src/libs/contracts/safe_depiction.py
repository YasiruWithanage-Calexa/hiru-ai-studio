"""Safe depiction: death, crime and injury are SHOWN, never graphic, and never named in a prompt (plan/2026-11-10b).

Google's video models (Veo 3.1, Omni Flash) and the image model decline a prompt that names death or violence ("a dead
man", "blood on the floor"), even when the picture asked for is a still figure with nothing graphic in it. A drama still
needs those scenes, so they are written the way television shoots them: what the camera sees ("lies still on the floor,
eyes closed"), reactions, and what is left behind.

Three layers keep a listed word away from the providers:
  * the writers are told: `PROMPT_LINE` is in the system prompt of every agent that writes what a shot shows (a test
    holds each copy to this text), and `knowledge_bases/rules/sources/safe_depiction.md` has the longer guidance;
  * code GATES it: `scan` finds every listed word; one in the description stops the request before anything is spent
    (`contracts.video_gen.validate_render` for video, both frame engines for first frames), with the word and a way to
    say it instead;
  * a SPOKEN line is reported, never stopped and never changed (dialogue is the script's): a word inside quotes is
    advice, because the description can be fixed and the line cannot.

Checks report, they never edit: nothing here rewrites a prompt. A blind swap breaks meaning ("a dead battery", "body
language"), so the person or the writer changes the words. The list is short and precise on purpose, and grows from
real refusals: a word goes in when a provider has declined it and it has no common harmless use in a shot description.

Pure stdlib (the `contracts` rule).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PLAN = "plan/2026-11-10b"


@dataclass(frozen=True)
class Term:
    word: str  # what the person is told the prompt says (the matched text is quoted too)
    pattern: str  # case-insensitive; word boundaries in the pattern
    instead: str  # what to write instead, in a few words


# Precise on purpose: each pattern leaves out the harmless phrases a shot description uses ("dead of night", "wound up",
# "dying light"). "shot" (a camera word), "body" ("body language") and "gun" are not listed.
TERMS: tuple[Term, ...] = (
    Term("dead", r"\bdead\b(?!\s+(?:of\s+(?:night|winter)|end|ends|silence|silent|still|calm|quiet|centre|center|ahead"
                 r"|tired|serious|battery|phone|air|weight|leaves|flowers|grass|bolt|pan|eyed?))",
         "“lies still, eyes closed”"),
    Term("death", r"\bdeaths?\b", "what the camera sees: a still figure, the people who find it"),
    Term("died / dying", r"\b(?:dies|died)\b|\bdying\b(?!\s+(?:light|sun|embers?|fire|flames?|day|evening|breeze))",
         "“has not moved”, “lies still”"),
    Term("corpse", r"\bcorpses?\b|\bcadavers?\b", "“a figure lying still”"),
    Term("body bag", r"\bbody[\s-]*bags?\b", "“a white sheet over a shape”"),
    Term("blood", r"\bblood(?:y|ied|ies|stains?|stained|shed|soaked|spattered|splattered|thirsty)?\b"
                  r"|\bbleed(?:s|ing)?\b|\bbled\b",
         "leave it out (a negative prompt may say it)"),
    Term("gore", r"\bgor(?:e|y)\b|\bgruesome\b|\bgrisly\b", "leave it out"),
    Term("wound", r"\bwounds\b|\bwounded\b|\bwound\b(?!\s+(?:up|tight|tightly|round|around|down|back|through|its|the))",
         "“a hand pressed to his side”, “a bandaged arm”"),
    Term("stab", r"\bstab(?:s|bed|bing)?\b", "the raised hand, then the reaction"),
    Term("kill", r"\bkill(?:s|ed|ing|er|ers)?\b", "what the camera sees before and after"),
    Term("murder", r"\bmurder(?:s|ed|ing|er|ers|ous)?\b|\bhomicides?\b", "what the camera sees before and after"),
    Term("suicide", r"\bsuicid(?:e|es|al)\b", "what the camera sees: an empty room, the people left"),
    Term("slain", r"\bslain\b|\bslay(?:s|ing)?\b", "what the camera sees before and after"),
    Term("strangle", r"\bstrangl(?:e|es|ed|ing)\b|\bnooses?\b|\bhanged\b", "the struggle off frame; the reaction"),
    Term("throat cut", r"\bslit\s+(?:his|her|their|the)\s+throat\b|\bthroats?\s+(?:slit|cut)\b", "leave it out"),
    Term("mutilate", r"\b(?:decapitat|behead|mutilat|dismember)\w*", "leave it out"),
    Term("torture", r"\btortur(?:e|es|ed|ing)\b", "the room after; a face"),
    Term("gunshot", r"\bgunshots?\b|\bbullet[\s-]+(?:wounds?|holes?)\b",
         "the sound off screen; the people who hear it"),
)
_COMPILED = tuple((t, re.compile(t.pattern, re.IGNORECASE)) for t in TERMS)

# A spoken line sits in straight quotes in the video prompt (`says, "{line}"`, clip_schema_veo_3_1.yaml); a writer may
# use curly ones. Whatever is quoted is treated as spoken: reported, never stopped.
_QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")


@dataclass(frozen=True)
class Finding:
    word: str  # the term's name
    said: str  # the text as the prompt has it ("Bloodied")
    instead: str
    spoken: bool  # inside a quoted (spoken) line: advice only


def _find(text: str, *, spoken: bool) -> list[Finding]:
    out: list[Finding] = []
    for term, rx in _COMPILED:
        m = rx.search(text)
        if m:
            out.append(Finding(word=term.word, said=m.group(0), instead=term.instead, spoken=spoken))
    return out


def scan(text: str) -> list[Finding]:
    """Every listed word in `text`, once per term and place: the description's first, then the spoken lines'."""
    text = text or ""
    spoken = " ".join(m.group(0) for m in _QUOTED.finditer(text))
    described = _QUOTED.sub(" ", text)
    return _find(described, spoken=False) + _find(spoken, spoken=True)


def blocking(text: str) -> list[Finding]:
    """The words that stop a request: those in the description (never a spoken line)."""
    return [f for f in scan(text) if not f.spoken]


def video_label(f: Finding) -> str:
    """A blocking check's words for the video panel."""
    return (f"The prompt says “{f.said}”. Google's video models decline words for death and violence, even negated "
            f"(“no blood”). Describe what the camera sees instead: {f.instead}. Change the shot's description, "
            "then render.")


def spoken_label(f: Finding) -> str:
    """An advisory: a spoken line has the word. Lines are never changed."""
    return (f"A spoken line says “{f.said}”. The line stays as written; if the model declines this take, play the "
            "line over a reaction shot or add the voice in the edit.")


def frame_error(found: list[Finding]) -> str:
    """Why a frame was not painted (stored as the frame's error; nothing was spent)."""
    said = ", ".join(f"“{f.said}”" for f in found[:3])
    return (f"Not painted: the shot's description says {said}, and image and video models decline words for death "
            f"and violence. Describe what the camera sees instead ({found[0].instead}), then paint again.")


# Added to a provider's refusal, so a person who meets one knows the likely cause and the way out.
REFUSAL_HINT = ("If the shot shows death, crime or injury, describe only what the camera sees (“lies still, eyes "
                "closed”, “a white sheet over a shape”) and leave out words like dead, blood or kill.")

# The one line every agent that writes what a shot shows has in its system prompt, word for word (whitespace may wrap).
PROMPT_LINE = (
    "- SAFE DEPICTION (plan/2026-11-10b). Death, crime and injury are shown, never graphic, and the video model "
    "refuses the words for them. Write only what the camera sees: \"lies still on the floor, eyes closed\", \"a white "
    "sheet over a shape\", \"a hand pressed to his side\". Never write dead, corpse, death, blood, wound, stab, kill, "
    "murder or suicide in a description, not even negated (\"no blood\"): code stops a prompt that has them. Let "
    "reactions and what is left behind carry the moment. A spoken line is never changed."
)
