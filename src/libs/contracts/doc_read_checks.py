"""The reader's checks (plan/2026-11-06f §4.4). Pure code over the model's answer and the document's text.

A `Problem` is something only the model can fix (a reworded line, a skipped scene, a heading's time left out); the
reader shows it to the same model as a repair, at most twice, then reports what is left. A note is something code mends
itself (a cue that is really a page header is dropped, a new speaker becomes a supporting character) or only reports (a
runtime that does not add up: overruns are reported, never fixed).

Text mode checks every word: a block's `text` must be the words of its `src` lines, and every line inside a scene must
be in one of its blocks. Pages mode cannot check the Sinhala, so it checks what survives the broken font: the Latin
parts of the scene headings (`INT.`, `EXT.`, clock times, scene numbers) must appear in the answer's headings, in order,
and every page must have its transcription.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from contracts.canon import name_key
from contracts.doc_read import (
    TIMES,
    BlockW,
    CanonW,
    CharacterW,
    EpisodeW,
    PatchW,
    PieceRead,
    SceneW,
    normalise,
)
from contracts.doc_read_quality import Layout, Piece
from contracts.screenplay import SCENE_HEADING, parse_heading

_LATIN = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?|[A-Za-z]{2,}|\d+")
_TIMES = {t.casefold() for t in TIMES}
SHOW = 5  # the most lines one problem quotes


@dataclass
class Problem:
    sentence: str  # what is wrong and how to fix it, for the model and for the job's events
    episode: int | None = None
    scene: int | None = None  # 0-based index within the episode's scenes


@dataclass
class Mended:
    answer: PieceRead
    notes: list[str] = field(default_factory=list)


def _where(ep: EpisodeW, i: int, s: SceneW) -> str:
    return f"Episode {ep.number} scene {i} (\"{normalise(s.heading)[:60]}\")"


def _span(doc: Layout, first: int, last: int, furniture: set[str]) -> str:
    """The words of lines first..last, without a page header or footer that falls between them."""
    return normalise(" ".join(ln for ln in doc.lines[first - 1:last] if _edge(ln) not in furniture))


def _quote(doc: Layout, n: int) -> str:
    return f"L{n:04d} \"{normalise(doc.lines[n - 1])[:90]}\""


def _blank(doc: Layout, n: int, furniture: set[str]) -> bool:
    text = doc.lines[n - 1]
    return not text.strip() or _edge(text) in furniture


def _edge(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split())).casefold()


def check_episodes(answer: PieceRead, piece: Piece) -> list[Problem]:
    """The episodes a piece must hold are there, once, in order, each with a scene."""
    out: list[Problem] = []
    numbers = [e.number for e in answer.episodes]
    if piece.expect:
        missing = [n for n in piece.expect if n not in numbers]
        extra = [n for n in numbers if n not in piece.expect]
        if missing:
            out.append(Problem(f"The answer has no episode {', '.join(map(str, missing))}; this part of the document "
                               f"is episode {', '.join(map(str, piece.expect))}. Return it with all its scenes."))
        if extra:
            out.append(Problem(f"The answer has episode {', '.join(map(str, extra))}, which this part of the document "
                               "is not. Put every scene in the episode it belongs to."))
    if len(set(numbers)) != len(numbers):
        out.append(Problem("The answer gives the same episode twice. Give each episode once, with all its scenes."))
    for ep in answer.episodes:
        if not ep.scenes:
            out.append(Problem(f"Episode {ep.number} has no scenes. Return every scene the text has.", ep.number))
    return out


def check_scenes(answer: PieceRead) -> list[Problem]:
    """Every scene has a place, and a time of day from the closed list."""
    out: list[Problem] = []
    for ep in answer.episodes:
        for i, s in enumerate(ep.scenes):
            if not s.location.strip():
                out.append(Problem(f"{_where(ep, i, s)} has no location. Give the place its heading names.",
                                   ep.number, i))
            if s.time_of_day and s.time_of_day.casefold() not in _TIMES:
                out.append(Problem(f"{_where(ep, i, s)} has time_of_day \"{s.time_of_day}\", which is not one of "
                                   f"{', '.join(TIMES)}. Use one of those or \"\".", ep.number, i))
    return out


def check_text(answer: PieceRead, piece: Piece, doc: Layout, furniture: set[str]) -> list[Problem]:
    """Text mode: the words are the source's words, and nothing inside a scene is left out."""
    out: list[Problem] = []
    lo, hi = piece.first_line, piece.last_line
    previous_end = 0
    for ep in answer.episodes:
        for i, s in enumerate(ep.scenes):
            where = _where(ep, i, s)
            if len(s.lines) != 2 or not lo <= s.lines[0] <= s.lines[1] <= hi:
                out.append(Problem(f"{where} has lines {s.lines}; give [first, last], the heading line first, inside "
                                   f"L{lo:04d}-L{hi:04d}.", ep.number, i))
                continue
            first, last = s.lines
            if first <= previous_end:
                out.append(Problem(f"{where} starts at L{first:04d}, inside the scene before it (which ends at "
                                   f"L{previous_end:04d}). Scenes follow each other without overlapping.",
                                   ep.number, i))
            elif previous_end:
                gap = [n for n in range(previous_end + 1, first) if not _blank(doc, n, furniture)]
                if gap:
                    out.append(Problem(f"Lines between two scenes are in no scene: "
                                       f"{'; '.join(_quote(doc, n) for n in gap[:SHOW])}. Put them in the scene they "
                                       "belong to.", ep.number, i))
            previous_end = max(previous_end, last)
            heading = parse_heading(doc.lines[first - 1]) if SCENE_HEADING.match(doc.lines[first - 1]) else None
            if heading and heading.time_of_day and not s.time_of_day:
                out.append(Problem(f"{where}: its heading says {heading.time_of_day}; time_of_day is empty.",
                                   ep.number, i))
            if s.time_of_day and s.time_of_day.isascii() and \
                    s.time_of_day.casefold() not in doc.lines[first - 1].casefold():
                out.append(Problem(f"{where} has time_of_day {s.time_of_day}, which its heading line "
                                   f"{_quote(doc, first)} does not say. Leave it \"\" when the heading gives none.",
                                   ep.number, i))
            covered: set[int] = {first}
            for k, b in enumerate(s.blocks):
                if len(b.src) != 2 or not first <= b.src[0] <= b.src[1] <= last:
                    out.append(Problem(f"{where} block {k} has src {b.src}; give [first, last] inside the scene's "
                                       f"lines L{first:04d}-L{last:04d}.", ep.number, i))
                    continue
                covered.update(range(b.src[0], b.src[1] + 1))
                words = normalise(b.text)
                source = _span(doc, b.src[0], b.src[1], furniture)
                if words and words not in source:
                    out.append(Problem(f"{where} block {k} ({b.kind}) is not the words of L{b.src[0]:04d}-"
                                       f"L{b.src[1]:04d}. Copy them exactly as written, not translated or tidied: "
                                       f"\"{source[:240]}\"", ep.number, i))
            left = [n for n in range(first, last + 1) if n not in covered and not _blank(doc, n, furniture)]
            if left:
                out.append(Problem(f"{where} leaves lines out of its blocks: "
                                   f"{'; '.join(_quote(doc, n) for n in left[:SHOW])}"
                                   f"{f' and {len(left) - SHOW} more' if len(left) > SHOW else ''}. Every line of a "
                                   "scene is in a block (action, dialogue, transition or sound).", ep.number, i))
    return out


