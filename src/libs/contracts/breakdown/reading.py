"""The reading (plan/2026-11-15 phases 2-3): the model reads every fact of an uploaded document; code only checks its
answer and decides whether the build may go on. Nothing here looks in the document for a heading, a number or a name.

    probe   `breakdown_probe`: what the document is, and whether its letters can be copied as they are   (gates 0, 1)
    read    `breakdown_read`: episodes, scenes (word-level start and end quotes), titles, places, stated lengths,
            people and their roles, the lines that are not story; every fact with the words it came from
    check   code over the answer: each quote is on its line (the one comparison with the document, and it only
            accepts or rejects the model's words), every story word is in exactly one scene, numbers are whole,
            seconds are sane. A finding goes back to the model once.
    gates   stop / needs input / warn (decision D2: any scene's problem holds the whole build)

Proven in lab/llm_reader (seven layouts, run5) and through today's breakdown to Raphael's shots (runs/e2e).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.breakdown.schema import EpisodeCutW, SceneCutW

WPS = 2.2  # Veo words per second (src/lib/veo/timing.ts)
MIN_S, MAX_S = 4, 1800
NL = "\n"
STORY_KINDS = ("story_script", "story_prose")


class _W(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── the wire shapes ──────────────────────────────────────────────────────────────────────────────────────────────


class QuoteW(_W):
    line: int = Field(description="the line number it is on; 0 when there is nothing to quote")
    quote: str = Field(description="the words copied character for character from that line; empty when line is 0")


class LengthW(_W):
    stated: bool = Field(description="true only when the document itself states a length for this scene or episode")
    low_seconds: float = Field(description="the stated length in seconds (the low end of a range); 0 when not stated")
    high_seconds: float = Field(description="the high end of a range in seconds; the same as low for one number; 0 "
                                            "when not stated")
    source: QuoteW = Field(description="the words that state the length, exactly as written")


class ProblemW(_W):
    where: QuoteW
    what: str


class TextQualityW(_W):
    readable: bool = Field(description="false when the letters are damaged so that copying them would copy errors")
    problems: list[ProblemW] = Field(description="up to 5 examples")


class ProbeW(_W):
    """The cheap first look (gates 0 and 1)."""

    kind: Literal["story_script", "story_prose", "synopsis", "series_bible", "cast_or_crew_list", "other_not_story"]
    kind_why: str
    language_of_dialogue: str
    text_quality: TextQualityW


class DeclaredW(_W):
    episodes: int = Field(description="the number of episodes the document SAYS it has; 0 if it says none")
    source: QuoteW


class EpisodeW(_W):
    number: int
    title: str
    heading: QuoteW = Field(description="only the heading's own words")
    length: LengthW


class SceneW(_W):
    episode: int = Field(description="the episode number it belongs to; 0 when the document has no episodes")
    number: int = Field(description="the document's own scene number within its episode")
    heading: QuoteW = Field(description="where the scene STARTS: ONLY the heading's own words, even when the line also "
                                        "holds other text")
    end: QuoteW = Field(description="where the scene ENDS: its last words, copied from the line they are on")
    title: str = Field(description="the scene's title as the document gives it; empty if it gives none")
    place: str = Field(description="the place by its own name; when the document points back ('same workspace'), the "
                                   "place it points to")
    place_refers_back: bool = Field(description="true when the document's words point back to an earlier place")
    place_source: QuoteW
    time_of_day: str = Field(description="as the document states it; empty if not stated")
    length: LengthW
    speakers: list[str] = Field(description="the people who speak in this scene, by the names in `people`")
    spoken_lines: list[int] = Field(description="every line number that holds words someone says aloud in this scene")


class PersonW(_W):
    name: str
    aliases: list[str] = Field(description="other ways the document names this same person")
    role: Literal["lead", "supporting", "minor", "group"] = Field(
        description="lead: the story is about them; group: several unnamed people (customers, staff)")
    why: str = Field(description="one line: why this role")
    first_seen: QuoteW


class SkippedW(_W):
    first: int
    last: int
    kind: Literal["title_page", "page_furniture", "production_notes", "end_marker", "other"]


class ReadingW(_W):
    """The reading of one whole document."""

    kind: Literal["story_script", "story_prose", "synopsis", "series_bible", "cast_or_crew_list", "other_not_story"]
    kind_why: str
    language_of_dialogue: str
    text_quality: TextQualityW
    declared: DeclaredW
    episodes: list[EpisodeW]
    scenes: list[SceneW]
    people: list[PersonW]
    skipped: list[SkippedW] = Field(description="line ranges that are not story")
    doubts: list[str] = Field(description="anything you were unsure of, one line each")


# ── the messages ─────────────────────────────────────────────────────────────────────────────────────────────────


def numbered(filename: str, lines: list[str]) -> str:
    """The document as labelled data, each line with its number (CLAUDE.md, "AI and RAG")."""
    body = NL.join(f"L{i:04d} | {ln}" for i, ln in enumerate(lines, 1))
    return f'<document filename="{filename}" lines="{len(lines)}">{NL}{body}{NL}</document>'


def repair_message(filename: str, lines: list[str], answer: ReadingW, found: list[Finding]) -> str:
    return (f"{numbered(filename, lines)}{NL}{NL}YOUR EARLIER ANSWER{NL}{answer.model_dump_json()}{NL}{NL}"
            f"CODE CHECKED IT AND FOUND{NL}" + NL.join(f"- {f.message}" for f in found)
            + f"{NL}{NL}Answer again, whole. Fix what the checks say if they are right; if a check is wrong about the "
              "document, keep your reading and say why in `doubts`.")


# ── checks over the answer ───────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Finding:
    code: str
    message: str


def _norm(s: str) -> str:
    return " ".join(s.split())


def tag(s: SceneW) -> str:
    return f"E{s.episode:02d}-S{s.number:02d}"


def quote_ok(q: QuoteW, lines: list[str], *, empty_ok: bool = False) -> str | None:
    if q.line == 0:
        return None if empty_ok and not q.quote.strip() else "no line given"
    if not 1 <= q.line <= len(lines):
        return f"line {q.line} does not exist"
    if not q.quote.strip():
        return f"empty quote for line {q.line}"
    if _norm(q.quote) not in _norm(lines[q.line - 1]):
        return f"{q.quote!r} is not on line {q.line} ({lines[q.line - 1][:90]!r})"
    return None


def span(q: QuoteW, lines: list[str], *, last: bool = False) -> tuple[int, int, int] | None:
    """(line, start, end) of the quote in its whitespace-collapsed line; `last` takes the last occurrence."""
    if quote_ok(q, lines) is not None:
        return None
    text, needle = _norm(lines[q.line - 1]), _norm(q.quote)
    at = text.rfind(needle) if last else text.find(needle)
    return q.line, at, at + len(needle)


def check(a: ReadingW, lines: list[str]) -> list[Finding]:
    out: list[Finding] = []

    def q(code: str, label: str, quote: QuoteW, empty_ok: bool = False) -> None:
        if (why := quote_ok(quote, lines, empty_ok=empty_ok)) is not None:
            out.append(Finding(code, f"{label}: {why}"))

    def length(label: str, ln: LengthW) -> None:
        if ln.stated:
            q("length_quote", f"{label} length", ln.source)
            if not (MIN_S <= ln.low_seconds <= ln.high_seconds <= MAX_S):
                out.append(Finding("length_value", f"{label} length {ln.low_seconds}-{ln.high_seconds} s is not sane"))
        elif ln.low_seconds or ln.high_seconds or ln.source.quote.strip():
            out.append(Finding("length_value", f"{label} length is not stated but carries seconds or a quote"))

    if a.declared.episodes:
        q("declared_quote", "declared episode count", a.declared.source)
    for e in a.episodes:
        q("heading_quote", f"episode {e.number} heading", e.heading)
        length(f"episode {e.number}", e.length)
    eps = {e.number for e in a.episodes}
    for s in a.scenes:
        q("heading_quote", f"{tag(s)} heading", s.heading)
        q("end_quote", f"{tag(s)} end", s.end)
        q("place_quote", f"{tag(s)} place", s.place_source, empty_ok=not s.place.strip())
        length(tag(s), s.length)
        if eps and s.episode not in eps:
            out.append(Finding("structure", f"{tag(s)} names episode {s.episode}, which is not in the episodes list"))
        bad = [n for n in s.spoken_lines if not s.heading.line <= n <= s.end.line]
        if bad:
            out.append(Finding("structure", f"{tag(s)} spoken lines {bad} are outside the scene"))
    out += coverage(a, lines)
    names = {n.casefold() for p in a.people for n in [p.name, *p.aliases]}
    for s in a.scenes:
        missing = [n for n in s.speakers if n.casefold() not in names]
        if missing:
            out.append(Finding("people", f"{tag(s)} speakers {missing} are not in people"))
    for p in a.people:
        q("person_quote", f"person {p.name}", p.first_seen)
    for ep in sorted({s.episode for s in a.scenes}):
        nums = [s.number for s in a.scenes if s.episode == ep]
        if sorted(nums) != list(range(1, len(nums) + 1)):
            out.append(Finding("numbering", f"episode {ep} scene numbers are {nums}, not 1..{len(nums)}"))
    return out


def coverage(a: ReadingW, lines: list[str]) -> list[Finding]:
    """Every story word in exactly one scene, word by word. Between two scenes only nothing, lines the model put in
    `skipped`, or an episode heading line may lie; a boundary inside a line leaves no word on either side."""
    out: list[Finding] = []
    skipped = {n for k in a.skipped for n in range(k.first, k.last + 1)} | {e.heading.line for e in a.episodes}
    spans: list[tuple[SceneW, tuple[int, int, int], tuple[int, int, int]]] = []
    for s in a.scenes:
        st, en = span(s.heading, lines), span(s.end, lines, last=True)
        if st is None or en is None:
            continue  # the quote check reports it
        if (en[0], en[2]) < (st[0], st[1]):
            out.append(Finding("coverage", f"{tag(s)} ends (line {en[0]}) before it starts (line {st[0]})"))
            continue
        spans.append((s, st, en))

    def loose(first: int, last: int, label: str) -> None:
        stray = [n for n in range(first, last + 1) if _norm(lines[n - 1]) and n not in skipped]
        if stray:
            show = ", ".join(f"{n} ({_norm(lines[n - 1])[:40]!r})" for n in stray[:4])
            out.append(Finding("coverage", f"{label}: line(s) {show} in no scene and not marked skipped"))

    for (p, _, pe), (s, ns, _) in pairwise(spans):
        label = f"between {tag(p)} and {tag(s)}"
        if (ns[0], ns[1]) < (pe[0], pe[2]):
            out.append(Finding("coverage", f"{tag(s)} starts (line {ns[0]}) inside {tag(p)}, which ends at line "
                                           f"{pe[0]}"))
            continue
        if pe[0] == ns[0]:
            gap = _norm(lines[pe[0] - 1])[pe[2]:ns[1]].strip()
            if gap:
                out.append(Finding("coverage", f"{label}: words {gap!r} on line {pe[0]} are in no scene"))
            continue
        after = _norm(lines[pe[0] - 1])[pe[2]:].strip()
        if after:
            out.append(Finding("coverage", f"{label}: words {after!r} after {tag(p)}'s end on line {pe[0]} are in no "
                                           "scene"))
        before = _norm(lines[ns[0] - 1])[:ns[1]].strip()
        if before and ns[0] not in skipped:
            out.append(Finding("coverage", f"{label}: words {before!r} before {tag(s)}'s heading on line {ns[0]} are "
                                           "in no scene"))
        loose(pe[0] + 1, ns[0] - 1, label)
    if spans:
        loose(1, spans[0][1][0] - 1, "before the first scene")
        loose(spans[-1][2][0] + 1, len(lines), "after the last scene")
    return out


# ── gates ────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Question:
    """A question to the roles that answer them (decision D3), on the build's question channel."""

    key: str
    title: str
    body: str
    options: list[dict[str, str]]
    allow_text: bool = False


