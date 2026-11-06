"""A story written as prose becomes screenplay text: find the episodes, cut each into scenes (the model's cut when
it kept
every spoken line word for word, else the rules'), render it as Fountain. The model call is the `prose_writer` agent's;
this is the code half. Ported from `structure_build/engine/prose.py` (plan/2026-11-03 Phase 6)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from contracts.beats import sentences
from contracts.screenplay import parse_document

MIN_SECONDS = 4  # the smallest scene envelope the schema accepts


CANON_NAMES = 80  # the prompt lists this many canon entries at most


_HEAD = re.compile(r"^\s*#*\s*(?:episode|ep\.?|කථාංගය)\s*0*(\d{1,3})\b\s*[—:\-–.]*\s*(.*)$", re.IGNORECASE)


# A speaker line: `Kasun:` alone, or `Kasun: "text"`. Digits first would be a time ("Duration: 1 minute").
_CUE = re.compile(r"^\s*([^\W\d_][^:：\n]{0,30}?)\s*[:：]\s*(.*)$")


_QUOTES = "\"“”‘’"


# `FINAL TEXT ON SCREEN:` and `Note:` look like a speaker line but name no one.
_NOT_A_NAME = re.compile(r"\b(?:screen|text|title|caption|super|notes?|duration)\b", re.IGNORECASE)


_DURATION = re.compile(r"duration\s*:?\s*(\d+(?:\.\d+)?)\s*(minutes?|mins?|seconds?|secs?)\b", re.IGNORECASE)


_END_MARK = re.compile(r"^\s*end\s+(?:of\s+)?(?:episode|ep\.?)\b", re.IGNORECASE)


# Text extraction glues a line to the next one: `…phone!”Anudi turned` and `evening.They talked`.
_GLUED_QUOTE = re.compile(r"([”\"])(?=[A-Z])")


_GLUED_SENTENCE = re.compile(r"(?<=[a-z]{2}[.!?])(?=[A-Z][a-z])")


_NON_WORD = re.compile(r"[\W_]+")


TIMES = ("DAY", "NIGHT", "MORNING", "AFTERNOON", "EVENING", "DAWN", "DUSK", "")


INT_EXT = ("INT", "EXT", "INT/EXT", "")


@dataclass
class Section:
    number: int | None  # None: a lone scene the document does not number
    title: str
    body: str
    duration_s: int | None


@dataclass
class Read(Section):
    """An episode the story reader found (plan/2026-11-05c): the verified spoken lines, and the text between them."""

    spoken: list[dict[str, str]] = field(default_factory=list)  # {speaker, delivery, text}, in order
    gaps: list[str] = field(default_factory=list)  # what is seen: before the first line, between, after the last


def _display(raw: str) -> str:
    raw = " ".join(raw.split())
    return " ".join(w[:1].upper() + w[1:].lower() for w in raw.split()) if raw.isupper() else raw


def _stated_seconds(raw: str) -> int | None:
    duration = _DURATION.search(raw)
    if not duration:
        return None
    value = float(duration.group(1))
    return round(value * (60 if duration.group(2).lower().startswith("m") else 1)) or None


def sections(text: str) -> list[Section]:
    """Every `EPISODE n — Title` section, with the body up to the next one. A number that appears
    twice (a contents list, then the body) keeps the longer section."""
    lines = text.replace("\f", "\n").split("\n")
    heads = [(i, m) for i, ln in enumerate(lines) if not _END_MARK.match(ln) and (m := _HEAD.match(ln))]
    if not heads:  # a plain bible or notes file has no `Episode n` line: no episodes, not an error
        return []
    found: dict[int, Section] = {}
    for (i, m), end in zip(heads, [i for i, _ in heads[1:]] + [len(lines)], strict=True):
        body = [ln for ln in lines[i + 1:end] if not _END_MARK.match(ln)]
        raw = "\n".join(body).strip()
        number = int(m.group(1))
        section = Section(number, _display(m.group(2).strip(" \"“”#")), raw, _stated_seconds(raw))
        if number not in found or len(section.body) > len(found[number].body):
            found[number] = section
    return [found[n] for n in sorted(found)]


def _cue(line: str) -> tuple[str, str] | None:
    """(speaker, text on the same line) when `line` starts a spoken line: `Name:` alone or
    `Name: "text"`."""
    m = _CUE.match(line)
    if not m or _NOT_A_NAME.search(m.group(1)) or len(m.group(1).split()) > 4:
        return None
    spoken = m.group(2).strip()
    return (m.group(1).strip(), spoken) if not spoken or spoken[0] in _QUOTES else None


def _cues(body: str) -> list[str]:
    """Speaker names written as `Name:` above (or before) a quoted line."""
    return [cue[0] for ln in body.split("\n") if (cue := _cue(ln))]


def is_script_like(section: Section) -> bool:
    """Prose with people speaking in it, as opposed to a one-paragraph synopsis."""
    return len(_cues(section.body)) >= 2


def _strip_quotes(text: str) -> str:
    return " ".join(text.strip().strip(_QUOTES).split())


def _fold(text: str) -> str:
    """Letters, marks and digits in lower case (Sinhala vowel signs are marks): what two copies of a line share."""
    return "".join(c for ch in unicodedata.normalize("NFC", text) if unicodedata.category(ch)[0] in "LMN"
                   for c in ch.casefold())


_WRAPPED = re.compile(r"^[(\[*_]+.{0,40}?[)\]*_]+$")


def _is_label(line: str, speaker: str, delivery: str) -> bool:
    """The speaker's name and the direction written above a line: `DASUN`, `(Smiling)`, `FATHER (ON THE PHONE)`."""
    n, name, how = _fold(line), _fold(speaker), _fold(delivery)
    return (not n or n in (name, how, name + how) or bool(_WRAPPED.match(line.strip()))
            or (bool(name) and n == name + "ontheline"))


