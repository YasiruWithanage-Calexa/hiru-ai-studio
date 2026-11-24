"""The code around the shot prompt agent (plan/2026-11-20d §4 phase 3). JSON in, JSON out, no model.

    camera_facts(settings, block, sentence)   -> the camera as the brief and the checks read it (the Camera agent's
                                                 design when it made one, else the panel's fields)
    shot_brief(facts)                         -> the <shot> part: the shot's facts
    camera_brief(camera)                      -> the <camera> part: the design to keep
    check(answer, facts, mode, fixed)         -> the faults (D6; a fault gets ONE repair, then nothing is stored)
    direction(answer)                         -> the video part, in the shape the `video_prompt` step assembles
    frame_parts(record)                       -> the frame part, the words `contracts.frame_brief` uses (D5)
    record(answer, ...)                       -> what `shots.design.shot_prompt` stores (D5)

Ported from `lab/shot_prompts/run.py` (`brief`, `check`), which proved them on the person's own scene; where the plan
and the lab differ the plan wins (the clock and edit words, safe depiction, notes to us, video-only mode). `facts` is
the `video_prompt` step's clip facts (`facts.clip_facts`) plus the frame's: the planner's opening picture
(`first_frame`), the state the shot opens in (`opens_state`) and the camera (`camera_facts`).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from contracts import camera as cam
from contracts import safe_depiction
from contracts.sentences import body

Row = dict[str, Any]
NL = "\n"
SPOKEN_MODES = ("dialogue", "voiceover", "sung")

GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|rig|drone|rails?|camera operator)\b",
                  re.I)
SINHALA = re.compile(r"[඀-෿]")
LINE_ID = re.compile(r"\bL\d+(?:\.\d+)?\b|\bE\d+-S\d+-B\d+")
QUOTES = re.compile(r"[\"“”«»]")
STILL_BAD = re.compile(r"\b(camera (?:moves|pushes|pulls|pans|tilts|zooms|tracks|arcs|rises|creeps)|begins to|"
                       r"starts to)\b", re.I)
ANGLE_WORDS = {"slightly_low": r"\b(low|below|looking (?:slightly )?up|up at)\b",
               "low": r"\b(low|below|looking up|up at)\b", "worms_eye": r"\b(ground|low|looking up)\b",
               "slightly_high": r"\b(high|above|looking (?:slightly )?down|down at|down on)\b",
               "high": r"\b(high|above|looking down|down at|down on)\b",
               "overhead": r"\b(overhead|above|straight down|top)\b", "dutch": r"\b(tilt|tilted|dutch|canted)\b"}
SIZE_WORDS = {"MS": r"\b(medium|waist|mid-thigh|knee)\b", "MWS": r"\b(medium[- ]wide|knee|full|wide)\b",
              "MLS": r"\b(medium[- ]long|knee|full|wide)\b", "MCU": r"\b(chest|medium close|close)\b",
              "CU": r"\b(close)\b", "ECU": r"\b(close|detail|macro)\b", "WIDE": r"\b(wide|full)\b",
              "EWS": r"\b(wide|vast|tiny|small)\b", "TWO": r"\b(two-shot|both|together|two)\b",
              "OTS": r"\b(over (?:the|his|her) shoulder|shoulder)\b", "INSERT": r"\b(insert|close|detail)\b"}
SPEECH = re.compile(r"\b(says|said|asks|asked|tells|replies|whispers|calls out|speaks)\b", re.I)
SILENT_OK = re.compile(r"\b(nobody|no one|no-one|none|neither) (?:of them )?(speaks|says|talks)\b", re.I)
# D6 (new): the lab's video text slipped clock and edit words in; the camera sentence and code hold the timing
CLOCK = re.compile(r"\b(?:(?:a|one|two|three|half|quarter|three-quarters?)[- ](?:of[- ]a[- ])?seconds?|"
                   r"\d+(?:\.\d+)?[- ]?(?:s|sec|secs|seconds?)\b|(?:one|two|three|four|five|six|seven|eight|nine|ten|"
                   r"twelve|fifteen)[- ]second|(?:lead|tail|head|edit) handles?|handles? of the (?:shot|clip|take)|"
                   r"the cut|a cut|cuts? (?:to|away)|in the edit)\b", re.I)
NOTES = re.compile(r"\bin the edit\b|\bnot spoken here\b|\bthe planner\b|\bthe brief\b", re.I)
LIMITS = {"situation": 450, "people": 650, "sound": 250, "step": 450, "frame": 2400}


# ── the facts ──────────────────────────────────────────────────────────────────────────────────────────────────────


def camera_facts(settings: Mapping[str, Any], block: Mapping[str, Any] | None, sentence: str) -> Row:
    """The camera as the brief states it and the checks hold it: the panel's fields as they stand (slugs for the angle,
    height and size), the Camera agent's design where it made one, and the sentence the video gets."""
    block = block or {}
    out: Row = {"angle": cam.slug_of("angle", str(settings.get("angle") or "")) or "eye_level",
                "height": cam.slug_of("height", str(settings.get("height") or "")) or "",
                "size": cam.slug_of("framing", str(settings.get("framing") or "")) or "",
                "lens": str(settings.get("lens") or ""), "aperture": str(settings.get("aperture") or ""),
                "focus": str(settings.get("focus") or ""), "composition": str(settings.get("composition") or ""),
                "move": str(settings.get("movement") or ""), "speed": str(settings.get("speed") or ""),
                "designed": bool(block), "sentence": " ".join(sentence.split())}
    for k in ("opens_on", "lands_on", "end_size", "direction", "start_s", "end_s", "trigger", "composition_note",
              "motivation"):
        if block.get(k) not in (None, ""):
            out[k] = block[k]
    return out


