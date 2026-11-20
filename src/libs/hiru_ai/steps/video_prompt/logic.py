"""The code around the video prompt agent (plan/2026-11-20b §4). JSON in, JSON out, no model.

    scene_brief(scene)              -> the <scene> part: identical for every clip of the scene (it caches)
    clip_brief(clip)                -> the <clip> part and the craft cards it gets (`cards_for`)
    gates(direction, clip)          -> the faults of an answer (a fault gets ONE repair call; then no prompt, D3)
    assemble(direction, clip, ...)  -> the prompt's sections, prose and checks (D8, D10, §4.4)

Ported from `lab/video_prompt/run.py` (`scene_brief`, `clip_brief`, `cards_for`, `gates`, `assemble`), which proved
them on Api Denna E01-S04; where this plan and the lab differ, the plan wins (the "notes to us" gate, the opening and
the join, the sections). The agent never sees a line it could change: every spoken word is put in here, by code.

`scene` is `{packet, genre, style_note}` (the scene packet, `contracts.breakdown.packet`). `clip` is the dict
`facts.clip_facts` builds from the shot producer's rows (`facts.py`): everything a brief, a gate or the assembly reads.
"""
from __future__ import annotations

import re
from typing import Any

from contracts import on_screen_text, safe_depiction
from contracts.producer import Check, PromptSection, PromptSegment, prompt_text
from contracts.sentences import body, sentence_breaks

Row = dict[str, Any]
NL = "\n"

SINHALA = re.compile(r"[඀-෿]")
LINE_ID = re.compile(r"\bL\d+\b|\bE\d+-S\d+-B\d+")
QUOTES = re.compile(r"[\"“”«»]")
SPEECH = re.compile(r"\b(say|says|said|saying|ask|asks|asked|tell|tells|told|repl(?:y|ies|ied)|whisper(?:s|ed)?|"
                    r"shout(?:s|ed)?|speak(?:s|ing)?|talk(?:s|ing)?|call(?:s)? out|murmur(?:s|ed)?|answers?)\b", re.I)
MOVING = re.compile(r"\b(handheld|hand-held|push(?:es)?[- ]in|dolly|pan(?:s|ning)?|tilt(?:s)?|zoom(?:s)?|tracking|"
                    r"drift(?:s)?|sway(?:s)?|creep(?:s)?)\b", re.I)
# plan §4.2 (new): the agent must not write notes to us into the prompt (gpt-5-mini did in the lab)
NOTES = re.compile(r"\(?[^.()]*\bin the edit\b[^.()]*\)?|\bnot spoken here\b|\bthe planner\b|\bthe brief\b", re.I)
# Camera gear named in a prompt is drawn into the picture: render 007 put a camera on a tripod in two takes after the
# camera section said "a steady frame on a tripod". The assembly says what the frame does instead.
GEAR = ((re.compile(r"\bframe\s+on\s+(?:a|the)\s+tripod\b", re.I), "unmoving frame"),
        (re.compile(r",?\s*\b(?:on|from|using)\s+(?:a|the)\s+tripod\b", re.I), ""),
        (re.compile(r"\btripod(?:[- ]mounted)?\b", re.I), "locked-off"))


def camera_words(text: str) -> str:
    """The camera section with no gear in it: "a steady frame on a tripod" -> "a steady unmoving frame"."""
    for pattern, said in GEAR:
        text = pattern.sub(said, text)
    return text


LIMITS = {"situation": 450, "people": 650, "camera": 300, "sound": 250, "step": 450}
SPOKEN_MODES = ("dialogue", "voiceover", "sung")
VIA = {"phone": "through the phone"}  # how a heard voice reaches the scene, in the line's head


# ── the clock the brief speaks (lab/sinhala_pace: Omni starts near 1 s, ~2.6 words/s, ~0.8 s between sentences) ─────


def speech_s(text: str) -> float:
    words = body(text)
    return round(1.0 + len(words.split()) / 2.6 + 0.8 * sentence_breaks(words), 1)


# ── the brief ──────────────────────────────────────────────────────────────────────────────────────────────────────


def line_ids(packet: Row) -> dict[str, str]:
    """Packet block id -> the short id every brief of the scene uses for the line said there (L<block number>)."""
    return {str(b["id"]): f"L{i}" for i, b in enumerate(packet.get("E_blocks") or [])
            if b.get("kind") == "dialogue" and b.get("speaker")}


def spoken_blocks(packet: Row) -> list[Row]:
    """The packet's spoken blocks in order: the n-th is the line row of `ord` n (D6, as raphael_write pairs them)."""
    return [b for b in packet.get("E_blocks") or [] if b.get("kind") == "dialogue" and b.get("speaker")]