@dataclass
class Gate:
    level: Literal["stop", "needs_input", "warn"]
    gate: str
    message: str
    questions: list[Question] = field(default_factory=list)


def verdict(gates: list[Gate]) -> str:
    levels = {g.level for g in gates}
    return "stop" if "stop" in levels else "needs_input" if "needs_input" in levels else "go"


def probe_gates(p: ProbeW) -> list[Gate]:
    """Gates 0 and 1, before the reading is paid for. D6: damaged letters stop the build (no model writes dialogue)."""
    out: list[Gate] = []
    if not p.text_quality.readable:
        ex = "; ".join(f"line {x.where.line}: {x.what}" for x in p.text_quality.problems[:2])
        out.append(Gate("stop", "0 file", "The document's text is damaged (" + (ex or "letters out of order") + "). "
                        "Export it again with a Unicode Sinhala font (for example Noto Sans Sinhala or Iskoola Pota) "
                        "and upload the new file."))
    if p.kind not in STORY_KINDS:
        out.append(Gate("stop", "1 kind", f"This document holds no story to build from ({p.kind}: {p.kind_why})."))
    return out


def _len_question(doc: str, s: SceneW, default_s: int) -> Question:
    return Question(key=f"breakdown:length:{doc}:{tag(s)}", title=f"{tag(s)}: how long is this scene?",
                    body=f"{tag(s)} {s.heading.quote!r} states no length. Type its length in seconds, or use the "
                         f"default of {default_s} s.",
                    options=[{"value": "default", "label": f"Use the default ({default_s} s)"}], allow_text=True)