def spoken(facts: Mapping[str, Any]) -> list[Row]:
    return list(facts.get("lines") or []) if facts.get("sound_mode") in SPOKEN_MODES else []


def speech_s(text: str) -> float:
    words = body(text)
    return round(1.0 + len(words.split()) / 2.6 + 0.8 * (max(1, len(re.findall(r"[.?!…]+", words))) - 1), 1)


def shot_brief(facts: Mapping[str, Any]) -> str:
    """The <shot> part (lab `brief`, from the product's rows): what the shot is for, the place and light, who is in
    frame dressed in the scene's look and where, who is only heard, the hands, the planner's opening picture and the
    state the shot opens in, the beats, the sound, and the lines spoken here (ids and seconds, never the words)."""
    out = [f"<shot slate=\"{facts.get('slate') or facts.get('code')}\">",
           f"Role {facts.get('role') or 'shot'}; the planner's size {facts.get('size', '')}"
           + (f" ({facts['framing_words']})" if facts.get("framing_words") else "")
           + f"; take {facts.get('take_s')} s; sound {facts.get('sound_mode') or 'ambient'}."]
    for label, key in (("What it is for", "why"), ("Planner's summary", "summary"), ("Setting", "setting"),
                       ("Light", "light")):
        if facts.get(key):
            out.append(f"{label}: {facts[key]}")
    for s in facts.get("in_frame") or []:
        out.append(f"In frame: {s['description']}" + (f" Where: {s['position']}" if s.get("position") else "")
                   + (f" Does: {s['action']}" if s.get("action") else ""))
    for h in facts.get("heard_people") or []:
        out.append(f"Only heard, never seen: {h}" + (" (through the phone)" if facts.get("voice_source") == "phone"
                                                      else ""))
    if not facts.get("in_frame"):
        out.append("Nobody is in frame.")
    if facts.get("hands"):
        out.append(f"Hands (a fact, keep it): {facts['hands']}")
    ff = facts.get("first_frame") or {}
    if isinstance(ff, Mapping) and (ff.get("composition") or ff.get("subjects")):
        subjects = ff.get("subjects")
        said = "; ".join(str(x) for x in subjects) if isinstance(subjects, list) else str(subjects or "")
        out.append(f"Planner's opening picture: {ff.get('composition', '')}" + (f" | {said}" if said else ""))
    if facts.get("opens_state"):
        out.append(f"The state it opens in (people, hands, props): {facts['opens_state']}")
    board = facts.get("board") or {}
    if board:  # plan/2026-11-23d §2.2: a person approved this blocking; the camera stays the <camera> part's
        out.append("The approved scene board (a person approved it; keep its blocking, hands and props; never its "
                   "camera):")
        if board.get("blocking"):
            out.append(f"- Blocking: {board['blocking']}")
        for p in board.get("hands") or []:
            out.append(f"- {p['name']}: left hand {p['left_hand']}; right hand {p['right_hand']}")
        if board.get("background_view"):  # plan/2026-11-24: the location sheet's view behind them
            out.append(f"- Background view: {board['background_view']}")
        for pr in board.get("props") or []:
            where = (f"in {pr['held_by']}'s {pr.get('hand') or ''} hand".replace("  ", " ") if pr.get("held_by")
                     else f"resting on {pr['rests_on']}" if pr.get("rests_on") else "")
            out.append(f"- the {pr['name']}" + (f": {where}" if where else ""))
    if facts.get("opening_note"):
        out.append(f"Opens: {facts['opening_note']}")
    if facts.get("join_note"):
        out.append(f"Join: {facts['join_note']}")
    if facts.get("carried"):
        out.append(f"Carried over from the shot before: {facts['carried']}")
    beats = facts.get("beats") or []
    if beats:
        out.append("Planner's beats:")
        for b in beats:
            text = " ".join(str(b.get(k) or "") for k in ("director_line", "action", "performance")).strip()
            out.append(f"- {b.get('time', '')}: {text}")
    snd = facts.get("sound") or {}
    out.append(f"Planner's sound: ambience {snd.get('ambience', '') or '-'}; effects {snd.get('effects', '') or '-'}; "
               f"music {snd.get('music', '') or '-'}.")
    lines = spoken(facts)
    if lines:
        out.append("Lines SPOKEN in this clip (each exactly once in your flow, in this order):")
        for ln in lines:
            via = " (heard through the phone, never seen)" if ln.get("heard") else ""
            part = f", part {ln['part']} of {ln['parts']} of one line" if int(ln.get("parts") or 0) > 1 else ""
            out.append(f"- {ln['lid']}: {ln['speaker']}{via}{part}, about {speech_s(ln['text'])} s of speech")
    else:
        out.append("Nobody speaks in this clip.")
        heard = [ln["lid"] for ln in facts.get("lines") or []]
        if heard:
            out.append("Heard in the edit over this clip, NOT spoken in it (context for the faces): "
                       + ", ".join(heard))
    out.append("</shot>")
    return NL.join(out)