def scene_brief(scene: Row) -> str:
    """The <scene> part (lab `scene_brief`): the scene, who wants and feels what, the production's direction, and every
    block in order with each line's id, speaker -> addressee, words, the reader's delivery note and its intent."""
    p = scene["packet"]
    a = p.get("A_scene") or {}
    names = {x["id"]: x["name"] for x in p.get("B_people") or []}
    short = line_ids(p)
    out = ["<scene>", f"Scene: {a.get('title') or a.get('heading') or ''}. {a.get('summary', '')}".rstrip(),
           f"What it is for: {a.get('purpose', '')}"]
    if scene.get("genre"):
        out.append(f"The production: a Sri Lankan {' '.join(str(scene['genre']).split())}.")
    if scene.get("style_note"):
        out.append(f"Its style: {' '.join(str(scene['style_note']).split())}")
    before, after = a.get("before_in_story") or {}, a.get("after_in_story") or {}
    if isinstance(before, dict) and before.get("ends_with"):
        out.append(f"Just before (the previous scene ends): {before['ends_with']}")
    if isinstance(after, dict) and after.get("opens_with"):
        out.append(f"Next (the following scene opens): {after['opens_with']}")
    place = p.get("C_place") or {}
    feeling = p.get("F_feeling") or {}
    raw_mood = feeling.get("mood")
    mood: list[Any] = raw_mood if isinstance(raw_mood, list) else []
    out.append(f"Place: {place.get('name', '')}. Mood of the scene: {', '.join(str(m) for m in mood)}.")
    out.append("People:")
    where = {"on_screen": "on screen", "phone": "heard on the phone only, never seen"}
    for x in p.get("B_people") or []:
        wants = _text(x.get("wants")).rstrip(".")
        start, end = _text(x.get("feeling_start")).rstrip("."), _text(x.get("feeling_end")).rstrip(".")
        out.append(f"- {x['name']} ({where.get(x.get('presence'), x.get('presence') or '')})"
                   + (f": wants to {wants}" if wants else "")
                   + (f"; feels {start.lower()} at the start, {end.lower()} by the end" if start or end else "") + ".")
    for r in a.get("relationships") or []:
        if isinstance(r, dict) and r.get("between"):
            out.append(f"Between {' and '.join(r['between'])}: {r.get('state', '')}")
    style = [" ".join(str(d.get("text") or "").split()) for d in p.get("G_direction") or []
             if isinstance(d, dict) and (d.get("about") != "other" or "style" in str(d.get("text")).lower()
                                         or "performance" in str(d.get("text")).lower())]
    if style:
        out.append("The production's direction: " + " ".join(style[:4]))
    out.append("Script, in order (a line's id is the name you use for it; the words are Sinhala):")
    for b in p.get("E_blocks") or []:
        hint = f" | how (the reader's note): {b['delivery_hint']}" if b.get("delivery_hint") else ""
        intent = f" | intent: {b['intent']}" if b.get("intent") else ""
        if b.get("kind") == "dialogue" and b.get("speaker"):
            who, to = names.get(b.get("speaker"), b.get("speaker")), names.get(b.get("addressee"), "")
            via = " (through the phone)" if b.get("presence") == "phone" else ""
            out.append(f"{short[str(b['id'])]} {who}{via} to {to or 'no one'}: \"{body(b['text'])}\"{hint}{intent}")
        else:
            out.append(f"action: {b.get('text', '')}{hint}{intent}")
    out.append("</scene>")
    return NL.join(out)


def _text(value: Any) -> str:
    """A packet value: "" for an `{"empty": ...}` marker."""
    return "" if isinstance(value, dict) else str(value or "")


def spoken(clip: Row) -> list[Row]:
    """The lines the clip itself speaks (D7): its lines when its sound mode is dialogue, voiceover or sung; none
    otherwise (a line over an ambient or silent clip is heard in the edit, never spoken in it)."""
    return list(clip.get("lines") or []) if clip.get("sound_mode") in SPOKEN_MODES else []


def heard_over(clip: Row) -> list[str]:
    """Lines heard in the edit over this clip, not spoken in it: context for the faces."""
    said = {ln["lid"] for ln in spoken(clip)}
    return [lid for lid in clip.get("edit_lines") or [] if lid not in said] + \
        ([ln["lid"] for ln in clip.get("lines") or []] if not spoken(clip) else [])


