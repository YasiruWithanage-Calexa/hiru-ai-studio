"""The document reader's format: what the model returns about a whole document, and how code maps it into the
system (plan/2026-11-06f §3).

The reader replaces the rules' reading of a script or bible, never what comes after it: `to_parsed` gives the parser's
`ParsedDocument`, so the structure build, its questions and the shot planners do not change; `to_candidates` gives the
canon extractor's candidate dicts, so the canon write and its locking do not change.

The wire shapes have no defaults on purpose: OpenAI's strict JSON schema wants every property required.

Two modes (decision 2):
  text   the model read numbered lines (`L0001 ...`); every block carries `src`, the first and last line it came from,
         so code can check each spoken line word for word (`contracts.doc_read_checks`).
  pages  the text layer was corrupt (a font with a broken ToUnicode map), so the model read the PDF's page images.
         Nothing can be checked word for word: those scenes carry `read_from = "pages"` and a person confirms them.
         The model also returns a clean transcription per page, which replaces the corrupt text for search (decision 8).
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from contracts.canon import CanonKind, name_key
from contracts.screenplay import TIMES_OF_DAY, Block, Heading, ParsedDocument, ParsedEpisode, ParsedScene

FORMAT = 1
Source = Literal["text", "pages"]
BlockKindW = Literal["action", "dialogue", "transition", "sound"]
IntExt = Literal["INT", "EXT", "INT/EXT", ""]
# The closed list for `time_of_day`: the parser's, so a reading and a parsed script agree.
TIMES = tuple(sorted(TIMES_OF_DAY))
READINGS = ("script", "bible", "canon_index", "outline")  # the roles the reader reads (decision 4)


# ── the wire (what the model answers) ────────────────────────────────────────────────────────────────────────────────


class EpisodeNoteW(BaseModel):
    episode: int
    note: str  # what changes for this person in this episode, as written


class CharacterW(BaseModel):
    name: str  # as the documents name them ("Aruni"); a Sinhala spelling goes in aliases
    aliases: list[str]  # every other way the documents and the cues write the name ("ARUNI", "අරුණි")
    code: str  # "C01" when the documents give one, else ""
    core: bool  # a main character (in a cast list, the bible or a canon index)
    summary: str  # who they are, one line, the documents' words
    age: str
    gender: str
    appearance: str
    wardrobe: str
    voice: str
    accent: str
    per_episode: list[EpisodeNoteW]
    quote: str  # a short quote from the document that shows them (text mode: code checks it is there)


class LocationW(BaseModel):
    name: str
    aliases: list[str]
    code: str
    look: str  # materials, light, landmarks: the documents' words
    quote: str


class PropW(BaseModel):
    name: str
    aliases: list[str]
    code: str
    details: str  # colour, size, states
    quote: str


class CanonW(BaseModel):
    characters: list[CharacterW]
    locations: list[LocationW]
    props: list[PropW]


class BlockW(BaseModel):
    kind: BlockKindW
    speaker: str  # dialogue: the canon name the cue refers to ("Aruni"); "" for anything else
    cue: str  # dialogue: the cue as written ("ARUNI", "නිශා")
    delivery: str  # "V.O.", "softly", ""
    text: str  # the words as written: never translated, never tidied
    src: list[int]  # text mode: [first line, last line] the block came from, cue included; pages mode: []


class SceneW(BaseModel):
    number: str  # as written ("01", "1")
    heading: str  # the heading line as written
    int_ext: IntExt
    location: str  # "Mahawewa canal"
    sub_location: str  # "", or the room inside the place
    time_of_day: str  # one of TIMES, or "" when the heading does not say
    clock: str  # "05:08" when the heading gives a time on the clock, else ""
    stated_seconds: int  # "1 MINUTE" -> 60, "1.5 MINUTES" -> 90; 0 when not stated
    flashback: bool
    lines: list[int]  # text mode: [first line, last line] the scene covers, heading included; pages mode: []
    blocks: list[BlockW]


class EpisodeW(BaseModel):
    number: int  # 0 when the document does not say which episode it is
    title: str
    stated_runtime: str  # "45 MIN", "" when not stated
    scenes: list[SceneW]


class PageW(BaseModel):
    page: int  # 1-based, of the whole document
    text: str  # pages mode: a clean transcription of the page; text mode: never asked for


class CanonRead(BaseModel):
    """`reader_canon`'s answer: the people, places and things in the front pages, a bible or a canon index."""
    canon: CanonW
    transcription: list[PageW]