def camera_brief(c: Mapping[str, Any]) -> str:
    """The <camera> part: the Camera agent's design to keep (or the panel's camera when it did not design the shot)."""
    who = "the Camera agent's design: keep it" if c.get("designed") else "the camera as the panel stands: keep it"
    angle = cam.label_of("angle", str(c.get("angle") or "eye_level"))
    height = cam.label_of("height", str(c.get("height") or "")) if c.get("height") else ""
    out = [f"<camera> ({who})"]
    if c.get("opens_on"):
        out.append(f"Opens on: {c['opens_on']}." + (f" Lands on: {c['lands_on']}" if c.get("lands_on") else "")
                   + (f" ({c['end_size']})." if c.get("end_size") else ""))
    out.append(f"Angle {angle.lower()}" + (f", height {height.lower()}" if height else "") + ".")
    lens = " ".join(x for x in (f"Lens {c['lens']}" if c.get("lens") else "",
                                f"at {c['aperture']}" if c.get("aperture") else "") if x)
    extra = "; ".join(x for x in (f"focus {str(c['focus']).lower()}" if c.get("focus") else "",
                                  f"composition {str(c['composition']).lower()}" if c.get("composition") else "") if x)
    note = f" ({c['composition_note']})" if c.get("composition_note") else ""
    if lens or extra:
        out.append(f"{lens}{'; ' if lens and extra else ''}{extra}{note}.")
    move = str(c.get("move") or "Hold")
    timing = f", {c['start_s']}-{c['end_s']} s" if c.get("start_s") not in (None, "") and c.get("end_s") else ""
    out.append(f"Move: {move.lower()}" + (f" {c['direction']}" if c.get("direction") else "")
               + (f", {str(c['speed']).lower()}" if c.get("speed") and str(c["speed"]) != "None" else "") + timing
               + (f", on {c['trigger']}" if c.get("trigger") else "") + ".")
    if c.get("sentence"):
        out.append(f"The video's camera line (code puts it in): {c['sentence']}")
    out.append("</camera>")
    return NL.join(out)


# ── the checks (D6) ────────────────────────────────────────────────────────────────────────────────────────────────


def _first(name: str) -> str:
    return name.split("(")[0].strip().lower()