def cards_for(clip: Row) -> list[str]:
    """The craft cards for this clip (lab `cards_for`)."""
    lines = spoken(clip)
    seen_speak = [ln for ln in lines if not ln.get("heard")]
    heard = [ln for ln in lines if ln.get("heard")]
    out = []
    if seen_speak:
        out.append("dialogue")
    if heard or clip.get("voice_source") == "phone" or "phone" in str(clip.get("over") or "").lower():
        out.append("phone")
    if not lines and clip.get("in_frame"):
        out.append("silent")
    if not clip.get("in_frame") or clip.get("role") in ("insert", "establishing", "cutaway", "pov", "atmosphere"):
        out.append("detail")
    if lines:
        out.append("sinhala_voice")
    return list(dict.fromkeys(out))


def clip_brief(clip: Row) -> str:
    """The <clip> part (lab `clip_brief`), from the product's rows: the planner's camera, who is in frame dressed in the
    scene's look, who is only heard, the hands, the beats and sound, the lines spoken here with their seconds, the
    lines heard over it, how it opens and joins, and the pictures the take attaches."""
    out = [f"<clip slate=\"{clip.get('slate') or clip.get('code')}\">",
           f"Role: {clip.get('role') or 'shot'}; framing {clip.get('size', '')} ({clip.get('framing_words', '')}); "
           f"angle {clip.get('angle', '')}; lens {clip.get('lens', '')}; camera move: {clip.get('technique', '')} "
           f"({clip.get('movement', '')}); take {clip.get('take_s')} s."]
    for label, key in (("Why the planner made it", "why"), ("Planner's summary", "summary"), ("Setting", "setting"),
                       ("Light", "light")):
        if clip.get(key):
            out.append(f"{label}: {clip[key]}")
    for s in clip.get("in_frame") or []:
        out.append(f"In frame: {s['description']}" + (f" Position: {s['position']}" if s.get("position") else "")
                   + (f" Does: {s['action']}" if s.get("action") else ""))
    for h in clip.get("heard_people") or []:
        out.append(f"Only heard, never seen: {h}" + (" (through the phone)" if clip.get("voice_source") == "phone"
                                                      else ""))
    if not clip.get("in_frame"):
        out.append("No person in frame.")
    if clip.get("hands"):
        out.append(f"Hands (a fact, keep it): {clip['hands']}")
    if clip.get("opening"):
        out.append(f"Opens: {clip['opening_note']}")
    if clip.get("join_note"):
        out.append(f"Join: {clip['join_note']}")
    if clip.get("carried"):
        out.append(f"Carried over from the clip before: {clip['carried']}")
    beats = clip.get("beats") or []
    if beats:
        out.append("Planner's beats:")
        for b in beats:
            text = " ".join(str(b.get(k) or "") for k in ("director_line", "action", "performance")).strip()
            out.append(f"- {b.get('time', '')}: {text}")
    snd = clip.get("sound") or {}
    out.append(f"Planner's sound: ambience {snd.get('ambience', '') or '-'}; effects {snd.get('effects', '') or '-'}; "
               f"music {snd.get('music', '') or '-'}.")
    lines = spoken(clip)
    if lines:
        out.append("Lines SPOKEN in this clip (each exactly once in your flow, in this order):")
        for ln in lines:
            via = " (heard through the phone, never seen)" if ln.get("heard") else ""
            part = f", part {ln['part']} of {ln['parts']} of one line" if ln.get("parts", 0) > 1 else ""
            out.append(f"- {ln['lid']}: {ln['speaker']}{via}{part}, about {speech_s(ln['text'])} s of speech")
        total = sum(speech_s(ln["text"]) for ln in lines) + 0.8 * (len(lines) - 1)
        out.append(f"Speech in all: about {total:.1f} s of a {clip.get('take_s')} s take.")
    else:
        out.append("Nobody speaks in this clip.")
    under = heard_over(clip)
    if under:
        out.append(f"Heard in the edit over this clip, NOT spoken in it (context for the faces): {', '.join(under)}")
    pics = (["the opening frame"] if clip.get("opening") else []) + \
        [f"a face sheet and a look sheet for {s['name']}" for s in clip.get("in_frame") or [] if s.get("name")]
    if pics:
        out.append(f"Pictures attached for the video model: {'; '.join(pics)}. The frame already fixes the framing.")
    out.append("</clip>")
    return NL.join(out)


# ── gates (code, every answer) ─────────────────────────────────────────────────────────────────────────────────────


