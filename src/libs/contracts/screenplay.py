"""Screenplay text → episodes → scenes → blocks. Pure and deterministic.

Shared by `canon_extract` (cues and headings name the cast and the places), `structure_build`
(the scenes themselves) and the API (a person editing a scene's script). One parser, so a
scene re-parsed after an edit splits exactly as it did in the build.

Accepted shapes, because Hiru's scripts arrive in more than one convention:
* Fountain / screenplay: `INT. HOUSE - NIGHT` headings, an UPPER-CASE cue line above the
  dialogue, `(parentheticals)` for delivery, `CUT TO:` transitions, `@Name` forced cues
  (needed for Sinhala names, which have no upper case);
* `Name: line` dialogue, accepted only for names already known (canon or a cue seen before),
  so a description such as "Note: ..." is never mistaken for speech;
* `SOUND:` / `SFX:` paragraphs as sound blocks.

Text is kept as written: Sinhala is never transliterated or re-normalised here (doc_ingest
already produced NFC with ZWJ kept).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCENE_HEADING = re.compile(
    r"^\s*(?:\d+[.)]?\s+)?(?:INT|EXT|INT\.?/EXT|I/E|EXT\.?/INT)[.\s]"  # INT. HARBOUR - NIGHT
    r"|^\s*SCENE\s+\d+"  # SCENE 12
    r"|^\s*දර්ශනය\s*\d+",  # Sinhala "scene N"
    re.IGNORECASE,
)
_INT_EXT = re.compile(r"^\s*(?:\d+[.)]?\s+)?(INT\.?/EXT|EXT\.?/INT|I/E|INT|EXT)[.\s]+", re.IGNORECASE)
CHARACTER_CUE = re.compile(r"^\s*[A-Z][A-Z0-9 .'\-]{1,28}(?:\s*\((?:V\.O\.|O\.S\.|CONT'D|O\.C\.)\))?\s*$")
_FORCED_CUE = re.compile(r"^\s*@(\S.{0,40}?)\s*$")
_CUE_EXT = re.compile(r"\s*\((V\.O\.|O\.S\.|CONT'D|O\.C\.)\)\s*$", re.IGNORECASE)
_TRANSITION = re.compile(r"^\s*(?:[A-Z ]+ TO:|FADE (?:IN|OUT)[.:]?|CUT TO BLACK\.?|> ?.+)\s*$")
_SOUND = re.compile(r"^\s*(?:SOUND|SFX|ශබ්දය)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_COLON_LINE = re.compile(r"^\s*([^:\n]{1,40}?)\s*[:：]\s*(\S.*)$")
_PAREN_ONLY = re.compile(r"^\s*\(([^)]*)\)\s*$")
_EPISODE_ANY = re.compile(r"(?:episode|\bep\.?|කථාංගය)\s*0*(\d{1,3})", re.IGNORECASE)
_EPISODE_HEAD = re.compile(r"^\s*#*\s*(?:episode|ep\.?|කථාංගය)\s*0*(\d{1,3})\b\s*[—:\-–.]*\s*(.*)$", re.IGNORECASE)
_FILENAME_EP = re.compile(r"(?:ep|episode|e)[\s_\-]*0*(\d{1,3})(?!\d)", re.IGNORECASE)
_TITLE_KEY = re.compile(r"^\s*(title|credit|author|authors|source|draft|draft date|contact|notes?)\s*:", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“]([^\"”]{2,80})[\"”]")

TIMES_OF_DAY = frozenset({
    "DAY", "NIGHT", "MORNING", "EVENING", "DAWN", "DUSK", "AFTERNOON", "NOON", "MIDNIGHT",
    "SUNRISE", "SUNSET", "LATER", "CONTINUOUS", "MOMENTS LATER", "SAME TIME", "LATE NIGHT",
    "EARLY MORNING", "දවල්", "රෑ", "උදේ", "හවස",
})


@dataclass
class Block:
    kind: str  # contracts.production.BlockKind value
    text: str = ""
    speaker: str = ""  # dialogue: the cue as written, extensions removed
    delivery: str = ""  # dialogue: parentheticals and cue extensions ("V.O.", "softly")


@dataclass
class Heading:
    raw: str
    int_ext: str = ""  # "INT" | "EXT" | "INT/EXT" | ""
    location: str = ""  # "KAMALA'S HOUSE"
    sub_location: str = ""  # "KITCHEN"
    time_of_day: str = ""  # "DAWN"


@dataclass
class ParsedScene:
    heading: Heading
    blocks: list[Block] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        return list(dict.fromkeys(b.speaker for b in self.blocks if b.kind == "dialogue"))


@dataclass
class ParsedEpisode:
    number: int | None  # None: the document does not say which episode it is
    title: str = ""
    scenes: list[ParsedScene] = field(default_factory=list)


@dataclass
class ParsedDocument:
    episodes: list[ParsedEpisode]
    title_page: dict[str, str] = field(default_factory=dict)

    @property
    def scenes(self) -> list[ParsedScene]:
        return [s for e in self.episodes for s in e.scenes]


def parse_heading(line: str) -> Heading:
    raw = " ".join(line.split())
    m = _INT_EXT.match(raw)
    int_ext = ""
    rest = raw
    if m:
        int_ext = m.group(1).upper().replace(".", "").replace("I/E", "INT/EXT").replace("EXT/INT", "INT/EXT")
        rest = raw[m.end():]
    else:
        rest = re.sub(r"^\s*(?:SCENE\s+\d+|දර්ශනය\s*\d+)\s*[.:\-–—]*\s*", "", raw, flags=re.IGNORECASE)
    parts = [p.strip(" .") for p in re.split(r"\s+[-–—]\s+|\s*[-–—]{2,}\s*", rest) if p.strip(" .")]
    time = ""
    if parts and parts[-1].upper() in TIMES_OF_DAY:
        time = parts.pop().upper()
    return Heading(raw=raw, int_ext=int_ext, location=parts[0] if parts else "",
                   sub_location=" - ".join(parts[1:]), time_of_day=time)


def _paragraphs(lines: list[str]) -> list[list[str]]:
    paras: list[list[str]] = [[]]
    for line in lines:
        if line.strip():
            paras[-1].append(line.rstrip())
        elif paras[-1]:
            paras.append([])
    return [p for p in paras if p]


def _cue(line: str) -> tuple[str, str] | None:
    """(speaker, extension) when `line` is a character cue."""
    forced = _FORCED_CUE.match(line)
    if forced:
        name = forced.group(1)
    elif CHARACTER_CUE.match(line) and not _TRANSITION.match(line) and not SCENE_HEADING.match(line):
        name = line.strip()
    else:
        return None
    ext = _CUE_EXT.search(name)
    speaker = _CUE_EXT.sub("", name).strip()
    return speaker, (ext.group(1).upper() if ext else "")


def _dialogue(speaker: str, ext: str, body: list[str]) -> Block:
    delivery: list[str] = [ext] if ext else []
    spoken: list[str] = []
    for line in body:
        paren = _PAREN_ONLY.match(line)
        if paren:
            delivery.append(paren.group(1).strip())
        else:
            spoken.append(line.strip())
    return Block("dialogue", " ".join(spoken), speaker, ", ".join(d for d in delivery if d))


def _blocks(lines: list[str], known: set[str]) -> list[Block]:
    out: list[Block] = []
    for para in _paragraphs(lines):
        first = para[0]
        cue = _cue(first)
        if cue and len(para) >= 2:
            out.append(_dialogue(cue[0], cue[1], para[1:]))
            known.add(cue[0].casefold())
            continue
        if _TRANSITION.match(first) and len(para) == 1:
            out.append(Block("cut", first.strip().lstrip("> ").strip()))
            continue
        text = " ".join(ln.strip() for ln in para)
        sound = _SOUND.match(text)
        if sound:
            out.append(Block("sound", sound.group(1).strip()))
            continue
        colon = [_COLON_LINE.match(ln) for ln in para]
        if all(m and m.group(1).strip().casefold() in known for m in colon):
            for m in colon:
                assert m is not None
                name, rest = m.group(1).strip(), m.group(2).strip()
                paren = re.match(r"^\(([^)]*)\)\s*(.*)$", rest)
                delivery, spoken = (paren.group(1).strip(), paren.group(2).strip()) if paren else ("", rest)
                out.append(Block("dialogue", spoken, name, delivery))
            continue
        out.append(Block("action", text))
    return [b for b in out if b.text or b.kind == "cut"]


def _title_page(lines: list[str]) -> tuple[dict[str, str], int]:
    """Fountain title page: `Key: value` lines before the first blank line."""
    meta: dict[str, str] = {}
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    start = i
    while i < len(lines) and lines[i].strip() and _TITLE_KEY.match(lines[i]):
        key, _, value = lines[i].partition(":")
        meta[key.strip().lower()] = value.strip()
        i += 1
    return (meta, i) if meta else ({}, start)


def episode_number_from(text: str, filename: str = "") -> int | None:
    """The episode a document declares near its top, or in its filename."""
    head = "\n".join(text.split("\n")[:15])
    m = _EPISODE_ANY.search(head)
    if m:
        return int(m.group(1))
    m = _FILENAME_EP.search(filename.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else None


def parse_document(text: str, filename: str = "", known_speakers: set[str] | None = None) -> ParsedDocument:
    """A script document. Episode headings inside the text split it into several episodes; a
    document without any is one episode, numbered from its title page or filename if possible."""
    known = {k.casefold() for k in (known_speakers or set())}
    lines = text.replace("\f", "\n").split("\n")
    meta, start = _title_page(lines)
    lines = lines[start:]

    marks = [(i, _EPISODE_HEAD.match(ln)) for i, ln in enumerate(lines)]
    heads = [(i, m) for i, m in marks if m and not SCENE_HEADING.match(lines[i])]
    segments: list[tuple[int | None, str, list[str]]] = []
    if heads:
        pre = lines[: heads[0][0]]
        if any(SCENE_HEADING.match(ln) for ln in pre):  # scenes before the first episode heading
            segments.append((episode_number_from("\n".join(pre), filename), "", pre))
        bounds = [i for i, _ in heads] + [len(lines)]
        for (i, m), end in zip(heads, bounds[1:], strict=True):
            assert m is not None
            segments.append((int(m.group(1)), m.group(2).strip(" \"“”"), lines[i + 1:end]))
    else:
        title = meta.get("title", "")
        number = episode_number_from("\n".join([title, *lines[:15]]), filename)
        quoted = _QUOTED.search(title)
        segments.append((number, quoted.group(1) if quoted else "", lines))

    episodes: list[ParsedEpisode] = []
    for number, title, seg in segments:
        ep = ParsedEpisode(number, title)
        scene: ParsedScene | None = None
        buf: list[str] = []
        for line in seg:
            if SCENE_HEADING.match(line):
                if scene is not None:
                    scene.blocks = _blocks(buf, known)
                    ep.scenes.append(scene)
                scene, buf = ParsedScene(parse_heading(line)), []
            elif scene is not None:
                buf.append(line)
        if scene is not None:
            scene.blocks = _blocks(buf, known)
            ep.scenes.append(scene)
        episodes.append(ep)
    return ParsedDocument(episodes, meta)


@dataclass
class OutlineEpisode:
    number: int
    title: str
    synopsis: str


def parse_outline(text: str) -> list[OutlineEpisode]:
    """`Episode 3 — Storm Season` headings with the paragraph(s) under each as the synopsis."""
    out: list[OutlineEpisode] = []
    current: OutlineEpisode | None = None
    for line in text.replace("\f", "\n").split("\n"):
        m = _EPISODE_HEAD.match(line)
        if m:
            current = OutlineEpisode(int(m.group(1)), m.group(2).strip(" \"“”#"), "")
            out.append(current)
        elif current is not None and line.strip():
            current.synopsis = f"{current.synopsis} {line.strip()}".strip()
    seen: dict[int, OutlineEpisode] = {}
    for ep in out:  # a number repeated (table of contents, then the body): keep the fuller one
        if ep.number not in seen or len(ep.synopsis) > len(seen[ep.number].synopsis):
            seen[ep.number] = ep
    return sorted(seen.values(), key=lambda e: e.number)
