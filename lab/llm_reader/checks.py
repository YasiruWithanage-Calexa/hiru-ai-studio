"""Code over the MODEL'S ANSWERS only.

  check()               is the reading sound? Each quote must be on its line (the one thing code compares with the
                        document, and only to accept or reject the model's words); scenes cover every story word once,
                        word by word (a boundary may fall inside a line); numbers whole; seconds sane. A finding goes
                        back to the model as a repair.
  transcription_check() is the page transcription sound? The Latin words of the text layer must all be there, in
                        order (the damaged font only breaks Sinhala); every Sinhala vowel sign must follow a consonant.
  gates()               may the build go on? Stop / Needs input / Warn. Any scene's problem holds the WHOLE build.

Nothing here looks in the document for a heading, a number or a name.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from schema import Answer, Quote, Transcription

WPS = 2.2  # Veo words per second (src/lib/veo/timing.ts)
MIN_S, MAX_S = 4, 1800
LATIN_RATIO = 0.98


@dataclass
class Finding:
    code: str
    message: str


@dataclass
class Gate:
    level: str  # stop | needs_input | warn
    gate: str
    message: str


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        levels = {g.level for g in self.gates}
        if "stop" in levels or self.findings:
            return "stop"
        return "needs_input" if "needs_input" in levels else "go"


def _norm(s: str) -> str:
    return " ".join(s.split())


def tag(s) -> str:  # noqa: ANN001
    return f"E{s.episode:02d} S{s.number:02d}"


def quote_ok(q: Quote, lines: list[str], *, empty_ok: bool = False) -> str | None:
    if q.line == 0:
        return None if empty_ok and not q.quote.strip() else "no line given"
    if not 1 <= q.line <= len(lines):
        return f"line {q.line} does not exist"
    if not q.quote.strip():
        return f"empty quote for line {q.line}"
    if _norm(q.quote) not in _norm(lines[q.line - 1]):
        return f"{q.quote!r} is not on line {q.line} ({lines[q.line - 1][:90]!r})"
    return None


def span(q: Quote, lines: list[str], *, last: bool = False) -> tuple[int, int, int] | None:
    """(line, start, end) of the quote inside its normalised line; `last` takes the last occurrence (an end quote)."""
    if quote_ok(q, lines) is not None:
        return None
    text, needle = _norm(lines[q.line - 1]), _norm(q.quote)
    at = text.rfind(needle) if last else text.find(needle)
    return q.line, at, at + len(needle)


# ── the reading ──────────────────────────────────────────────────────────────────────────────────────────────────


def check(a: Answer, lines: list[str]) -> list[Finding]:
    out: list[Finding] = []

    def q(code: str, label: str, quote: Quote, empty_ok: bool = False) -> None:
        if (why := quote_ok(quote, lines, empty_ok=empty_ok)) is not None:
            out.append(Finding(code, f"{label}: {why}"))

    def length(label: str, ln) -> None:  # noqa: ANN001
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


def coverage(a: Answer, lines: list[str]) -> list[Finding]:
    """Every story word in exactly one scene, word by word. Between two scenes only nothing, or lines the model put in
    `skipped`, or an episode heading line, may lie; a boundary inside a line leaves no word on either side."""
    out: list[Finding] = []
    skipped = {n for k in a.skipped for n in range(k.first, k.last + 1)}
    skipped |= {e.heading.line for e in a.episodes}
    spans = []
    for s in a.scenes:
        st, en = span(s.heading, lines), span(s.end, lines, last=True)
        if st is None or en is None:
            continue  # the quote check already reports it
        if (en[0], en[2]) < (st[0], st[1]):
            out.append(Finding("coverage", f"{tag(s)} ends (line {en[0]}) before it starts (line {st[0]})"))
            continue
        spans.append((s, st, en))

    def loose(first: int, last: int, label: str) -> None:
        stray = [n for n in range(first, last + 1) if _norm(lines[n - 1]) and n not in skipped]
        if stray:
            show = ", ".join(f"{n} ({_norm(lines[n - 1])[:40]!r})" for n in stray[:4])
            out.append(Finding("coverage", f"{label}: line{'s' if len(stray) > 1 else ''} {show} in no scene and not "
                                           f"marked skipped"))

    for (p, _, pe), (s, ns, _) in zip(spans, spans[1:], strict=False):
        label = f"between {tag(p)} and {tag(s)}"
        if (ns[0], ns[1]) < (pe[0], pe[2]):
            out.append(Finding("coverage", f"{tag(s)} starts (line {ns[0]}) inside {tag(p)}, which ends at line {pe[0]}"))
            continue
        if pe[0] == ns[0]:
            gap = _norm(lines[pe[0] - 1])[pe[2]:ns[1]].strip()
            if gap:
                out.append(Finding("coverage", f"{label}: words {gap!r} on line {pe[0]} are in no scene"))
            continue
        after = _norm(lines[pe[0] - 1])[pe[2]:].strip()
        if after:
            out.append(Finding("coverage", f"{label}: words {after!r} after {tag(p)}'s end on line {pe[0]} are in no "
                                           f"scene"))
        before = _norm(lines[ns[0] - 1])[:ns[1]].strip()
        if before and ns[0] not in skipped:
            out.append(Finding("coverage", f"{label}: words {before!r} before {tag(s)}'s heading on line {ns[0]} are "
                                           f"in no scene"))
        loose(pe[0] + 1, ns[0] - 1, label)
    if spans:
        loose(1, spans[0][1][0] - 1, "before the first scene")
        loose(spans[-1][2][0] + 1, len(lines), "after the last scene")
    return out


# ── the transcription ────────────────────────────────────────────────────────────────────────────────────────────

_SIGN = {0x0DCA, *range(0x0DCF, 0x0DE0), 0x0DF2, 0x0DF3}  # Sinhala al-lakuna and vowel signs
_CONSONANT = range(0x0D9A, 0x0DC7)


def misplaced_signs(text: str) -> list[str]:
    """Words in which a Sinhala vowel sign does not follow a consonant (the damaged font's mark)."""
    bad = []
    for word in text.split():
        prev = ""
        for ch in word:
            if ord(ch) in _SIGN and not (prev and ord(prev) in _CONSONANT):
                bad.append(word)
                break
            prev = ch
    return bad


def latin(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)


def transcription_check(t: Transcription, layer_pages: dict[int, list[str]], first_page: int) -> list[Finding]:
    out: list[Finding] = []
    got = {p.page: p.lines for p in t.pages}
    want = sorted(layer_pages)
    if sorted(got) != list(range(first_page, first_page + len(want))) and sorted(got) != want:
        out.append(Finding("pages", f"pages {sorted(got)} transcribed; expected {want}"))
    for n, page in zip(want, sorted(got), strict=False):
        mine, theirs = latin("\n".join(got[page])), latin("\n".join(layer_pages[n]))
        sm = difflib.SequenceMatcher(a=theirs, b=mine, autojunk=False)
        if sm.ratio() < LATIN_RATIO:
            lost = [" ".join(theirs[i1:i2]) for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace")]
            out.append(Finding("latin", f"page {n}: the English words differ from the printed page (ratio "
                                        f"{sm.ratio():.3f}); missing or changed: {lost[:4]}"))
        bad = misplaced_signs("\n".join(got[page]))
        if bad:
            out.append(Finding("sinhala", f"page {n}: {len(bad)} Sinhala words with a vowel sign not after a "
                                          f"consonant, e.g. {bad[:3]}"))
    return out


# ── gates ────────────────────────────────────────────────────────────────────────────────────────────────────────


def gates(a: Answer, lines: list[str]) -> list[Gate]:
    g: list[Gate] = []
    if a.kind not in ("story_script", "story_prose"):
        return [Gate("stop", "1 kind", f"not a story to build from: {a.kind} ({a.kind_why})")]
    # Gate 2: structure
    if not a.scenes:
        return [Gate("stop", "2 structure", "no scenes found")]
    if a.declared.episodes and a.declared.episodes != len(a.episodes):
        g.append(Gate("needs_input", "2 structure",
                      f"the document says {a.declared.episodes} episodes; {len(a.episodes)} found"))
    # Gate 3: people and places
    if not [p for p in a.people if p.role != "group"]:
        g.append(Gate("stop", "3 people", "no people found"))
    elif not any(p.main for p in a.people):
        g.append(Gate("needs_input", "3 people", "no lead character"))
    # Gate 4: every scene; any scene's problem holds the whole build (the person's decision, 2026-11-15)
    for label, bad in (("states no length", [tag(s) for s in a.scenes if not s.length.stated]),
                       ("has no place", [tag(s) for s in a.scenes if not s.place.strip()]),
                       ("has no title", [tag(s) for s in a.scenes if not s.title.strip()])):
        if bad:
            g.append(Gate("needs_input", "4 scene", f"{len(bad)} of {len(a.scenes)} scenes {label}: {', '.join(bad)}"))
    for s in a.scenes:  # overruns are reported, never trimmed (CLAUDE.md)
        if not s.length.stated:
            continue
        words = sum(max(0, len(lines[n - 1].split()) - 1) for n in s.spoken_lines if 1 <= n <= len(lines))
        if words / WPS > s.length.high_seconds:
            g.append(Gate("warn", "4 scene", f"{tag(s)}: ~{words} spoken words need ~{words / WPS:.0f} s; "
                                             f"the script gives {s.length.high_seconds:g} s"))
    return g


def envelope(s) -> float | None:  # noqa: ANN001
    """The person's rule (2026-11-15): a range gives its top."""
    return s.length.high_seconds if s.length.stated else None


# ── against the expected answer ──────────────────────────────────────────────────────────────────────────────────


def score(a: Answer, gold: dict, verdict: str) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    story = a.kind in ("story_script", "story_prose")
    rows.append(("kind", story == gold["story"], a.kind))
    rows.append(("verdict", verdict == gold["verdict"], f"{verdict} (expected {gold['verdict']})"))
    if not gold["story"]:
        return rows
    rows.append(("episodes", len(a.episodes) == gold["episodes"], f"{len(a.episodes)}"))
    rows.append(("scenes", len(a.scenes) == len(gold["scenes"]), f"{len(a.scenes)} of {len(gold['scenes'])}"))
    got = {(s.episode, s.number): s for s in a.scenes}
    bad_title, bad_len, bad_head = [], [], []
    for x in gold["scenes"]:
        s = got.get((x["episode"], x["number"]))
        t = f"E{x['episode']:02d}S{x['number']:02d}"
        if s is None:
            bad_title.append(f"{t} missing")
            continue
        if _norm(s.title).casefold() != _norm(x["title"]).casefold():
            bad_title.append(f"{t} {s.title!r}")
        if len(s.heading.quote) > 90 or s.heading.quote.rstrip().endswith((".", "!")):
            bad_head.append(f"{t} {s.heading.quote!r}")
        if x["high"] is None:
            if s.length.stated:
                bad_len.append(f"{t} invented {s.length.high_seconds:g} s")
        elif not s.length.stated or abs(s.length.high_seconds - x["high"]) > 1 or abs(s.length.low_seconds - x["low"]) > 1:
            bad_len.append(f"{t} {s.length.low_seconds:g}-{s.length.high_seconds:g} s (expected {x['low']:g}-{x['high']:g})")
    rows.append(("titles", not bad_title, "; ".join(bad_title) or "all match"))
    rows.append(("headings clean", not bad_head, "; ".join(bad_head) or "only heading words"))
    rows.append(("lengths", not bad_len, "; ".join(bad_len) or "all match"))
    leads = {p.name.casefold() for p in a.people if p.main}
    rows.append(("leads", all(any(m in n for n in leads) for m in gold["main"]), ", ".join(sorted(leads))))
    crowd = [p.name for p in a.people if p.role != "group"
             and any(w in p.name.casefold() for w in ("customers", "staff", "friends", "workers"))]
    rows.append(("crowds are groups", not crowd, ", ".join(crowd) or "yes"))
    back = got.get((3, 4))
    rows.append(("'Same workspace' resolved", bool(back and back.place_refers_back and "same" not in back.place.casefold()),
                 f"{back.place!r} (refers back: {back.place_refers_back})" if back else "no E03 S04"))
    return rows