def gates(a: ReadingW, lines: list[str], *, doc: str, default_s: int, answers: dict[str, dict[str, Any]] | None = None
          ) -> list[Gate]:
    """Gates 2-4 over a checked reading, after the answers already given (a resumed build) are counted."""
    answers = answers or {}
    g: list[Gate] = []
    if a.kind not in STORY_KINDS:
        return [Gate("stop", "1 kind", f"This document holds no story to build from ({a.kind}: {a.kind_why}).")]
    if not a.scenes:
        return [Gate("stop", "2 structure", "No scenes were found in the document.")]
    if a.declared.episodes and a.declared.episodes != len(a.episodes):
        key = f"breakdown:episodes:{doc}"
        got = answers.get(key, {}).get("value")
        if got == "stop":
            g.append(Gate("stop", "2 structure", "A person stopped the build: the document's episodes need fixing."))
        elif got != "continue":
            g.append(Gate("needs_input", "2 structure", f"The document says {a.declared.episodes} episodes; "
                          f"{len(a.episodes)} were found.", [Question(
                              key=key, title="The episodes do not add up",
                              body=f"The document says it has {a.declared.episodes} episodes, but "
                                   f"{len(a.episodes)} were found in it.",
                              options=[{"value": "continue", "label": f"Build the {len(a.episodes)} found"},
                                       {"value": "stop", "label": "Stop; I will fix the document"}])]))
    people = [p for p in a.people if p.role != "group"]
    if not people:
        g.append(Gate("stop", "3 people", "No people were found in the story."))
    elif not any(p.role == "lead" for p in people):
        key = f"breakdown:lead:{doc}"
        if key not in answers:
            g.append(Gate("needs_input", "3 people", "No lead character was found.", [Question(
                key=key, title="Who is the story about?",
                body="No lead character was found. Type the lead's name, or build without one.",
                options=[{"value": "none", "label": "Build without a lead"}], allow_text=True)]))
    asks = [_len_question(doc, s, default_s) for s in a.scenes
            if not s.length.stated and seconds_answer(answers.get(f"breakdown:length:{doc}:{tag(s)}")) is None]
    if asks:
        g.append(Gate("needs_input", "4 scene", f"{len(asks)} of {len(a.scenes)} scenes state no length; the build "
                      "waits for them (any scene holds the whole build).", asks))
    # a place the document does not name is the episode call's to infer from the scene's words: reported, not asked
    unplaced = [tag(s) for s in a.scenes if not s.place.strip()]
    if unplaced:
        g.append(Gate("warn", "4 scene", f"no place named in the document: {', '.join(unplaced)}"))
    for s in a.scenes:  # overruns are reported, never trimmed (CLAUDE.md)
        if not s.length.stated:
            continue
        words = sum(max(0, len(lines[n - 1].split()) - 1) for n in s.spoken_lines if 1 <= n <= len(lines))
        if words / WPS > s.length.high_seconds:
            g.append(Gate("warn", "4 scene", f"{tag(s)}: ~{words} spoken words need ~{words / WPS:.0f} s; the "
                                             f"script gives {s.length.high_seconds:g} s"))
    return g


