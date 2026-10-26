"""Shot IR → the Veo 3.1 prompt, as titled SECTIONS a person reads and copies to Flow.

Forked from PromptMotion `nova_producer/engine/serialize.py` (1d748dc), `build_veo31_shot_prompt`
and its helpers. Why an IR and code, not prose from the model: the guarantees have to run on
something structured. The approved lines are bound to the right speaker (Veo swaps speakers when
a prompt merely mentions people and quotes); wordless shots say so positively (a model given no
audio instruction invents speech); every constant sentence comes from the clip schema, so the
DP guidance and the delivered prose cannot drift.

Section order follows upstream's paragraph order: opening frame, style, setting (and what a
joined shot carries over), subjects, join, camera, lighting, voices, timed beats with the lines,
sound, constraints, format.

Hiru divergences (UPSTREAM.md): sections with segments instead of one string (Sinhala is its own
segment, so the panel renders it as Sinhala and the plain text stays byte-exact); the camera
section is rebuilt from the camera as it stands when a person changed it; voice casting comes
from canon voice pins; lines are placed on the beat the timing kernel bound them to, not spread
proportionally; no subject pin, asset or storyboard paths; no reference-sheet citation (Veo gets
the accepted first frame, which already carries identity).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from contracts.producer import CameraSettings, CastMember, Check, PromptSection, PromptSegment, camera_sentence
from shot_producer.engine.model import Line, ShotInput
from shot_producer.engine.schema import get_schema

Row = dict[str, Any]
_DANGLING = frozenset({"a", "an", "the", "and", "or", "but", "with", "in", "of", "to", "for", "on", "at", "by",
                       "from", "her", "his", "their", "its"})
_ANCHOR_CHARS = 70
_MIN_ANCHOR_CHARS = 18
_SENTINEL = "\u0000LINE\u0000"


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def _bare(text: object) -> str:
    """Clean text without its closing punctuation, for text this code ends with its own."""
    return _clean(text).rstrip(" .;,")


def _trim(text: str, limit: int) -> str:
    """Cut at a clause boundary and drop trailing connectives (upstream `_trim`)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", ";", ","):
        idx = cut.rfind(sep)
        if idx >= limit // 2:
            cut = cut[:idx]
            break
    else:
        cut = cut.rsplit(" ", 1)[0] or cut
    words = cut.split()
    while words and words[-1].lower().strip(",;:.—-") in _DANGLING:
        words.pop()
    return (" ".join(words).rstrip(" ,;:.—-")) or text[:limit].rstrip(" ,;:.—-")


def _anchor_phrase(text: str) -> str:
    first = re.split(r"[,;.]", text, maxsplit=1)[0].strip()
    if _MIN_ANCHOR_CHARS <= len(first) <= _ANCHOR_CHARS:
        return first
    return _trim(text, _ANCHOR_CHARS)


def who_clause(c: CastMember | None) -> str:
    """A short visual tag that binds a line to a VISIBLE person: 'the woman in a faded blue
    saree'. Wardrobe first; SHORT on purpose — it distinguishes, the frame describes."""
    if c is None:
        return ""
    gender = c.gender.strip().lower()
    noun = "man" if gender.startswith("m") else "woman" if gender.startswith(("f", "w")) else "person"
    wardrobe = _anchor_phrase(_clean(c.wardrobe_anchor or c.appearance))
    if wardrobe:
        return f"the {noun} in {(wardrobe[0].lower() + wardrobe[1:]).rstrip(' .,;:')}"
    # "the person" tells a video model nothing about which face is speaking: say nothing.
    return f"the {noun}" if noun != "person" else ""


@dataclass
class Context:
    """Everything a prompt is written from besides the shot itself."""

    aspect_ratio: str
    camera: CameraSettings  # as it stands now
    recommended: CameraSettings
    style_note: str = ""
    previous_code: str = ""
    carried: str = ""  # what a joined shot carries over from the previous one
    has_frame: bool = False  # an accepted first frame is attached


def _seg(text: str) -> PromptSegment:
    return PromptSegment(text=text)


def _section(sid: str, title: str, *texts: str) -> PromptSection | None:
    body = " ".join(t for t in texts if t and t.strip())
    return PromptSection(id=sid, title=title, segments=[_seg(body)]) if body else None


def _spoken(template: str, *, speaker: str, delivery: str, name: str, line: str) -> list[PromptSegment]:
    """A dialogue sentence with the Sinhala words as their own segment, byte-exact."""
    head, _, tail = template.format(speaker=speaker, delivery=delivery, name=name, line=_SENTINEL).partition(_SENTINEL)
    return [_seg(head), PromptSegment(sinhala=line), _seg(tail)]