def _action(blocks: list[dict[str, str]], gap: str, label: tuple[str, str] | None) -> None:
    """The sentences of `gap` as action blocks, without the name and direction of the line that follows it."""
    text = _GLUED_SENTENCE.sub("\n", _GLUED_QUOTE.sub(r"\1\n", gap))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip() and not _DURATION.search(ln)]
    for _ in range(3):
        if label and lines and _is_label(lines[-1], *label):
            lines.pop()
    if lines:  # one visible event per block: a paragraph is split at its sentence ends
        for sentence in sentences(" ".join(lines)):
            blocks.append({"kind": "action", "speaker": "", "delivery": "", "text": sentence})


def by_lines(section: Read) -> list[dict[str, Any]]:
    """One scene for the episode from the reader's lines (checked against the document): each is dialogue, and what lies
    between two of them is action. Nothing here depends on how a line is laid out."""
    blocks: list[dict[str, str]] = []
    for i, gap in enumerate(section.gaps):
        line = section.spoken[i] if i < len(section.spoken) else None
        _action(blocks, gap, (line["speaker"], line["delivery"]) if line else None)
        if line:
            blocks.append({"kind": "dialogue", "speaker": line["speaker"], "delivery": line["delivery"],
                           "text": line["text"]})
    return [{"int_ext": "", "location": "", "sub_location": "", "time_of_day": "",
             "seconds": section.duration_s or 0, "blocks": blocks}]


def by_rules(section: Section) -> list[dict[str, Any]]:
    """One scene for the episode: `Name:` lines become dialogue, the rest action. The place and the
    scene breaks need reading; this fallback does not guess them. An episode the story reader found is cut from its
    lines instead (`by_lines`), whatever its layout."""
    if isinstance(section, Read) and section.spoken and len(section.gaps) == len(section.spoken) + 1:
        return by_lines(section)
    body = _GLUED_SENTENCE.sub("\n", _GLUED_QUOTE.sub(r"\1\n", section.body))
    lines = [ln.strip() for ln in body.split("\n") if ln.strip() and not _DURATION.search(ln)]
    blocks: list[dict[str, str]] = []
    action: list[str] = []

    def flush() -> None:
        if action:  # one visible event per block: a paragraph is split at its sentence ends
            for sentence in sentences(" ".join(action)):
                blocks.append({"kind": "action", "speaker": "", "delivery": "", "text": sentence})
            action.clear()

    i = 0
    while i < len(lines):
        cue = _cue(lines[i])
        if cue:
            speaker, spoken = cue
            flush()
            parts = [spoken] if spoken else []
            if not parts and i + 1 < len(lines):
                i += 1
                parts.append(lines[i])
            while parts and parts[0][0] in "“\"" and not re.search(r"[”\"]\s*$", parts[-1]) and i + 1 < len(lines):
                i += 1  # a long line wrapped before its closing quote
                parts.append(lines[i])
            blocks.append({"kind": "dialogue", "speaker": speaker, "delivery": "",
                           "text": _strip_quotes(" ".join(parts))})
        else:
            action.append(lines[i])
        i += 1
    flush()
    return [{"int_ext": "", "location": "", "sub_location": "", "time_of_day": "",
             "seconds": section.duration_s or 0, "blocks": blocks}]


def _norm(text: str) -> str:
    return _NON_WORD.sub("", text.casefold())


def trusted(section: Section, scenes: list[dict[str, Any]]) -> bool:
    """The model's cut is used only if it kept every spoken line word for word. For an episode the story reader found,
    that is two independent reads agreeing: the cutter's dialogue is the reader's lines, same lines in the same order
    (each of them is in the document: `story_check` found it there)."""
    source = _norm(section.body)
    spoken = [b["text"] for s in scenes for b in s["blocks"] if b["kind"] == "dialogue"]
    if isinstance(section, Read) and section.spoken:
        said = [f for t in spoken if (f := _fold(t))]
        read = [f for ln in section.spoken if (f := _fold(ln["text"]))]
        return bool(scenes) and all(s["blocks"] for s in scenes) and said == read
    return (bool(scenes) and all(s["blocks"] for s in scenes)
            and len(spoken) >= len(_cues(section.body))
            and all(_norm(t) in source for t in spoken if _norm(t)))