def seconds_answer(answer: dict[str, Any] | None) -> float | None:
    """A person's answer to a length question: 0 for "use the default", the seconds they typed, None when unanswered
    or not a number of seconds (the question is asked again)."""
    if not answer:
        return None
    if answer.get("value") == "default":
        return 0.0
    words = str(answer.get("text") or "").split()
    try:
        s = float(words[0]) if words else -1.0
    except ValueError:
        return None
    return s if MIN_S <= s <= MAX_S else None


def envelope(s: SceneW) -> float | None:
    """Decision D1: a stated range gives its top."""
    return s.length.high_seconds if s.length.stated else None


# ── handing the reading to the breakdown ─────────────────────────────────────────────────────────────────────────


def unglue(lines: list[str], a: ReadingW) -> tuple[list[str], ReadingW]:
    """A heading the model found INSIDE a line (glued to the sentence before it) becomes its own line, cut at the
    model's word, so the line-based breakdown sees one scene per line range. Every line number in the reading moves
    with it. Mechanical: the model decided where the scene starts."""
    cuts: dict[int, int] = {}  # line -> character where its heading starts (in the collapsed line)
    for s in a.scenes:
        st = span(s.heading, lines)
        if st is not None and st[1] > 0 and _norm(lines[st[0] - 1])[: st[1]].strip():
            cuts[st[0]] = st[1]
    if not cuts:
        return lines, a
    out: list[str] = []
    new_of: dict[int, int] = {}
    for n, ln in enumerate(lines, 1):
        if n in cuts:
            text = _norm(ln)
            out.append(text[: cuts[n]].rstrip())
            new_of[n] = len(out)  # the sentence part keeps this number; the heading goes on the next
            out.append(text[cuts[n]:])
        else:
            out.append(ln)
            new_of[n] = len(out)

    def move(q: QuoteW, heading: bool = False) -> QuoteW:
        """The quote's new line: a quote on a cut line moves to the heading's half when it is the heading, or when
        its words are only in that half (out[n - 1] is the sentence half, out[n] the heading half)."""
        if q.line == 0 or q.line not in new_of:
            return q
        n = new_of[q.line]
        if q.line in cuts:
            words = _norm(q.quote)
            if heading or (words in out[n] and words not in out[n - 1]):
                n += 1
        return q.model_copy(update={"line": n})

    def mv(n: int) -> int:
        return new_of.get(n, n)

    moved = a.model_copy(deep=True)
    for e in moved.episodes:
        e.heading = move(e.heading)
        e.length.source = move(e.length.source)
    for s in moved.scenes:
        s.heading = move(s.heading, heading=True)
        s.end = move(s.end)
        s.place_source = move(s.place_source)
        s.length.source = move(s.length.source)
        s.spoken_lines = [mv(n) for n in s.spoken_lines]  # words on a cut line are the sentence half's
    for p in moved.people:
        p.first_seen = move(p.first_seen)
    moved.declared.source = move(moved.declared.source)
    for k in moved.skipped:
        k.first, k.last = mv(k.first), mv(k.last) + (1 if k.last in cuts else 0)
    for x in moved.text_quality.problems:
        x.where = move(x.where)
    return out, moved


def cuts(a: ReadingW) -> list[EpisodeCutW]:
    """The reading's scenes as the split's cuts (heading line, last line). Run after `unglue`."""
    heads = {e.number: e.heading.line for e in a.episodes}
    eps: dict[int, EpisodeCutW] = {}
    for s in a.scenes:
        ep = eps.setdefault(s.episode, EpisodeCutW(number=s.episode, heading=heads.get(s.episode, s.heading.line),
                                                   scenes=[]))
        ep.scenes.append(SceneCutW(number=s.number, heading=s.heading.line, last=s.end.line))
    return [eps[k] for k in sorted(eps)]


def fact_lines(a: ReadingW, s: SceneW) -> list[int]:
    """The lines inside a scene that hold no story words: where its place and stated length were read from (when nobody
    speaks on them), and the stretches the model marked as not story (page headers and the like)."""
    inside = range(s.heading.line + 1, s.end.line + 1)
    got = {s.place_source.line, s.length.source.line if s.length.stated else 0}
    got = {n for n in got if n in inside and n not in s.spoken_lines}
    got |= {n for k in a.skipped for n in range(k.first, k.last + 1) if n in inside}
    return sorted(got)