def _tokens(text: str) -> list[str]:
    return [t.casefold() for t in _LATIN.findall(text)]


def anchors(piece: Piece, doc: Layout) -> list[tuple[int, str, list[str]]]:
    """The scene headings of the text layer that keep Latin words a broken font cannot spoil: (line, text, tokens)."""
    out = []
    for n in range(piece.first_line, piece.last_line + 1):
        line = doc.lines[n - 1]
        if SCENE_HEADING.match(line):
            tokens = _tokens(line)
            if tokens:
                out.append((n, normalise(line), tokens))
    return out


def _find(tokens: list[str], within: list[str], start: int) -> int | None:
    """The index after `tokens` found in order (not necessarily side by side) in `within` from `start`, or None."""
    i = start
    for t in tokens:
        while i < len(within) and within[i] != t:
            i += 1
        if i == len(within):
            return None
        i += 1
    return i


def check_pages(answer: PieceRead, piece: Piece, doc: Layout) -> list[Problem]:
    """Pages mode: every heading the text layer shows has a scene in the answer, in order; every page is transcribed."""
    out: list[Problem] = []
    headings = [(_tokens(s.heading), ep.number) for ep in answer.episodes for s in ep.scenes]
    at = 0
    missing = []
    for n, text, tokens in anchors(piece, doc):
        hit = next((k for k in range(at, len(headings)) if _find(tokens, headings[k][0], 0) is not None), None)
        if hit is None:
            missing.append(f"page {doc.page_of[n - 1]}: \"{text[:80]}\"")
        else:
            at = hit + 1
    if missing:
        out.append(Problem(f"Scenes the pages hold are missing from the answer (the Latin part of their headings is "
                           f"not in any scene's heading, in order): {'; '.join(missing[:SHOW])}"
                           f"{f' and {len(missing) - SHOW} more' if len(missing) > SHOW else ''}. Return every scene, "
                           "with its heading as written."))
    have = {p.page for p in answer.transcription if p.text.strip()}
    pages = [p for p in range(piece.first_page, piece.last_page + 1) if p not in have]
    if pages:
        out.append(Problem(f"No transcription for page {', '.join(map(str, pages))}. Transcribe every page given, "
                           "word for word, in the language it is written in."))
    return out


def check_piece(answer: PieceRead, piece: Piece, doc: Layout, mode: str, furniture: set[str]) -> list[Problem]:
    out = check_episodes(answer, piece) + check_scenes(answer)
    out += check_text(answer, piece, doc, furniture) if mode == "text" else check_pages(answer, piece, doc)
    return out