def _line_segments(ln: Line, shot: ShotInput) -> list[PromptSegment]:
    rules = get_schema()
    who = next((c for c in shot.cast if c.id == ln.character_id), None)
    name = who.name if who else (ln.speaker.title() or "the speaker")
    anchor = who_clause(who)
    speaker = f"{name} ({anchor})" if anchor else name
    delivery = f" ({_clean(ln.delivery)})" if _clean(ln.delivery) else ""
    key = {"voiceover": "voiceover_line", "sung": "sung_line"}.get(shot.sound_mode, "dialogue_line")
    return _spoken(rules.render_rules[key], speaker=speaker, delivery=delivery, name=name, line=ln.text)


def _camera_text(ir: Row, ctx: Context) -> str:
    """The DP's camera, unless a person changed it: then the camera as it stands, in plain words,
    with only the DP's grade kept (the grade does not depend on the fields people choose)."""
    raw = ir.get("cinematography")
    cine: Row = raw if isinstance(raw, dict) else {}
    grade = ", ".join(b for b in (_clean(cine.get("white_balance")), _clean(cine.get("color_tone"))) if b)
    lens = _clean(cine.get("lens_artifacts"))
    changed = changed_fields(ctx)
    if changed - {"lighting"} or not cine:
        out = [f"Camera: {camera_sentence(ctx.camera)}"]
    else:
        cam = "; ".join(b for b in (_clean(cine.get("camera")), _clean(cine.get("angle")), _clean(cine.get("framing")),
                                    _clean(cine.get("movement")), _clean(cine.get("depth_of_field"))) if b)
        out = [f"Camera: {cam}."]
    if ctx.camera.axis.startswith("Side B"):
        out.append("Screen direction: the action plays right to left.")
    if grade:
        out.append(f"Grade: {grade}.")
    if lens and lens.lower() != "none":
        out.append(f"Lens: {lens}.")
    return " ".join(out)


def changed_fields(ctx: Context) -> set[str]:
    now, rec = ctx.camera.model_dump(), ctx.recommended.model_dump()
    return {k for k in now if now[k] != rec[k]}


def _voice_text(shot: ShotInput) -> str:
    rules = get_schema()
    said = []
    for cid in shot.speaker_ids:
        c = next((x for x in shot.cast if x.id == cid), None)
        if c is None or not c.voice_pin:
            continue
        anchor = who_clause(c)
        said.append(rules.render_rules["voice_speaker"].format(who=f"{c.name} ({anchor})" if anchor else c.name,
                                                               voice=_clean(c.voice_pin).rstrip(".")))
    return rules.render_rules["voice_cast"].format(voices=" ".join(said)) if said else ""


def _audio_text(shot: ShotInput, ir: Row) -> str:
    """What the soundtrack is, stated for every mode. Silence has to be ASKED for."""
    room = "; ".join(_bare(i.text) for i in shot.items if i.kind == "sound" and i.text.strip()) \
        or _bare(ir.get("audio"))
    mode, bits = shot.sound_mode, []
    if mode in ("music_only", "silent", "ambient"):
        bits.append("No dialogue. No voiceover. Nobody speaks on camera.")
    if mode == "silent":
        bits.append("Silence — no music, no room tone.")
    elif mode == "music_only":
        bits.append(f"Music only{': ' + room if room else ', the score carries the shot'}.")
    elif mode == "ambient":
        bits.append(f"Diegetic sound only: {room or 'natural sound of the location'}.")
    elif mode == "voiceover":
        bits.append("The spoken words are a voice off screen, exactly as written in the beats above."
                    + (f" Under it: {room}." if room else ""))
    elif mode == "sung":
        bits.append("Sung performance — the vocal is performed in frame and carries the shot.")
    elif mode == "dialogue":
        bits.append("Spoken dialogue only, exactly as written in the beats above and only from the named speakers. "
                    "No narration, no voiceover." + (f" Room sound: {room}." if room else ""))
    return " ".join(bits)


def _beats_section(shot: ShotInput, ir: Row, ctx: Context) -> PromptSection | None:
    beats = [b for b in ir.get("beats") or [] if isinstance(b, dict)]
    if not beats:
        return None
    drop_camera = bool(changed_fields(ctx) & {"framing", "movement", "speed"})
    by_beat: dict[int, list[Line]] = {}
    for ln in shot.lines:
        idx = ln.beat_index if ln.beat_index is not None and 0 <= ln.beat_index < len(beats) else len(beats) - 1
        by_beat.setdefault(idx, []).append(ln)
    segments = [_seg(f"Over {shot.duration_s} seconds:")]
    for n, beat in enumerate(beats):
        when = _clean(beat.get("time"))
        body = _bare(beat.get("director_line")) or _bare(beat.get("action"))
        detail = _bare(beat.get("action"))
        if body and detail and body != detail:
            body = f"{body}. {detail}"
        cam = _bare(beat.get("camera"))
        if cam and not drop_camera and cam.lower() not in ("unchanged", "as above", "same", "none"):
            body = f"{cam}. {body}" if body else cam
        line = f"\n{when}: {body}" if when else f"\n- {body}"
        if line.rstrip() and not line.rstrip().endswith((".", "!", "?", ":", "—")):
            line = line.rstrip() + "."
        segments.append(_seg(line))
        for ln in by_beat.get(n, []):
            segments.append(_seg(" "))
            segments.extend(_line_segments(ln, shot))
    return PromptSection(id="action", title="Action & dialogue", segments=_merge(segments))


