"""Step 5, the checks (plan/2026-11-11 §8): code, free. Each returns Findings; `blocking` ones stop packet assembly."""

from __future__ import annotations

import itertools
import re

from contracts.breakdown import ids
from contracts.breakdown.lines import Doc
from contracts.breakdown.schema import Breakdown, Finding, Scene

WPS = 2.2  # Veo words per second (src/lib/veo/timing.ts)
_MINUTES = re.compile(r"(\d+(?:\.\d+)?)\s*MINUTES?\s*$")


def _speaks_a_name(bd: Breakdown, sc: Scene) -> list[Finding]:
    """A dialogue block holds words someone says, never a speaker's own name pointed at in narration."""
    names = {e.id: e.name.lower() for e in bd.entities}
    return [
        Finding(
            code="words",
            scene=sc.id,
            blocking=True,
            message=f"{b['id']} is a dialogue block of the single word {b['text']!r}: that is narration, not speech",
        )
        for b in sc.blocks
        if b["kind"] == "dialogue" and b["text"].strip(" .,:;").lower() == names.get(b["speaker"], "<no name>")
    ]


def _where(doc: Doc, at: list[tuple[int, int]], what: str) -> str:
    """Runs of word positions as a repair can act on them: `line 60 words 11-12 ("gaththa salli.") in no block`."""
    runs: list[tuple[int, int, int]] = []
    for line, w in at:
        if runs and runs[-1][0] == line and runs[-1][2] == w - 1:
            runs[-1] = (line, runs[-1][1], w)
        else:
            runs.append((line, w, w))
    parts = [f"line {ln} word{'s' if a != z else ''} {a}{'-' + str(z) if a != z else ''} "
             f"({' '.join(doc.words(ln)[a:z + 1])!r}) {what}" for ln, a, z in runs[:8]]
    return "; ".join(parts) + ("; ..." if len(runs) > 8 else "")


def _cue_inside(sc: Scene) -> list[Finding]:
    """A dialogue block that starts with its own cue ("NIMAL - ...") pointed from word 0: its span must start at word 2,
    after the cue, or the line's last words fall out of it."""
    return [Finding(code="words", scene=sc.id, blocking=True, message=(
                f"{b['id']} starts with the speaker cue: on a cue line (NAME - ...) the dialogue span starts at word 2 "
                f"(line {b['spans'][0][0]})"))
            for b in sc.blocks if b["kind"] == "dialogue" and b["spans"] and b["spans"][0][1] == 0
            and len(b["text"].split()) > 1 and b["text"].split()[1] == "-"]


def words(bd: Breakdown, doc: Doc) -> list[Finding]:
    """Every body word of a scene is in exactly one block; every speech event sits in a dialogue block."""
    out: list[Finding] = []
    for sc in bd.scenes:
        if not sc.blocks:
            continue
        out += _speaks_a_name(bd, sc)
        seen: dict[tuple[int, int], int] = {}
        for b in sc.blocks:
            for line, a, z in b["spans"]:
                if not (sc.first <= line <= sc.last):
                    out.append(
                        Finding(
                            code="words",
                            scene=sc.id,
                            blocking=True,
                            message=f"{b['id']} points at line {line}, outside the scene",
                        )
                    )
                    continue
                for w in range(a, z):
                    seen[(line, w)] = seen.get((line, w), 0) + 1
            for e in b["events"]:
                if e["speech"] and b["kind"] != "dialogue":
                    out.append(
                        Finding(
                            code="words",
                            scene=sc.id,
                            blocking=True,
                            message=(
                                f"{e['id']} is speech but {b['id']} is a {b['kind']} block: cut it into its own "
                                "dialogue block"
                            ),
                        )
                    )
        missing: list[tuple[int, int]] = []
        overlap: list[tuple[int, int]] = []
        cues = {b["spans"][0][0] for b in sc.blocks if b["kind"] == "dialogue" and b["spans"]}
        for line in range(sc.first, sc.last + 1):
            ws = doc.words(line)
            # "ARUNI -": the speaker's cue is the speaker field
            skip = 2 if line in cues and len(ws) > 1 and ws[1] == "-" else 0
            for w in range(skip, len(ws)):
                n = seen.get((line, w), 0)
                if n == 0:
                    missing.append((line, w))
                elif n > 1:
                    overlap.append((line, w))
        if missing or overlap:
            detail = "; ".join(x for x in (_where(doc, missing, "in no block"), _where(doc, overlap, "in two blocks")) if x)
            out.append(
                Finding(
                    code="words",
                    scene=sc.id,
                    blocking=True,
                    message=f"{len(missing)} word(s) in no block, {len(overlap)} word(s) in more than one: {detail}",
                )
            )
        out += _cue_inside(sc)
    return out