def _sentences_with(text: str, name: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", text) if _first(name) in s.lower()]


def _same(a: str, b: str) -> bool:
    a, b = _first(a), _first(b)
    return bool(a and b) and (a == b or a in b or b in a)


def video_text(a: Mapping[str, Any]) -> dict[str, str]:
    v = a.get("video") or {}
    texts = {k: str(v.get(k) or "") for k in ("situation", "people", "sound")}
    for n, s in enumerate(v.get("flow") or [], 1):
        if isinstance(s, Mapping):
            for k in ("text", "to", "how", "listener"):
                texts[f"flow {n} {k}"] = str(s.get(k) or "")
    return texts


def check(a: Mapping[str, Any], facts: Mapping[str, Any], *, mode: str = "both") -> list[str]:
    """The faults of an answer (lab `check`, D6). Each check passes a good answer; the step's tests hold a good/bad
    pair per check. In video-only mode the opening and frame are the stored ones (code puts them back), so only the
    video is checked against them."""
    faults: list[str] = []
    opening, frame, video = a.get("opening") or {}, a.get("frame") or {}, a.get("video") or {}
    want = [str(p["name"]) for p in facts.get("in_frame") or [] if p.get("name")]
    people = [p for p in opening.get("people") or [] if isinstance(p, Mapping)]
    got = [str(p.get("name") or "") for p in people]
    if len(got) != len(want) or not all(any(_same(w, g) for g in got) for w in want):
        faults.append(f"opening: people {got or 'none'} but the shot shows {want or 'nobody'}")
    frame_people = f"{frame.get('composition', '')} {frame.get('people', '')}"
    for p in people:
        name, side = str(p.get("name") or ""), str(p.get("side") or "")
        for where, text in (("frame", frame_people), ("video", str(video.get("people") or ""))):
            if _first(name) not in text.lower():
                faults.append(f"{where}: {name} is in the opening but not named here")
                continue
            if side in ("left", "right"):
                other = "right" if side == "left" else "left"
                said = " ".join(_sentences_with(text, name))
                if re.search(rf"\b{other}\b", said) and not re.search(rf"\b{side}\b", said):
                    faults.append(f"{where}: {name} is on the {other} here but on the {side} in the opening")
    c = facts.get("camera") or {}
    comp = str(frame.get("composition") or "")
    angle = str(c.get("angle") or "")
    if mode == "both" and angle in ANGLE_WORDS and not re.search(ANGLE_WORDS[angle], comp, re.I):
        faults.append(f"frame: the design's angle is {angle.replace('_', ' ')}"
                      + (f" ({str(c.get('height')).replace('_', ' ')})" if c.get("height") else "")
                      + " but the composition never says so in physical words")
    size = str(c.get("size") or facts.get("size") or "")
    if mode == "both" and size in SIZE_WORDS and not re.search(SIZE_WORDS[size], comp, re.I):
        faults.append(f"frame: the shot opens {size} but the composition does not say that framing")
    frame_text = " ".join(str(frame.get(k) or "") for k in ("composition", "people", "background", "light"))
    if mode == "both" and (w := STILL_BAD.search(frame_text)):
        faults.append(f"frame: a still has no motion ('{w.group(0)}')")
    if mode == "both" and len(frame_text) > LIMITS["frame"]:
        faults.append(f"frame: {len(frame_text)} characters, at most {LIMITS['frame']}")
    texts = video_text(a)
    every = " ".join(texts.values())
    for where, text in (("frame", frame_text if mode == "both" else ""), ("video", every)):
        if (g := GEAR.search(text)):
            faults.append(f"{where}: names camera gear ('{g.group(0)}')")
        if SINHALA.search(text) or LINE_ID.search(text) or QUOTES.search(text):
            faults.append(f"{where}: Sinhala, a line id or quotation marks in your text")
        if (n := NOTES.search(text)):
            faults.append(f"{where}: a note to us ('{n.group(0)}'); every word goes to a model")
    if (clock := CLOCK.search(every)):
        faults.append(f"video: a clock or edit word ('{clock.group(0)}'); say what happens and in what order")
    for k, v in texts.items():
        limit = LIMITS.get(k, LIMITS["step"])
        if len(v) > limit:
            faults.append(f"{k}: {len(v)} characters, at most {limit}")
    flow = [s for s in video.get("flow") or [] if isinstance(s, Mapping)]
    want_lines = [str(ln["lid"]) for ln in spoken(facts)]
    got_lines = [str(s.get("line_id") or "") for s in flow if s.get("kind") == "line"]
    if got_lines != want_lines:
        faults.append(f"video: lines {got_lines or 'none'}, the clip speaks {want_lines or 'nothing'} (each once, in "
                      "order)")
    for s in flow:
        if s.get("kind") == "line" and not str(s.get("how") or "").strip():
            faults.append(f"video: line {s.get('line_id')} has no delivery")
    if not want_lines and (spoke := SPEECH.search(SILENT_OK.sub("", every))):
        faults.append(f"video: somebody speaks in a clip where nobody speaks ('{spoke.group(0)}')")
    for name in facts.get("heard_people") or []:  # named AS heard is fine; placed in frame is not
        named = re.search(rf"\b{re.escape(name)}\b[^.;]*", f"{video.get('people', '')} {frame_people}", re.I)
        if named and not re.search(r"heard|never in frame|never seen|phone|voice|off[- ]screen", named.group(0), re.I):
            faults.append(f"people: {name} is only heard and never in frame")
    faults += timing_faults(flow, facts)
    if mode == "both":  # plan/2026-11-23d D2: what the approved board puts in a hand is in the frame
        held = {str(pr.get("name") or "").lower() for pr in (facts.get("board") or {}).get("props") or []
                if pr.get("held_by")}
        for thing in sorted(h for h in held if h):
            if not re.search(rf"\b{re.escape(thing.split()[-1])}", frame_text, re.I):
                faults.append(f"frame: the approved scene board has the {thing} in a hand, but the frame never "
                              "names it")
    declined = sorted({f.said for f in safe_depiction.blocking(f"{frame_text} {every}")})
    if declined:
        faults.append("words the image and video models decline: " + ", ".join(declined))
    return faults


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timing_faults(flow: list[Mapping[str, Any]], facts: Mapping[str, Any]) -> list[str]:
    """lab/timecodes (2026-11-21), Google's timecodes: every step's range runs in order from 0 to the take, no gap, no
    overlap, whole or half seconds, at least 1 s each, a line at least its speech time (half a second of slack: the
    clock is generous), and no more than about one step per 1.5 s."""
    if not flow:
        return []
    take = _num(facts.get("take_s")) or 0.0
    times = [(_num(s.get("start_s")), _num(s.get("end_s"))) for s in flow]
    if any(a is None or b is None for a, b in times):
        return ["video: every step needs its start_s and end_s"]
    out: list[str] = []
    if times[0][0] != 0 or (take and abs(float(times[-1][1] or 0) - take) > 1e-6):
        out.append(f"video: the steps' times must run from 0 to {take:g} s")
    for n, ((_a, b), (c, _d)) in enumerate(pairwise(times), 1):
        if abs(float(b or 0) - float(c or 0)) > 1e-6:
            out.append(f"video: step {n} ends at {float(b or 0):g} s but step {n + 1} starts at {float(c or 0):g} s")
    by_lid = {str(ln["lid"]): ln for ln in spoken(facts)}
    for n, (s, (a, b)) in enumerate(zip(flow, times, strict=True), 1):
        a, b = float(a or 0), float(b or 0)
        if b - a < 1 - 1e-6:
            out.append(f"video: step {n} lasts {b - a:g} s, at least 1 s")
        if (a * 2) % 1 or (b * 2) % 1:
            out.append(f"video: step {n}: whole or half seconds only")
        ln = by_lid.get(str(s.get("line_id") or "")) if s.get("kind") == "line" else None
        if ln is not None and b - a + 0.5 < speech_s(str(ln.get("text") or "")):
            out.append(f"video: step {n} speaks about {speech_s(str(ln.get('text') or ''))} s of words in {b - a:g} s")
    if take and len(flow) > max(2, round(take / 1.5)):
        out.append(f"video: {len(flow)} steps in {take:g} s, about one per 1.5 s at most")
    return out


# ── what is stored and handed on ───────────────────────────────────────────────────────────────────────────────────


def fixed_answer(a: Mapping[str, Any], stored: Mapping[str, Any] | None) -> Row:
    """Video-only mode (D4 b): the stored opening and frame put back, whatever the answer said of them."""
    out = dict(a)
    if stored:
        out["opening"], out["frame"] = stored.get("opening") or out.get("opening"), stored.get("frame") or out.get(
            "frame")
    return out


def direction(a: Mapping[str, Any]) -> Row:
    """The video part in the shape the `video_prompt` step gates and assembles (`situation, people, flow, sound`)."""
    v = a.get("video") or {}
    return {"situation": str(v.get("situation") or ""), "people": str(v.get("people") or ""),
            "flow": [dict(s) for s in v.get("flow") or [] if isinstance(s, Mapping)],
            "sound": str(v.get("sound") or "")}


def frame_parts(rec: Mapping[str, Any] | None) -> Row:
    """The frame part a stored shot prompt gives the frame brief (D5): composition, people, background, light."""
    frame = (rec or {}).get("frame") or {}
    return {k: " ".join(str(frame.get(k) or "").split()) for k in ("composition", "people", "background", "light")}


def now() -> str:
    return datetime.now(UTC).isoformat()


def record(a: Mapping[str, Any], *, model: str, job_id: str, pins: Mapping[str, Any], mode: str = "both",
           repaired: bool = False) -> Row:
    """What `shots.design.shot_prompt` stores (D5): the opening, the frame and the video, the pins it was written
    against (the shot's, with the picture and motion pins), the model, the job and when."""
    return {"opening": dict(a.get("opening") or {}), "frame": dict(a.get("frame") or {}),
            "video": dict(a.get("video") or {}), "pins": dict(pins), "model": model, "job_id": job_id,
            "mode": mode, "repaired": repaired, "written_at": now()}