def fit_seconds(raw: list[int], target: int | None) -> list[int] | None:
    """Scene lengths that add up to the episode's stated length (None when it states none)."""
    if not target or not raw:
        return None
    weights = [max(int(s), 1) for s in raw]
    scaled = [max(MIN_SECONDS, round(target * w / sum(weights))) for w in weights]
    scaled[scaled.index(max(scaled))] += target - sum(scaled)
    return scaled if min(scaled) >= MIN_SECONDS else None


def _heading(scene: dict[str, Any], number: int) -> str:
    place = " ".join(str(scene.get("location") or "").split())
    if not place:
        return f"SCENE {number}"
    head = f"{scene.get('int_ext') or 'INT'}. {place}"
    sub = " ".join(str(scene.get("sub_location") or "").split())
    return " - ".join(p for p in [head, sub, str(scene.get("time_of_day") or "")] if p)


def render(scenes: list[dict[str, Any]]) -> str:
    """Fountain text: a heading, then action paragraphs and `@Speaker` dialogue."""
    out: list[str] = []
    for n, scene in enumerate(scenes, start=1):
        out.append(_heading(scene, n))
        for b in scene["blocks"]:
            text = " ".join(str(b["text"]).split()).lstrip(">").strip()
            if not text:
                continue
            if b["kind"] == "dialogue" and b["speaker"].strip():
                delivery = " ".join(str(b.get("delivery") or "").split())
                out.append(f"@{' '.join(b['speaker'].split())}" + (f"\n({delivery})" if delivery else "")
                           + f"\n{text}")
            else:
                out.append(text)
        out.append("")
    return "\n\n".join(p for p in out if p is not None)


@dataclass
class Converted:
    text: str
    scene_seconds: dict[str, list[int]]
    episodes: list[int | None]
    by_model: list[int | None]
    fallbacks: list[int | None]  # the model's cut was rejected for these episodes


def from_story(story: dict[str, Any] | None) -> list[Section] | None:
    """The script episodes of a document's reading (`story_check`), whatever their layout; None when it has none."""
    todo: list[Section] = [
        Read(ep["number"], ep["title"], ep["body"], ep.get("duration_s") or _stated_seconds(ep["body"]),
             ep["spoken"], ep["gaps"])
        for ep in (story or {}).get("episodes", []) if ep["kind"] == "script" and ep["body"].strip()]
    return todo or None


def has_scenes(text: str) -> bool:
    """Real scene headings: the screenplay parser owns the document, free and the same every time."""
    return bool(parse_document(text).scenes)


def to_cut(text: str, story: dict[str, Any] | None = None) -> list[Section] | None:
    """The episodes to cut, or None when the document has real scene headings (the parser owns it) or no episode in it
    reads like a script. With the document's reading, its script episodes are the ones to cut, with no `Name:` gate; the
    rules look again only when the reading is missing, or lost episodes whose quotes were not in the text."""
    if has_scenes(text):
        return None
    if read := from_story(story):
        return read
    if story is not None and not story.get("dropped", {}).get("episodes"):
        return None  # the reader looked and found no script in it
    todo = [s for s in sections(text) if is_script_like(s)]
    return todo or None


def cut_input(section: Section, canon: list[dict[str, Any]]) -> dict[str, Any]:
    """The `prose_writer` agent's input for one episode."""
    return {"number": section.number, "title": section.title, "duration_s": section.duration_s, "body": section.body,
            "canon": [{"kind": str(c["kind"]), "name": c["name"]} for c in canon
                      if c["kind"] in ("character", "location")]}


def assemble(todo: list[Section], cuts: list[tuple[list[dict[str, Any]], bool, bool]]) -> Converted:
    """`cuts[i]` = (scenes, from the model, the model was tried and rejected) for `todo[i]` -> the document as text."""
    parts: list[str] = []
    seconds: dict[str, list[int]] = {}
    for section, (scenes, _, _) in zip(todo, cuts, strict=True):
        parts.append(f"EPISODE {section.number}" + (f" \u2014 {section.title}" if section.title else ""))
        parts.append(render(scenes))
        fitted = fit_seconds([int(s.get("seconds") or 0) for s in scenes], section.duration_s)
        if fitted and len(fitted) == len(scenes):
            seconds[str(section.number)] = fitted
    return Converted("\n\n".join(parts), seconds, [s.number for s in todo],
                     [s.number for s, (_, model, _) in zip(todo, cuts, strict=True) if model],
                     [s.number for s, (_, _, rejected) in zip(todo, cuts, strict=True) if rejected])