def id_check(bd: Breakdown) -> list[Finding]:
    out: list[Finding] = []
    known = {e.id for e in bd.entities}
    for sc in bd.scenes:
        if not sc.brief:
            continue

        def need(x: str, what: str, sc: Scene = sc) -> None:
            if x and (not ids.valid(x) or x not in known):
                out.append(Finding(code="ids", scene=sc.id, blocking=True, message=f"{what} {x!r} does not resolve"))

        need(sc.brief.get("place", ""), "place")
        for p in sc.brief["people"]:
            need(p["person"], "person")
        for t in sc.brief["things"]:
            need(t["thing"], "thing")
        for b in sc.blocks:
            need(b["speaker"], "speaker")
            need(b["addressee"], "addressee")
            for h in b["heard_by"]:
                need(h, "heard_by")
            for e in b["events"]:
                for x in (*e["actors"], *e["things"], e["spot"]):
                    need(x, "event reference")
    return out


def sources(bd: Breakdown, doc: Doc) -> list[Finding]:
    out: list[Finding] = []
    for e in bd.entities:
        for k, v in e.card.items():
            if v.source == "script" and (
                v.lines is None or not (doc.has_line(v.lines[0]) and doc.has_line(v.lines[1]))
            ):
                out.append(
                    Finding(
                        code="sources", blocking=True, message=f"{e.id}.{k} has a script source outside the document"
                    )
                )
    return out


def _also_on_screen(sc: Scene, person: str) -> bool:
    """A person can be seen in a scene and ALSO be heard from a device (Mudalali fights, and his recorded voice
    plays)."""
    return any(b["speaker"] == person and b["presence"] == "on_screen" for b in sc.blocks) or any(
        person in e["actors"] and e["visible"] for b in sc.blocks for e in b["events"]
    )


def presence(bd: Breakdown) -> list[Finding]:
    """An on-screen speaker is in the scene's people as on_screen; a phone, voice message or recording is not."""
    out: list[Finding] = []
    for sc in bd.scenes:
        if not sc.brief:
            continue
        here = {p["person"]: p["presence"] for p in sc.brief["people"]}
        for b in sc.blocks:
            if b["kind"] != "dialogue" or not b["speaker"]:
                continue
            listed = here.get(b["speaker"])
            if b["presence"] == "on_screen" and listed != "on_screen":
                out.append(
                    Finding(
                        code="presence",
                        scene=sc.id,
                        blocking=True,
                        message=(f"{b['id']}: {b['speaker']} speaks on screen but is not listed as on_screen"),
                    )
                )
            if b["presence"] != "on_screen" and listed == "on_screen" and not _also_on_screen(sc, b["speaker"]):
                out.append(
                    Finding(
                        code="presence",
                        scene=sc.id,
                        blocking=True,
                        message=(f"{b['id']}: {b['speaker']} speaks as {b['presence']} but is listed as on_screen"),
                    )
                )
    return out


def continuity(bd: Breakdown) -> list[Finding]:
    """Report only: a thing starts where the scene before left it (page order stands in for story order here)."""
    out: list[Finding] = []
    ordered = [s for s in bd.scenes if s.brief]
    for a, b in itertools.pairwise(ordered):
        ends = {t["thing"]: t["holder_end"] for t in (a.brief or {})["things"] if t["holder_end"]}
        for t in (b.brief or {})["things"]:
            if t["thing"] in ends and t["holder_start"] and t["holder_start"] != ends[t["thing"]]:
                out.append(
                    Finding(
                        code="continuity",
                        scene=b.id,
                        message=(
                            f"{t['thing']} ends {a.id} with {ends[t['thing']]} but starts {b.id} with "
                            f"{t['holder_start']}"
                        ),
                    )
                )
    return out


def direction(bd: Breakdown) -> list[Finding]:
    return [
        Finding(code="direction", blocking=True, message=f"{r.id}: scope {r.scope_kind} does not resolve")
        for r in bd.rules
        if r.scope_kind != "all" and not r.scope_id
    ]