def gates(d: Row, clip: Row) -> list[str]:
    """The faults of the agent's answer (lab `gates`, with the heard-only fix and the plan's notes gate). Each gate
    passes a good answer: `tests` holds one per gate."""
    want = [ln["lid"] for ln in spoken(clip)]
    flow = [s for s in d.get("flow") or [] if isinstance(s, dict)]
    got = [str(s.get("line_id") or "") for s in flow if s.get("kind") == "line"]
    faults = []
    if got != want:
        faults.append(f"lines: this clip speaks {want or 'nothing'} in that order, each once; your flow has "
                      f"{got or 'none'}")
    texts = {k: str(d.get(k) or "") for k in ("situation", "people", "camera", "sound")}
    for n, s in enumerate(flow, 1):
        for k in ("text", "to", "how", "listener"):
            texts[f"flow {n} {k}"] = str(s.get(k) or "")
    every = " ".join(texts.values())
    for k, v in texts.items():
        if SINHALA.search(v):
            faults.append(f"{k}: Sinhala letters; never write a line's words")
        found = LINE_ID.search(v)
        if found:
            faults.append(f"{k}: a line or block id ({found.group(0)}) in the text")
        if QUOTES.search(v):
            faults.append(f"{k}: quotation marks")
        note = NOTES.search(v)
        if note:
            faults.append(f"{k}: a note to us ({note.group(0).strip()}); every word goes to the video model")
        limit = LIMITS.get(k, LIMITS["step"])
        if len(v) > limit:
            faults.append(f"{k}: {len(v)} characters, at most {limit}")
    if not want:
        said = sorted({m.group(0).lower() for m in SPEECH.finditer(every)})
        if said:
            faults.append(f"nobody speaks in this clip, but the text has: {', '.join(said)}")
    for name in clip.get("heard_people") or []:  # named AS heard is fine; placed in frame is not
        named = re.search(rf"\b{re.escape(name)}\b[^.;]*", str(d.get("people") or ""), re.I)
        if named and not re.search(r"heard|never in frame|never seen|phone|voice", named.group(0), re.I):
            faults.append(f"people: {name} is only heard and never in frame")
    if clip.get("locked_off") and MOVING.search(str(d.get("camera") or "")):
        faults.append(f"camera: the planner's camera is locked off; "
                      f"'{MOVING.search(str(d.get('camera') or '')).group(0)}' moves it")  # type: ignore[union-attr]
    for s in flow:
        if s.get("kind") == "line" and not str(s.get("how") or "").strip():
            faults.append(f"line {s.get('line_id')}: no delivery")
    declined = sorted({f.said for f in safe_depiction.blocking(every)})
    if declined:
        faults.append("words the video models decline: " + ", ".join(declined))
    return faults


# ── assembly ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _seg(text: str) -> PromptSegment:
    return PromptSegment(text=text)