class PieceRead(BaseModel):
    """`reader_episode`'s answer for one piece: one episode, a window of pages, or a whole short document. `canon` holds
    only what is NOT in the list it was given (a new speaker, a place), or the whole canon of a short document."""
    canon: CanonW
    episodes: list[EpisodeW]
    transcription: list[PageW]


class SceneReplaceW(BaseModel):
    """Replace the run of scenes `replace_from`..`replace_to` (0-based, inclusive) of episode `episode` with `scenes`.
    `replace_to = replace_from - 1` inserts before `replace_from`; an empty `scenes` removes the run."""
    episode: int
    replace_from: int
    replace_to: int
    scenes: list[SceneW]


class PatchW(BaseModel):
    """`reader_repair`'s answer: replacements only. It cannot rewrite the reading."""
    replaces: list[SceneReplaceW]


# ── the stored reading (`documents.reading_path`) ────────────────────────────────────────────────────────────────────


class Reading(BaseModel):
    """What is kept beside the text, one per document. A rebuild reads this and makes no model call (decision 4)."""
    format: int = FORMAT
    filename: str = ""
    source: Source = "text"
    canon: CanonW = Field(default_factory=lambda: CanonW(characters=[], locations=[], props=[]))
    episodes: list[EpisodeW] = Field(default_factory=list)
    transcription: list[PageW] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # what code mended or noticed (a new speaker, a runtime that is off)
    unresolved: list[str] = Field(default_factory=list)  # problems left after the repairs: reported, never hidden

    def dumps(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def loads(cls, raw: str | bytes) -> Reading | None:
        """The stored reading, or None when it is not one this code can read (an older format)."""
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return None
        try:
            return cls.model_validate(data)
        except ValueError:
            return None


def reading_path(text_path: str) -> str:
    """Where a document's reading lives: beside its `extracted.txt`."""
    folder = text_path.rsplit("/", 1)[0] if "/" in text_path else ""
    return f"{folder}/reading.json" if folder else "reading.json"


# ── text helpers shared by the checks and the reader ─────────────────────────────────────────────────────────────────

_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """For comparing words: NFC (ZWJ / ZWNJ kept: they build Sinhala conjuncts), whitespace folded."""
    return _SPACE.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def numbered(lines: list[str], first: int = 1) -> str:
    """Lines as the model reads them in text mode: `L0001 text`. Numbers are global to the document."""
    return "\n".join(f"L{first + i:04d} {line}" for i, line in enumerate(lines))


# ── into the system ──────────────────────────────────────────────────────────────────────────────────────────────────

_BLOCK_KIND = {"action": "action", "dialogue": "dialogue", "transition": "cut", "sound": "sound"}


def heading_of(scene: SceneW) -> Heading:
    return Heading(raw=normalise(scene.heading) or _built_heading(scene), int_ext=scene.int_ext,
                   location=scene.location.strip(), sub_location=scene.sub_location.strip(),
                   time_of_day=scene.time_of_day.strip().upper() if scene.time_of_day.isascii()
                   else scene.time_of_day.strip(),
                   flashback=scene.flashback, stated_seconds=max(0, scene.stated_seconds), clock=scene.clock.strip())


def _built_heading(scene: SceneW) -> str:
    place = " - ".join(p for p in (scene.location, scene.sub_location, scene.time_of_day) if p)
    return f"{scene.int_ext}. {place}".strip(". ") if scene.int_ext else place


def to_parsed(reading: Reading) -> ParsedDocument:
    """The reading as the parser's shape. A dialogue block's speaker is the canon name the reader mapped the cue to, so
    `structure_build.analyse.match_speaker` finds the same person for every way the cue is written."""
    episodes = []
    for ep in reading.episodes:
        scenes = []
        for s in ep.scenes:
            blocks = []
            for b in s.blocks:
                kind = _BLOCK_KIND[b.kind]
                text = b.text.strip()
                if kind != "cut" and not text:
                    continue
                speaker = (b.speaker or b.cue).strip() if kind == "dialogue" else ""
                blocks.append(Block(kind, text, speaker, b.delivery.strip() if kind == "dialogue" else ""))
            scenes.append(ParsedScene(heading_of(s), blocks))
        episodes.append(ParsedEpisode(ep.number or None, ep.title.strip(), scenes))  # 0: the text does not say
    return ParsedDocument(episodes)


def scene_seconds(reading: Reading) -> dict[str, list[int]]:
    """{episode number: [stated seconds per scene]}; 0 where the script gives no length (the production's default
    envelope is used there)."""
    return {str(ep.number): [max(0, s.stated_seconds) for s in ep.scenes] for ep in reading.episodes}


def scene_sources(reading: Reading) -> dict[str, list[str]]:
    """{episode number: ["text" | "pages" per scene]}: how each scene was read (decision 6)."""
    return {str(ep.number): [reading.source] * len(ep.scenes) for ep in reading.episodes}


def _card(kind: CanonKind, entity: CharacterW | LocationW | PropW) -> dict[str, str]:
    if isinstance(entity, CharacterW):
        notes = "; ".join(f"Ep {n.episode:02d}: {n.note.strip()}" for n in entity.per_episode if n.note.strip())
        card = {"summary": entity.summary, "age": entity.age, "gender": entity.gender.lower().strip(),
                "appearance": entity.appearance, "wardrobe": entity.wardrobe, "voice": entity.voice,
                "accent": entity.accent, "notes": notes}
    elif isinstance(entity, LocationW):
        card = {"look": entity.look, "summary": _first_sentence(entity.look)}
    else:
        card = {"details": entity.details, "summary": _first_sentence(entity.details)}
    if kind is CanonKind.CHARACTER and card.get("gender") not in ("", "female", "male"):
        card["gender"] = ""  # free words ("woman") are kept in the summary; the card wants the closed value
    return {k: " ".join(v.split()) for k, v in card.items() if v and v.strip()}


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()), maxsplit=1)
    return parts[0] if parts and parts[0] else ""