def _merge(segments: list[PromptSegment]) -> list[PromptSegment]:
    out: list[PromptSegment] = []
    for s in segments:
        if s.text is not None and out and out[-1].text is not None:
            out[-1] = _seg(out[-1].text + s.text)
        elif s.text != "":
            out.append(s)
    return out


def _guard(shot: ShotInput) -> str:
    rules = get_schema()
    bits = [rules.rule("frame_hygiene"), rules.rule("lettering_clean"), rules.rule("anatomy")]
    if not shot.cast:
        bits.append(rules.rule("no_extra_people"))
    bits.append(rules.rule("physics"))
    return "Rendering constraints: " + " ".join(b for b in bits if b)


def build_sections(shot: ShotInput, ir: Row, ctx: Context) -> list[PromptSection]:
    rules = get_schema()
    spoken = shot.sound_mode in ("dialogue", "voiceover", "sung") and bool(shot.lines)
    opening = (rules.rule("opening_carried").format(previous=ctx.previous_code or "the previous shot")
               if shot.frame_strategy == "carry_last_frame" else rules.rule("opening_frame") if ctx.has_frame else "")
    setting = _clean(ir.get("setting"))
    subjects = [s for s in ir.get("subjects") or [] if isinstance(s, dict) and _clean(s.get("description"))]
    described = "; ".join(_bare(s.get("description")) + (f" — {_bare(s.get('action'))}" if s.get("action") else "")
                          for s in subjects)
    join = "" if shot.camera_link == "cut" else rules.rule(
        "join_continuous" if shot.camera_link == "continuous" else "join_match")
    light = _clean(ir.get("lighting"))
    if "lighting" in changed_fields(ctx):
        light = f"{ctx.camera.lighting}." + (f" {light}" if light else "")
    sections = [
        _section("opening", "First frame", opening),
        _section("style", "Style", rules.rule("medium_style"), _clean(ctx.style_note)),
        _section("setting", "Setting", f"{setting.rstrip('.')}." if setting else "",
                 f"Carried over: {ctx.carried}." if ctx.carried and shot.camera_link != "cut" else ""),
        _section("subjects", "Subjects", f"{described}." if described else ""),
        _section("join", "Join", join),
        _section("camera", "Camera", _camera_text(ir, ctx)),
        _section("lighting", "Lighting", f"{light.rstrip('.')}." if light else ""),
        _section("voices", "Voices", _voice_text(shot) if spoken else ""),
        _beats_section(shot, ir, ctx),
        _section("sound", "Sound", _audio_text(shot, ir)),
        _section("constraints", "Style lock & constraints",
                 rules.rule("lip_lock") if shot.cast else "", rules.rule("language_line") if spoken else "",
                 rules.rule("market_line"), _guard(shot)),
        _section("format", "Format", f"Aspect ratio {ctx.aspect_ratio}. Duration {shot.duration_s} seconds. "
                                     f"Ends on a cut."),
    ]
    return [s for s in sections if s is not None]


def prompt_checks(shot: ShotInput, sections: list[PromptSection], ctx: Context) -> list[Check]:
    """Free checks the prompt carries (PLAN.md §6.2 guardrails; Phase 5 adds `prompt_check`)."""
    checks: list[Check] = []
    sinhala = [seg.sinhala for s in sections for seg in s.segments if seg.sinhala is not None]
    if shot.lines:
        speakers = {ln.character_id or ln.speaker for ln in shot.lines}
        one = len(speakers) == 1
        checks.append(Check(label="One visible speaker" if one else f"{len(speakers)} speakers in one shot",
                            tone="pass" if one else "advisory"))
        verbatim = sinhala == [ln.text for ln in shot.lines]
        checks.append(Check(label="Lines verbatim from the script" if verbatim else "A line differs from the script",
                            tone="pass" if verbatim else "fail"))
        missing = [c.name for c in shot.cast if c.id in shot.speaker_ids and not c.voice_pin]
        checks.append(Check(label=f"No voice pin · {', '.join(missing)}" if missing else "Voice pins for every speaker",
                            tone="advisory" if missing else "pass"))
        if shot.word_target and shot.words > shot.word_target:
            over = f"{shot.words} words for a {shot.duration_s} s shot (about {shot.word_target} fit)"
            checks.append(Check(label=over, tone="advisory"))
    else:
        checks.append(Check(label="Silence stated", tone="pass" if not sinhala else "fail"))
    if shot.frame_strategy == "carry_last_frame":
        checks.append(Check(label=f"Starts on {ctx.previous_code or 'the previous'} take's last frame", tone="pass"))
    elif ctx.has_frame:
        checks.append(Check(label="Opens on the accepted first frame", tone="pass"))
    if changed_fields(ctx):
        checks.append(Check(label="Camera changed from the recommendation", tone="advisory"))
    return checks