def length(bd: Breakdown) -> list[Finding]:
    """Reported, never trimmed."""
    out: list[Finding] = []
    for sc in bd.scenes:
        m = _MINUTES.search(sc.heading)
        if not m or not sc.blocks:
            continue
        spoken = sum(len(b["text"].split()) for b in sc.blocks if b["kind"] == "dialogue") / WPS
        stated = float(m.group(1)) * 60
        if spoken > stated:
            out.append(
                Finding(code="length", scene=sc.id, message=f"spoken {spoken:.0f} s is over the stated {stated:.0f} s")
            )
    return out


def cards(bd: Breakdown) -> list[Finding]:
    """Reports only (never deletes or merges): cards a person should look at."""
    out: list[Finding] = []
    heads = " ".join(s.heading.lower() for s in bd.scenes)
    seen_text: dict[tuple[str, str], str] = {}
    for e in bd.entities:
        if e.kind == "thing" and e.lines[1] - e.lines[0] > 10:
            out.append(
                Finding(
                    code="cards",
                    message=f"{e.id} {e.name!r} spans {e.lines[1] - e.lines[0] + 1} lines: a pointer this wide is a "
                            "guess",
                )
            )
        for o in bd.entities:
            if (
                o.id != e.id
                and o.kind == e.kind
                and o.place_kind == e.place_kind
                and e.name.lower() in o.name.lower()
                and len(e.name) < len(o.name)
            ):
                out.append(
                    Finding(code="cards", message=f"{e.id} {e.name!r} is inside {o.id} {o.name!r}: the same {e.kind}?")
                )
        d = e.card.get("details")
        if d and d.value:
            if (e.kind, d.value) in seen_text:
                out.append(
                    Finding(code="cards", message=f"{e.id} and {seen_text[e.kind, d.value]} carry the same detail text")
                )
            seen_text[e.kind, d.value] = e.id
        if e.kind == "place" and e.place_kind in ("set", "spot") and not e.within and e.place_kind == "spot":
            out.append(Finding(code="cards", message=f"{e.id} {e.name!r} is a spot with no set"))
        if e.kind == "place" and e.place_kind == "set" and e.name.lower() not in heads:
            out.append(Finding(code="cards", message=f"{e.id} {e.name!r} is a set no scene heading names"))
    return out


HEARD_THROUGH = ("phone", "voice_message", "recording")  # presences whose voice comes out of something
_THING_ID = re.compile(r"\bP\d{2,}\b")


def implied(bd: Breakdown) -> list[Finding]:
    """Report only (plan/2026-11-12 §3.2): an implied thing whose name is not a plain noun of at most three words was
    not made; the reader may only name a thing, never slip story into a name."""
    from contracts.breakdown.build import NOUN, implied_name

    return [
        Finding(
            code="implied",
            scene=sc.id,
            message=f"implied thing {i['name']!r} is not a plain noun of at most three words: it was not recorded",
        )
        for sc in bd.scenes
        for i in (sc.brief or {}).get("implied", [])
        if not NOUN.match(implied_name(i["name"]))
    ]


def devices(bd: Breakdown) -> list[Finding]:
    """Report only (plan/2026-11-12 §3.3): a line heard through something names the thing it comes from, and that thing
    is one of the scene's things. No list of devices: the check asks only whether there is one and whether it exists."""
    out: list[Finding] = []
    for sc in bd.scenes:
        if not sc.brief:
            continue
        here = {t["thing"] for t in sc.brief["things"]}
        for b in sc.blocks:
            if b["kind"] != "dialogue" or b["presence"] not in HEARD_THROUGH:
                continue
            found = _THING_ID.findall(b["device"] or "")
            if not found or not any(x in here for x in found):
                out.append(
                    Finding(
                        code="device",
                        scene=sc.id,
                        message=(
                            f"{b['id']} is heard as {b['presence']} but names no device among the scene's things: a "
                            "planner may not show where the voice comes from"
                        ),
                    )
                )
    return out


def run_all(bd: Breakdown, doc: Doc) -> list[Finding]:
    """Runs every check, replaces the memory's findings with the build's own plus these, and returns these."""
    found = [
        *words(bd, doc),
        *id_check(bd),
        *sources(bd, doc),
        *presence(bd),
        *continuity(bd),
        *direction(bd),
        *length(bd),
        *cards(bd),
        *implied(bd),
        *devices(bd),
    ]
    bd.findings = [f for f in bd.findings if f.message.startswith("card ") and f.code == "sources"] + found
    return found