def _end(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def register(clip: Row) -> str:
    """The register line after the flow: how the people speak, or that nobody does."""
    lines = spoken(clip)
    if not lines:
        return "Nobody speaks in this clip: no dialogue, no voice."
    seen = any(not ln.get("heard") for ln in lines)
    return (("They speak casual, everyday spoken Sinhala, the way people really talk in a Sri Lankan teledrama: not an "
             "interview, not a speech, nobody looks at the camera." if seen else
             "The voice speaks casual, everyday spoken Sinhala, like a real phone call in a Sri Lankan teledrama.")
            + " Only these words are spoken, only by the people named; English words in a line are said as Sri "
              "Lankans say them.")


def action_section(d: Row, clip: Row) -> PromptSection:
    """The flow: actions as the agent wrote them; each line its head, the line's exact words as a Sinhala segment,
    and what the listener does. Then the register line."""
    by_lid = {ln["lid"]: ln for ln in spoken(clip)}
    segments: list[PromptSegment] = []
    for s in d.get("flow") or []:
        if segments:
            segments.append(_seg(NL + NL))
        if s.get("kind") != "line":
            segments.append(_seg(_end(str(s.get("text") or ""))))
            continue
        ln = by_lid[str(s.get("line_id"))]
        how = str(s.get("how") or "").strip().rstrip(".:")
        if ln.get("heard"):
            via = VIA.get(clip.get("voice_source") or "", "from off screen")
            if how.lower().startswith(via):  # the agent said it too (live run 005 wrote it twice)
                how = how[len(via):].lstrip(" ,;:-")
            head = f"{ln['speaker']}'s voice {via}, {how}:"
            tail = "No one on screen mouths these words."
        else:
            head = f"{ln['speaker']}, to {str(s.get('to') or '').strip()}, {how}:"
            tail = ""
        segments += [_seg(head + NL), PromptSegment(sinhala=body(ln["text"]))]
        rest = " ".join(x for x in (tail, _end(str(s.get("listener") or ""))) if x)
        if rest:
            segments.append(_seg(NL + rest))
    segments.append(_seg(NL + NL + register(clip)))
    return PromptSection(id="action", title="Action & dialogue", segments=_merge(segments))


def _merge(segments: list[PromptSegment]) -> list[PromptSegment]:
    out: list[PromptSegment] = []
    for s in segments:
        if s.text is not None and out and out[-1].text is not None:
            out[-1] = _seg(out[-1].text + s.text)
        elif s.text != "":
            out.append(s)
    return out


def _section(sid: str, title: str, *texts: str) -> PromptSection | None:
    text = " ".join(t.strip() for t in texts if t and t.strip())
    return PromptSection(id=sid, title=title, segments=[_seg(text)]) if text else None


def assemble(d: Row, clip: Row, *, repaired: bool = False) -> Row:
    """The prompt (D8, D10): `sections` (opening, situation, people, action, camera, sound, rules, format), `prose`
    and `checks`. No "Image n" citations: the render adds them from the same list it attaches."""
    rules = [str(clip.get("hands") or ""), "Clean frame: no captions, no subtitles, no watermarks.",
             on_screen_text.VIDEO]
    sections = [s for s in (
        _section("opening", "First frame", str(clip.get("opening") or ""), str(clip.get("join") or ""),
                 f"Carried over: {clip['carried']}." if clip.get("carried") and clip.get("join") else ""),
        _section("situation", "Situation", str(d.get("situation") or "")),
        _section("people", "People", str(d.get("people") or "")),
        action_section(d, clip),
        _section("camera", "Camera", camera_words(str(d.get("camera") or ""))),
        _section("sound", "Sound", str(d.get("sound") or "")),
        _section("rules", "Rules", *rules),
        _section("format", "Format", f"Aspect ratio {clip.get('aspect_ratio', '16:9')}. Duration "
                                     f"{clip.get('take_s')} seconds. Ends on a cut."),
    ) if s is not None]
    return {"sections": [s.model_dump(exclude_none=True) for s in sections], "prose": prompt_text(sections),
            "checks": [c.model_dump() for c in checks(d, clip, sections, repaired=repaired)]}


def checks(d: Row, clip: Row, sections: list[PromptSection], *, repaired: bool = False) -> list[Check]:
    """What the Video prompt pane shows (§4.4). Speech against the take is reported, never trimmed."""
    out: list[Check] = []
    lines = spoken(clip)
    words = [seg.sinhala for s in sections for seg in s.segments if seg.sinhala is not None]
    if lines:
        verbatim = words == [body(ln["text"]) for ln in lines]
        out.append(Check(label="Lines verbatim from the script" if verbatim else "A line differs from the script",
                         tone="pass" if verbatim else "fail"))
        directed = all(str(s.get("how") or "").strip() and (str(s.get("to") or "").strip() or
                                                             by_heard(clip, str(s.get("line_id"))))
                       for s in d.get("flow") or [] if s.get("kind") == "line")
        out.append(Check(label="Direction for every line" if directed else "A line has no direction",
                         tone="pass" if directed else "advisory"))
        speakers = {ln.get("character_id") or ln["speaker"] for ln in lines if not ln.get("heard")}
        out.append(Check(label="One visible speaker" if len(speakers) == 1 else (
            "No speaker on screen" if not speakers else f"{len(speakers)} speakers in one clip"),
            tone="pass" if len(speakers) <= 1 else "advisory"))
        for name in clip.get("heard_people") or []:
            where = str(clip.get("voice_source") or "off screen").replace("_", " ")
            out.append(Check(label=f"Heard only · {name} ({where})", tone="pass"))
        missing = list(clip.get("voices_missing") or [])
        out.append(Check(label=f"No voice pin · {', '.join(missing)}" if missing else "Voice pins for every speaker",
                         tone="advisory" if missing else "pass"))
        speech = sum(speech_s(ln["text"]) for ln in lines) + 0.8 * (len(lines) - 1)
        take = float(clip.get("take_s") or 0)
        if take and speech > take + 0.05:
            out.append(Check(label=f"{speech:.1f} s of speech in a {clip.get('take_s')} s take", tone="advisory"))
    else:
        out.append(Check(label="Silence stated", tone="pass" if not words else "fail"))
    if repaired:
        out.append(Check(label="Repaired once", tone="advisory"))
    if clip.get("opening") and clip.get("carried_from"):
        out.append(Check(label=f"Starts on {clip['carried_from']}'s last frame", tone="pass"))
    elif clip.get("opening"):
        out.append(Check(label="Opens on the accepted first frame", tone="pass"))
    return out


def by_heard(clip: Row, lid: str) -> bool:
    return any(ln["lid"] == lid and ln.get("heard") for ln in spoken(clip))