def mend(answer: PieceRead, furniture: set[str]) -> Mended:
    """What code fixes itself: a dialogue block with no speaker takes its cue; a cue that is a repeated page header is
    not a speaker (its block is dropped); an empty transition reads "CUT TO:"."""
    notes: list[str] = []
    fixed = answer.model_copy(deep=True)
    for ep in fixed.episodes:
        for s in ep.scenes:
            kept: list[BlockW] = []
            for b in s.blocks:
                if b.kind == "dialogue":
                    cue = b.cue or b.speaker
                    if _edge(cue) in furniture or _edge(b.speaker) in furniture:
                        notes.append(f"\"{cue}\" is the page header, not a speaker; its line was dropped from "
                                     f"episode {ep.number}.")
                        continue
                    if not b.speaker.strip():
                        b.speaker = b.cue
                if b.kind == "transition" and not b.text.strip():
                    b.text = "CUT TO:"
                kept.append(b)
            s.blocks = kept
    return Mended(fixed, notes)


def drop_unquoted(canon: CanonW, text: str) -> tuple[CanonW, list[str]]:
    """Text mode: an entity whose quote is not in the documents keeps its name and loses its description (only what is
    written, decision 7; the rule of `steps/memory_check`)."""
    source = normalise(text)
    notes: list[str] = []
    fixed = canon.model_copy(deep=True)
    for field_name in ("characters", "locations", "props"):
        for e in getattr(fixed, field_name):
            quote = normalise(e.quote)
            if quote and quote in source:
                continue
            described = [k for k, v in e.model_dump().items()
                         if isinstance(v, str) and v and k not in ("name", "code", "quote")]
            if not described and not getattr(e, "per_episode", None):
                continue
            for k in described:
                setattr(e, k, "")
            if isinstance(e, CharacterW):
                e.per_episode = []
            notes.append(f"{e.name}: the reader's description was left out because its quote is not in the text.")
    return fixed, notes


def add_speakers(canon: CanonW, episodes: list[EpisodeW]) -> tuple[CanonW, list[str]]:
    """A speaker the canon does not know becomes a supporting character, and is reported (§4.4)."""
    fixed = canon.model_copy(deep=True)
    known = {k for c in fixed.characters for k in [name_key(c.name), *(name_key(a) for a in c.aliases)]}
    notes: list[str] = []
    for ep in episodes:
        for s in ep.scenes:
            for b in s.blocks:
                if b.kind != "dialogue":
                    continue
                name = (b.speaker or b.cue).strip()
                key = name_key(name)
                if not key or key in known:
                    continue
                aliases = [b.cue] if b.cue and name_key(b.cue) != key else []
                fixed.characters.append(CharacterW(
                    name=name, aliases=aliases, code="", core=False, summary="", age="", gender="", appearance="",
                    wardrobe="", voice="", accent="", per_episode=[], quote=""))
                known.add(key)
                known.update(name_key(a) for a in aliases)
                notes.append(f"{name} speaks in episode {ep.number} but is in no cast list; added as a supporting "
                             "character.")
    return fixed, notes


_RUNTIME = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MIN|MINUTE|MINUTES|MINS)\b", re.IGNORECASE)


def runtime_notes(episodes: list[EpisodeW]) -> list[str]:
    """The scenes' stated lengths against the episode's stated runtime: reported, never fixed."""
    notes = []
    for ep in episodes:
        m = _RUNTIME.search(ep.stated_runtime or "")
        total = sum(max(0, s.stated_seconds) for s in ep.scenes)
        if not m or not total:
            continue
        stated = int(float(m.group(1)) * 60)
        if abs(total - stated) > max(60, stated // 10):
            notes.append(f"Episode {ep.number}: its scenes' stated lengths add up to {total // 60} min {total % 60} s, "
                         f"but it says it runs {ep.stated_runtime.strip()}.")
    return notes


def apply_patch(answer: PieceRead, patch: PatchW) -> PieceRead | None:
    """The answer with the patch's runs of scenes replaced, or None when a replacement points outside the answer."""
    fixed = answer.model_copy(deep=True)
    by_episode: dict[int, list[tuple[int, int, list[SceneW]]]] = {}
    for r in patch.replaces:
        by_episode.setdefault(r.episode, []).append((r.replace_from, r.replace_to, r.scenes))
    for number, runs in by_episode.items():
        ep = next((e for e in fixed.episodes if e.number == number), None)
        if ep is None:
            if all(a == 0 and b == -1 for a, b, _ in runs):  # a missing episode, given whole
                fixed.episodes.append(EpisodeW(number=number, title="", stated_runtime="",
                                               scenes=[s for _, _, scenes in runs for s in scenes]))
                continue
            return None
        for a, b, scenes in sorted(runs, key=lambda r: r[0], reverse=True):
            if not (0 <= a <= len(ep.scenes) and a - 1 <= b < len(ep.scenes)):
                return None
            ep.scenes[a:b + 1] = [s.model_copy(deep=True) for s in scenes]
    fixed.episodes.sort(key=lambda e: e.number)
    return fixed