def to_candidates(reading: Reading) -> list[dict[str, Any]]:
    """The reading's canon as `canon_extract` candidates ({key, kind, code, name, aliases, core, card, sources, lines,
    scenes}), with the lines and scenes each person speaks in counted from the episodes."""
    lines: dict[str, int] = {}
    scenes: dict[str, int] = {}
    places: dict[str, int] = {}
    for ep in reading.episodes:
        for s in ep.scenes:
            spoke: set[str] = set()
            for b in s.blocks:
                if b.kind == "dialogue" and (who := name_key(b.speaker or b.cue)):
                    lines[who] = lines.get(who, 0) + 1
                    spoke.add(who)
            for who in spoke:
                scenes[who] = scenes.get(who, 0) + 1
            if key := name_key(s.location):
                places[key] = places.get(key, 0) + 1

    out: list[dict[str, Any]] = []
    groups: list[tuple[CanonKind, list[Any], dict[str, int], dict[str, int]]] = [
        (CanonKind.CHARACTER, list(reading.canon.characters), lines, scenes),
        (CanonKind.LOCATION, list(reading.canon.locations), {}, places),
        (CanonKind.PROP, list(reading.canon.props), {}, {})]
    for kind, entities, line_count, scene_count in groups:
        for e in entities:
            name = " ".join(e.name.split())
            if not name:
                continue
            keys = {name_key(name), *(name_key(a) for a in e.aliases)} - {""}
            out.append({"key": f"{kind.value}:{name_key(name)}", "kind": kind.value, "code": e.code.strip(),
                        "name": name, "aliases": list(dict.fromkeys(a.strip() for a in e.aliases
                                                                   if a.strip() and name_key(a) != name_key(name))),
                        "core": bool(getattr(e, "core", False)), "card": _card(kind, e),
                        "sources": [reading.filename] if reading.filename else [],
                        "lines": sum(line_count.get(k, 0) for k in keys),
                        "scenes": sum(scene_count.get(k, 0) for k in keys)})
    return out


