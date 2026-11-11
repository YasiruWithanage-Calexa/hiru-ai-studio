"""Polishing a prompt's wording without losing a fact (the `prompt_writer` agent's rules, in code).

Code writes every prompt first, from what the shot planner saved: that text is complete and testable. The agent may
then rewrite the DESCRIPTIVE sections as film language for the image or video model. It never sees the parts whose words
are load-bearing (the attached pictures and their numbers, the spoken lines, who is only heard, the fixed rules and the
format), and its answer is checked here, section by section:

  * every ANCHOR of the code text is still in it: the people and places named, numbers with their units (4300K), left
    and right, and the time and weather words;
  * nothing quoted appears that was not quoted (a model must not invent speech or on-screen words);
  * no word the image and video models decline appears that the code text did not have (`contracts.safe_depiction`);
  * it is not empty and not much longer than the code text.

A section that fails keeps the code's words, and the report says why. So the polished prompt is never worse than the
code's on facts: the worst case is the code's prompt.

A first frame's polish is stored on the shot (`shots.design.frame_polish`: section key → {stamp, text}) and used only
while the section's code text is still the one it was written from (`stamp`): change the shot, and the code's words
come back until the writer runs again.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from contracts import safe_depiction

Row = dict[str, Any]
Kind = Literal["first_frame", "video"]

# The sections a model may reword. Everything else is sent to the image or video model exactly as code wrote it.
POLISHABLE: dict[str, tuple[str, ...]] = {
    "first_frame": ("shot", "composition", "people", "place", "light", "colour", "mood"),
    "video": ("setting", "subjects", "story", "camera", "lighting"),
}
# Words whose loss changes the picture: screen side, the time of day, the weather, interior or exterior.
_KEY_WORDS = ("left", "right", "night", "dawn", "dusk", "sunset", "sunrise", "morning", "evening", "afternoon",
              "midday", "noon", "rain", "wet", "mist", "fog", "storm", "wind", "interior", "exterior")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s?(?:K|mm|s|%)?(?![\w/])", re.I)
GROWTH = 1.6  # a polished section may be this many times the code's length (plus `SLACK` characters), no more
SLACK = 200


def stamp(text: str) -> str:
    """Which code text a polish was written from."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:12]


def _word(word: str, text: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", text, re.I) is not None


def anchors(text: str, names: Iterable[str] = ()) -> list[str]:
    """What a rewrite of `text` must still say: the names it uses (of `names`), its numbers, its key words."""
    out: list[str] = [n for n in dict.fromkeys(n.strip() for n in names) if n and _word(n, text)]
    out += [" ".join(m.group(0).split()) for m in _NUMBER.finditer(text)]
    out += [w for w in _KEY_WORDS if _word(w, text)]
    return list(dict.fromkeys(out))


class Section(BaseModel):
    """One section sent to the writer: its words and what it must keep."""

    key: str
    title: str
    text: str
    keep: list[str] = Field(default_factory=list)


class Request(BaseModel):
    kind: Kind
    sections: list[Section]


def request(kind: Kind, sections: Sequence[Mapping[str, Any]], names: Iterable[str] = ()) -> Request:
    """The sections of a prompt the writer may reword (`{key, title, text}` each, in the prompt's order), with their
    anchors. A section not in `POLISHABLE[kind]`, or with no text, is never sent."""
    names = list(names)
    return Request(kind=kind, sections=[
        Section(key=str(s["key"]), title=str(s.get("title") or s["key"]), text=str(s["text"]),
                keep=anchors(str(s["text"]), names))
        for s in sections if str(s.get("key")) in POLISHABLE[kind] and str(s.get("text") or "").strip()])


def problem(code: str, polished: str, keep: Sequence[str]) -> str:
    """Why `polished` may not replace `code` ("" = it may)."""
    text = " ".join(polished.split())
    if not text:
        return "came back empty"
    lost = [k for k in keep if not (_word(k, text) if re.fullmatch(r"[\w' -]+", k) else k.lower() in text.lower())]
    if lost:
        return "dropped " + ", ".join(f"“{k}”" for k in lost[:3])
    if len(text) > len(code) * GROWTH + SLACK:
        return "grew too long"
    if '"' not in code and ('"' in text or "“" in text) and "“" not in code:
        return "added quoted words"
    before = {f.said.lower() for f in safe_depiction.blocking(code)}
    if any(f.said.lower() not in before for f in safe_depiction.blocking(text)):
        return "added words the video models decline"
    return ""


class Merged(BaseModel):
    """The writer's answer applied: section key → the text to use, and what happened to each section sent."""

    texts: dict[str, str] = Field(default_factory=dict)  # only the sections whose polish was kept
    kept_code: dict[str, str] = Field(default_factory=dict)  # key → why the code's words stayed

    @property
    def polished(self) -> list[str]:
        return list(self.texts)


def merge(req: Request, answer: Mapping[str, str]) -> Merged:
    """Each section sent → the writer's text where it passes `problem`, else the code's (with the reason)."""
    out = Merged()
    for s in req.sections:
        said = " ".join(str(answer.get(s.key) or "").split())
        why = problem(s.text, said, s.keep) if s.key in answer else "not answered"
        if why:
            out.kept_code[s.key] = why
        elif said != " ".join(s.text.split()):
            out.texts[s.key] = said
    return out


def frame_record(req: Request, merged: Merged) -> dict[str, Row]:
    """What is stored on the shot (`design.frame_polish`): for each polished section, the stamp of the code text it
    was written from, and its text."""
    by_key = {s.key: s for s in req.sections}
    return {k: {"stamp": stamp(by_key[k].text), "text": t} for k, t in merged.texts.items() if k in by_key}


def usable(record: Mapping[str, Any] | None, key: str, code_text: str) -> str:
    """A stored polish of section `key` while the code text is still the one it was written from; else ""."""
    entry = (record or {}).get(key)
    if not isinstance(entry, Mapping) or entry.get("stamp") != stamp(code_text):
        return ""
    return " ".join(str(entry.get("text") or "").split())


def report(merged: Merged, titles: Mapping[str, str]) -> list[Row]:
    """The checks a person sees for one polish: how many sections were reworded, and each one kept as code wrote it
    because the rewrite lost something (`Check` rows)."""
    out: list[Row] = []
    if merged.texts:
        out.append({"label": f"Wording polished by the prompt writer · {len(merged.texts)} section"
                             + ("s" if len(merged.texts) != 1 else ""), "tone": "pass"})
    for key, why in merged.kept_code.items():
        if why != "not answered":
            out.append({"label": f"{titles.get(key, key)} kept as written: the rewrite {why}", "tone": "advisory"})
    return out