def merge_canon(base: CanonW, more: CanonW) -> tuple[CanonW, list[str]]:
    """`base` with what `more` adds: a new entity is appended, one already there gains aliases and fills empty fields.
    -> (merged, the names that were new). Earlier answers win, as in `canon_extract.rules.merge`."""
    added: list[str] = []
    merged = base.model_copy(deep=True)
    for field in ("characters", "locations", "props"):
        have: list[Any] = getattr(merged, field)
        for e in getattr(more, field):
            keys = {name_key(e.name), *(name_key(a) for a in e.aliases)} - {""}
            match = next((h for h in have if (e.code and h.code == e.code)
                          or keys & ({name_key(h.name), *(name_key(a) for a in h.aliases)} - {""})), None)
            if match is None:
                have.append(e.model_copy(deep=True))
                added.append(e.name)
                continue
            for alias in [e.name, *e.aliases]:
                if name_key(alias) not in {name_key(match.name), *(name_key(a) for a in match.aliases)}:
                    match.aliases.append(alias)
            for k, v in e.model_dump().items():
                if isinstance(v, str) and v and not getattr(match, k):
                    setattr(match, k, v)
    return merged, added


def roster(canon: CanonW) -> str:
    """The canon list an episode call gets: names, aliases and codes only, so every episode maps a cue to the same
    person without paying for the cards again."""
    rows = []
    for label, entities in (("PERSON", canon.characters), ("PLACE", canon.locations), ("THING", canon.props)):
        for e in entities:
            also = f" (also: {', '.join(e.aliases)})" if e.aliases else ""
            rows.append(f"{label} {e.code + ' ' if e.code else ''}{e.name}{also}")
    return "\n".join(rows) or "(none yet)"


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema as OpenAI's strict structured output wants it: every object closed
    (`additionalProperties: false`) with every property required, and no titles or defaults. For an engine that calls
    the SDK itself (the doc_ingest service); LangChain makes the same from the class."""
    schema = model.model_json_schema()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("title", None)
        node.pop("default", None)
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
            for sub in props.values():  # the property map itself: its keys are field names, never popped
                walk(sub)
        for key, value in node.items():
            if key != "properties":
                walk(value)

    walk(schema)
    return schema


_ROLE_ORDER = {"canon_index": 0, "bible": 1, "outline": 2, "script": 3}


def reading_candidates(documents: list[dict[str, Any]], *, rule_candidates: Any, merge: Any,
                       same: Any) -> list[dict[str, Any]] | None:
    """The canon candidates when documents have readings (plan/2026-11-06f §4.5), or None when none has: the readings'
    canon is the list (a canon index first, then the bible, then the scripts); documents without a reading add their
    rules' canon as before; the rules' canon of the read documents is used only for its codes (C01, L03), which a
    reader can miss. `rule_candidates`, `merge`, `same` are the canon engine's own rules (`canon_extract.rules`)."""
    read = [d for d in documents if d.get("reading")]
    if not read:
        return None
    ordered = sorted(read, key=lambda d: _ROLE_ORDER.get(str(d.get("role")), 9))
    cands: list[dict[str, Any]] = merge(*(to_candidates(Reading.model_validate(d["reading"])) for d in ordered))
    unread = [d for d in documents if not d.get("reading")]
    if unread:
        cands = merge(cands, rule_candidates(unread))
    coded = [c for c in rule_candidates(read) if c.get("code")]
    for c in cands:
        if not c["code"]:
            match = next((r for r in coded if same(r, c)), None)
            if match is not None:
                c["code"] = match["code"]
    return cands
