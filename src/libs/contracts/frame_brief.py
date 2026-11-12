"""The first frame's brief (plan/2026-11-11b): the image prompt for a shot's opening still, built in code from
everything the planner already decided, and the images attached to it, each with its job.

Before this, the prompt read only the IR's four short `first_frame` lines and the panel's camera, so a night scene in
the rain was painted from "Cab interior moving through wet streets". Now, in a fixed order:

  lead · references (each with what to take from it) · shot · composition · people · place and time · light ·
  colour and grade · mood · who is only heard · the fixed close

The fuller IR field wins over the short frame line; a person's own camera change wins over both. Lens and stop are
written as what they look like, never as numbers (a number in an image prompt is what models letter onto the
picture). The scene's treatment (the colour script of the shot's sequence, the moment's feeling) is read from the
planner's stored plan on the scene row, for a Raphael scene; any other scene simply has no such section.

One function, `frame_brief`, for every caller: the shot screen shows exactly what the renderer will send.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts.camera_words import camera_words, lens_look, lighting_words
from contracts.camera_words import changed as _changed
from contracts.canon import look_sheet_path
from contracts.holding import references_for
from contracts.producer import (
    CAMERA_OPTIONS,
    DRAFT_LABEL,
    CameraField,
    CameraSettings,
    CastMember,
    PersonEdits,
    identity_line,
    shot_canon_ids,
)
from contracts.prompt_polish import POLISHABLE, usable
from contracts.staging import ShotIntent

Row = dict[str, Any]

# D5: the soft length of the whole prompt. Over it, the optional sections are cut in `CUT_ORDER`. Measured on Ekama
# S02 (run3): a Raphael shot with four pictures is ~2,450 characters uncut, so 2,000 would cut every mood and grade.
PROMPT_CAP = 2600
# The people seen, the place, a second place, what they hold, the same-setup frame; the image model takes up to 16.
MAX_REFERENCES = 6
# The label of a same-setup frame (§4.4). The prompt keys on its start, as it does for sheets and the draft.
SETUP_LABEL = "the accepted frame of shot"

LEAD = ("Photorealistic still frame from a Sri Lankan television drama, shot on a cinema camera with real optics and "
        "natural imperfections.")
GENERAL_GENRE = "television drama"
# plan/2026-11-12b: a shot whose script is only a cut to black or a title card is a black plate made by code, never
# painted (an image model given a place plate and a genre paints a scene into it)
BLACK_PLATE = ("A black plate, made by code: a cut to black or a title card is never painted; the title is added in "
               "post.")
_BLACK = re.compile(r"^\s*((smash\s+)?cut|fade(\s+out)?)\s+to\s+black\b|^\s*(black|black screen|darkness)\s*\.?\s*$"
                    r"|^\s*(main\s+)?(title|super|card|caption)\s*:", re.IGNORECASE)


def black_plate(texts: Iterable[str]) -> bool:
    """Every block a shot covers is a cut to black or a title card ("Cut to black.", "TITLE: EKAMA SAKSHIYA.")."""
    found = [t for t in texts if str(t).strip()]
    return bool(found) and all(_BLACK.search(str(t)) for t in found)


def lead_line(genre: str = "") -> str:
    """The prompt's first sentence. `genre` is the production's genre phrase (`contracts.memory.genre_of`,
    plan/2026-11-12b: "action and crime thriller"); none keeps LEAD byte for byte."""
    genre = " ".join(genre.split())
    return LEAD.replace(GENERAL_GENRE, genre, 1) if genre else LEAD
CLOSE_PLACE = "The people, place and everyday details are Sri Lankan."
CLOSE_SINGLE = "A single still frame: no text, no watermark, no captions, no collage, no split panels."


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else f"{text}."


def _has(container: str, part: str) -> bool:
    """`part` already said in `container` (loosely: case and punctuation do not count)."""
    def fold(s: str) -> str:
        return re.sub(r"^(the|a|an) ", "", " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()))
    return bool(part) and fold(part) in fold(container)


# plan/2026-11-09 (D4, Raphael first): the first frame is the clip's opening, so it shows the state the clip opens in
OPENS_LINE = "In this frame, as the clip opens: {state}."


def opens_line(shot: Mapping[str, Any]) -> str:
    """The state a Raphael shot opens in (its intent's `opens`, from the scene's state ledger), for the still, so the
    still and the video agree. "" for every other planner and for a shot with no ledger."""
    if str(shot.get("planner") or "") != "raphael":
        return ""
    intent = ShotIntent.of(shot)
    state = " ".join((intent.opens if intent else "").split()).rstrip(" .;,")
    return OPENS_LINE.format(state=state) if state else ""


# ── the camera as it looks ──────────────────────────────────────────────────────────────────


def _mm(text: str) -> int | None:
    found = re.search(r"(\d{2,3})\s*mm", text or "")
    return int(found.group(1)) if found else None


def _stop(text: str) -> float | None:
    found = re.search(r"f\s*/\s*(\d+(?:\.\d+)?)", text or "", re.I)
    return float(found.group(1)) if found else None


def nearest_option(f: CameraField, text: str) -> str:
    """The panel's lens or stop nearest to what a planner wrote ("braced handheld, 65mm, f/2.8" → "50mm", "f/2.8");
    "" when it names none. A tie goes to the longer lens and the smaller opening."""
    if f == CameraField.LENS:
        mm = _mm(text)
        if mm is None:
            return ""
        lenses = CAMERA_OPTIONS[f]
        return min(lenses, key=lambda x: (abs(int(x[:-2]) - mm), -int(x[:-2])))
    if f == CameraField.APERTURE:
        stop = _stop(text)
        if stop is None:
            return ""
        stops = CAMERA_OPTIONS[f]
        return min(stops, key=lambda x: (abs(float(x[2:]) - stop), -float(x[2:])))
    raise ValueError(f"no nearest option for {f}")


def _cine(ir: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = ir.get("cinematography")
    return raw if isinstance(raw, Mapping) else {}


def _frame(ir: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = ir.get("first_frame")
    return raw if isinstance(raw, Mapping) else {}


def shot_section(ir: Mapping[str, Any], camera: CameraSettings, recommended: CameraSettings | None) -> str:
    """Every field of the camera panel as it stands (`contracts.camera_words`), for a still: size, angle, lens and stop
    with what they look like, focus, the move it opens, the side of the line of action."""
    out = f"Shot: {camera_words(camera, recommended, ir, still=True)}"
    if recommended is not None and camera.framing != recommended.framing:
        out += f" Compose it as a {camera.framing.lower()}."
    return out


# ── the scene's look (the planner's treatment) ──────────────────────────────────────────────


@dataclass(frozen=True)
class ShotLook:
    """What the scene's treatment says about one shot: its sequence's colour script and its moment's feeling."""

    palette: str = ""
    light: str = ""
    grade: str = ""
    feeling: str = ""
    ambience: str = ""
    mood: str = ""  # plan/2026-11-12b D7: the scene packet's mood words, "bleak, restrained, ominous"


def shot_look(scene: Mapping[str, Any] | None, slate: str) -> ShotLook:
    """From the Raphael plan stored on the scene (`scenes.raphael`): the clip with this slate → its moment → that
    moment's sequence → the colour script entry. Empty for any other scene, or a slate the plan does not have."""
    raw = (scene or {}).get("raphael")
    plan: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    clip = next((c for c in plan.get("clips") or [] if isinstance(c, Mapping) and slate
                 and str(c.get("slate") or "") == slate), None)
    if clip is None:
        return ShotLook()
    edit = plan.get("edit") if isinstance(plan.get("edit"), Mapping) else {}
    moment = next((m for m in (edit or {}).get("moments") or []
                   if isinstance(m, Mapping) and m.get("n") == clip.get("moment")), {})
    treatment = (edit or {}).get("treatment") if isinstance((edit or {}).get("treatment"), Mapping) else {}
    colour = next((c for c in (treatment or {}).get("colour_script") or []
                   if isinstance(c, Mapping) and moment and c.get("sequence") == moment.get("sequence")), {})
    sound = clip.get("sound") if isinstance(clip.get("sound"), Mapping) else {}
    return ShotLook(palette=_clean(colour.get("palette")), light=_clean(colour.get("light")),
                    grade=_clean(colour.get("grade")), feeling=_clean(moment.get("feeling")),
                    ambience=" ".join(_clean((sound or {}).get(k)) for k in ("ambience", "effects")).strip(),
                    mood=", ".join(_clean(m) for m in plan.get("mood") or [] if isinstance(m, str) and _clean(m)))


# ── place, time and weather ─────────────────────────────────────────────────────────────────

_TIMES = (("NIGHT", "night"), ("DAWN", "dawn"), ("DUSK", "dusk"), ("SUNSET", "sunset"), ("EVENING", "evening"),
          ("MORNING", "morning"), ("AFTERNOON", "afternoon"), ("NOON", "midday"), ("DAY", "day"))
_WEATHER = ((r"\b(rain\w*|drizzl\w*|downpour|monsoon)\b", "rain"), (r"\bwet\b", "wet surfaces"),
            (r"\b(fog\w*|mist\w*|haze|hazy)\b", "mist"), (r"\b(storm\w*|thunder\w*)\b", "a storm"),
            (r"\b(wind\w*|gust\w*)\b", "wind"))


def time_phrase(scene: Mapping[str, Any] | None) -> str:
    """"night, interior" from the scene heading and its time of day; "" when neither says."""
    heading = _clean((scene or {}).get("heading")).upper()
    when = f"{_clean((scene or {}).get('time_of_day')).upper()} {heading}"
    time = next((word for key, word in _TIMES if key in when), "")
    # anywhere in the heading: a document's own heading may lead with its scene number ("SCENE 02 - INT. CASH VAN")
    place = ("interior and exterior" if re.search(r"\b(I/E|INT\.?\s*/\s*EXT)\b", heading)
             else "exterior" if re.search(r"\bEXT\b", heading) else "interior" if re.search(r"\bINT\b", heading)
             else "")
    return ", ".join(p for p in (time, place) if p)


def weather_phrase(*texts: str) -> str:
    """The weather the planner's own words name ("rain, wet surfaces"); never invented, "" when none is named."""
    words = " ".join(texts).lower()
    if re.search(r"\b(no|without)\s+rain\b", words):
        words = re.sub(r"\b(no|without)\s+rain\w*", " ", words)
    found = [label for pattern, label in _WEATHER if re.search(pattern, words)]
    return ", ".join(dict.fromkeys(found))


# ── references ──────────────────────────────────────────────────────────────────────────────


def sheet_path(row: Mapping[str, Any]) -> str:
    """The newest reference sheet of a canon entity's current card ("" when none is made)."""
    assets = (row.get("current") or {}).get("reference_assets") or []
    first = assets[0] if assets else None
    return str(first.get("path") if isinstance(first, dict) else first or "")


def _label_name(label: str, prefix: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", label[len(prefix):]).strip()


def reference_job(label: str) -> str:
    """What the image model takes from one attached picture, from its label: the faces from a sheet but not its light,
    the place from a plate but not its time of day, the framing and grade from the same-setup frame but not the pose.
    "" for the approved draft (its own paragraph says what to keep) and for a label this does not know."""
    for prefix, job in (
        ("the look sheet for ", "{n}'s face, body and clothes, not its light or backdrop"),
        ("the character sheet for ", "{n}'s face and body, not its light or backdrop"),
        ("the location plate for ", "the place and its fixtures, not its light or time of day"),
        ("the reference sheet for ", "{n} exactly as shown"),
        (SETUP_LABEL + " ", "the same camera setup: match its framing, light and grade, not the pose"),
    ):
        if label.startswith(prefix):
            return job.format(n=_label_name(label, prefix))
    return ""


@dataclass(frozen=True)
class PlannedReference:
    """One picture a frame wants: what it is (`id` a canon id, or a frame id for a same-setup frame), its role, and the
    (label, storage path) choices in the order they are tried. No choice = wanted but missing."""

    id: str
    role: str  # look | character | place | prop | setup
    name: str
    choices: tuple[tuple[str, str], ...]

    @property
    def label(self) -> str:
        return self.choices[0][0] if self.choices else ""


@dataclass(frozen=True)
class SetupFrame:
    """The accepted final frame of an earlier shot of the same camera setup (§4.4)."""

    frame_id: str
    slate: str
    path: str


def setup_of(slate: str) -> str:
    """"2B-2" → "2B": the camera setup a slate belongs to ("" for a shot with no slate)."""
    slate = _clean(slate)
    return slate.rsplit("-", 1)[0] if "-" in slate else ""


def setup_frame(shot: Mapping[str, Any], shots: Iterable[Mapping[str, Any]],
                accepted: Mapping[str, Mapping[str, Any]]) -> SetupFrame | None:
    """The first shot of this shot's setup, before it in the slate order, that has an accepted final frame with a
    picture (`accepted`: shot id → frame row). None for a shot with no setup, the first of its setup, a person who
    turned it off (`PersonEdits.setup_frame_off`), or when no earlier shot of the setup is accepted yet."""
    setup = setup_of(str(shot.get("slate") or ""))
    if not setup or PersonEdits.of(shot).setup_frame_off:
        return None

    def take(s: Mapping[str, Any]) -> int:
        tail = str(s.get("slate") or "").rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    mine = take(shot)
    earlier = sorted((s for s in shots if str(s.get("id")) != str(shot.get("id"))
                      and setup_of(str(s.get("slate") or "")) == setup and take(s) < mine), key=take)
    for s in earlier:
        frame = accepted.get(str(s["id"]))
        if frame and frame.get("storage_path"):
            return SetupFrame(frame_id=str(frame["id"]), slate=str(s.get("slate") or ""),
                              path=str(frame["storage_path"]))
    return None


def plan_references(scene: Mapping[str, Any], shot: Mapping[str, Any], canon: Sequence[Mapping[str, Any]],
                    on_screen: Sequence[str], looks: Mapping[str, Mapping[str, Any]],
                    *, setup: SetupFrame | None = None, limit: int = MAX_REFERENCES) -> list[PlannedReference]:
    """The pictures a frame is painted against, in their fixed order: the people the camera SEES, the scene's place,
    another place, what they hold (`contracts.holding.references_for`), then the same-setup frame. A person wearing a
    look is offered the look sheet first, the base sheet next. Someone only heard is never here: their sheet would put
    their face in the frame. Over `limit`, the last ones drop, so the same-setup frame goes before a prop and a prop
    before a person. An entry with no choices is wanted but has no picture (`missing_references`)."""
    by_id = {str(c["id"]): c for c in canon}
    names = {str(c["id"]): str(c.get("name") or "") for c in canon}
    edits = PersonEdits.of(shot)
    seen = {c: names[c] for c in on_screen if c in names}
    planned = references_for(scene, shot, canon, shot_canon_ids(scene, list(on_screen), edits), seen,
                             removed=edits.cast.remove, has_sheet=lambda r: bool(sheet_path(r)))
    out: list[PlannedReference] = []
    for cid, note in planned:
        row = by_id.get(cid)
        if not row or len(out) >= limit:
            continue
        kind = str(row["kind"])
        what = {"location": "the location plate for", "prop": "the reference sheet for"}.get(
            kind, "the character sheet for")
        choices = [(f"{what} {row['name']}" + (f" ({note})" if note else ""), sheet_path(row))]
        role = {"location": "place", "prop": "prop"}.get(kind, "character")
        look = looks.get(cid) if kind == "character" else None
        if look is not None:
            choices.insert(0, (f"the look sheet for {row['name']}", look_sheet_path(look)))
            role = "look"
        out.append(PlannedReference(id=cid, role=role, name=str(row["name"]),
                                    choices=tuple((label, path) for label, path in choices if path)))
    if setup is not None and len(out) < limit:
        out.append(PlannedReference(id=setup.frame_id, role="setup", name=setup.slate,
                                    choices=((f"{SETUP_LABEL} {setup.slate}", setup.path),)))
    return out


def missing_references(planned: Sequence[PlannedReference]) -> list[str]:
    """What a frame wanted but has no picture for, in words for the shot screen."""
    out = []
    for p in planned:
        if p.choices:
            continue
        if p.role in ("character", "look"):
            out.append(f"No sheet for {p.name}: their face is painted from words only.")
        elif p.role == "place":
            out.append(f"No location plate for {p.name}: the place is painted from words only.")
        else:
            out.append(f"No reference sheet for {p.name}: it is painted from words only.")
    return out


def references_block(labels: Sequence[str]) -> list[str]:
    """The sentences that name every attached picture, in order, and say what each is for. Built from the same list
    that is attached, so an attached picture is never left unnamed (it would still steer the frame, with no
    instruction)."""
    if not labels:
        return []
    named = "; ".join(f"image {n} is {label}" for n, label in enumerate(labels, start=1))
    parts = [f"Reference images, in order: {named}. Match them exactly: the same faces, hair, skin tone and build, "
             "the same place. Do not redesign anyone."]
    jobs = [f"image {n}: {job}" for n, label in enumerate(labels, start=1) if (job := reference_job(label))]
    if jobs:
        parts.append("Take from " + "; ".join(jobs) + ".")
    if any(label.startswith(DRAFT_LABEL) for label in labels):
        # The draft was painted small to settle the picture: keep what was settled, make it final.
        parts.append("The approved draft is a rough, low-quality version of this very frame: keep its composition, "
                     "framing, pose, expression, props and light exactly, and paint it again as the finished frame "
                     "with full detail and sharpness. The sheets still decide faces, hair and the place.")
    if any(label.startswith("the look sheet") for label in labels):
        # A look sheet IS the costume of this shot: clothes, hair, makeup and accessories.
        parts.append("A look sheet shows what that person wears in this shot: dress them exactly as their look sheet "
                     "shows, the same clothes, hair, makeup and accessories.")
    if any(label.startswith("the character sheet") for label in labels):
        # A sheet shows a plain reference outfit; the clothes of this shot come from the card.
        parts.append("A character sheet shows a plain reference outfit: take clothes from the People line, never "
                     "from the sheet, and if it names none dress them in plain everyday clothes.")
    return parts


# ── the brief ───────────────────────────────────────────────────────────────────────────────

# Cut first when the prompt is over `PROMPT_CAP` (D5). Never cut: references, shot, people, place and time, unseen.
CUT_ORDER = ("mood", "layers", "frame_light", "grade_script")
TITLES = {"lead": "Lead", "references": "Reference images", "shot": "Shot", "composition": "Composition",
          "people": "People", "place": "Place and time", "light": "Light", "colour": "Colour and grade",
          "mood": "Mood", "unseen": "Heard, not seen", "close": "Format"}


@dataclass
class BriefPart:
    """One piece of a section, with where its words came from (shown on the shot screen; a test checks a fact got
    in). `cut` names it in `CUT_ORDER` when it may go to keep the prompt under the cap."""

    text: str
    source: str
    cut: str = ""


@dataclass
class BriefSection:
    key: str
    parts: list[BriefPart] = field(default_factory=list)

    @property
    def title(self) -> str:
        return TITLES.get(self.key, self.key)

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.parts if p.text)

    def add(self, text: str, source: str, cut: str = "") -> None:
        text = _sentence(_clean(text))
        if text:
            self.parts.append(BriefPart(text=text, source=source, cut=cut))


@dataclass
class FrameBrief:
    sections: list[BriefSection]
    cut: list[str] = field(default_factory=list)  # what was cut to fit the cap, in `CUT_ORDER` words

    def text(self) -> str:
        return " ".join(s.text for s in self.sections if s.text)

    def view(self) -> list[Row]:
        """The sections for the shot screen: `{key, title, text, sources}`."""
        return [{"key": s.key, "title": s.title, "text": s.text,
                 "sources": list(dict.fromkeys(p.source for p in s.parts if p.text))}
                for s in self.sections if s.text]

    def fit(self, cap: int = PROMPT_CAP) -> FrameBrief:
        for name in CUT_ORDER:
            if len(self.text()) <= cap:
                break
            for s in self.sections:
                before = len(s.parts)
                s.parts = [p for p in s.parts if p.cut != name]
                if len(s.parts) != before and name not in self.cut:
                    self.cut.append(name)
        return self


def _subject_for(member: CastMember, ir: Mapping[str, Any]) -> Mapping[str, Any]:
    """The IR's subject entry for one person: by code, else the one whose description names them."""
    subjects = [s for s in ir.get("subjects") or [] if isinstance(s, Mapping)]
    by_code = next((s for s in subjects if str(s.get("id") or "") == member.code), None)
    if by_code is not None:
        return by_code
    name = member.name.lower()
    return next((s for s in subjects if name and name in _clean(s.get("description")).lower()), {})


def frame_brief(*, ir: Mapping[str, Any], camera: CameraSettings, aspect_ratio: str, cast: list[CastMember],
                references: list[str] | None = None, recommended: CameraSettings | None = None,
                recommended_framing: str = "", unseen: str = "", hands: str = "",
                scene: Mapping[str, Any] | None = None, shot: Mapping[str, Any] | None = None,
                cap: int = PROMPT_CAP, polished: bool = True, genre: str = "") -> FrameBrief:
    """The first frame's brief, from the shot's IR, the camera as it stands, the people the camera SEES (`cast`), the
    labels of the pictures attached IN ORDER (`references`), who is only heard (`unseen`,
    `contracts.staging.unseen_sentence`), who holds what (`hands`), and the scene row (heading, time of day, the
    planner's stored treatment). `recommended` lets a person's own camera change win over the planner's words;
    `recommended_framing` is the older way of saying the same for the size alone.

    `polished`: use the `prompt_writer`'s wording stored on the shot (`design.frame_polish`) for each section whose code
    text is still the one it was written from (`contracts.prompt_polish.usable`); False = the code's words only."""
    if recommended is None and recommended_framing and recommended_framing != camera.framing:
        recommended = camera.model_copy(update={"framing": recommended_framing})
    frame, cine = _frame(ir), _cine(ir)
    look = shot_look(scene, str((shot or {}).get("slate") or ""))
    sections = {k: BriefSection(k) for k in TITLES}

    sections["lead"].add(lead_line(genre), "fixed")
    for line in references_block(list(references or [])):
        sections["references"].add(line, "attached images")
    sections["shot"].add(shot_section(ir, camera, recommended), "camera + ir.cinematography")

    composition = sections["composition"]
    composition.add(_clean(frame.get("composition")), "ir.first_frame.composition")

    people = sections["people"]
    seen = [c for c in cast if c.kind == "character"]
    lines = []
    for c in seen:
        head = identity_line(c)
        bits = [head]
        subject = _subject_for(c, ir)
        dressed = bool(c.look or c.wardrobe_anchor)
        description = _clean(subject.get("description")).rstrip(".")
        if description.lower().startswith(c.name.lower()):
            description = description[len(c.name):].lstrip(" ,:;")
        if description and not dressed and not _has(head, description):
            # the planner's own description (its dress only where no card or look dresses them)
            bits = [f"{head}: {description}" if head == c.name else f"{head}; {description}"]
        position = _clean(subject.get("position"))
        if position:
            bits.append(position.rstrip("."))
        condition = _clean(c.condition).rstrip(".")
        if condition and not _has("; ".join(bits), condition):  # plan/2026-11-12c: the scene's, never the outfit's
            bits.append(f"in this scene: {condition}")
        lines.append("; ".join(bits))
    if lines:
        people.add("People: " + " | ".join(lines), "cast cards + ir.subjects")
    raw = frame.get("subjects")
    subject_text = "; ".join(_clean(s) for s in raw) if isinstance(raw, list) else _clean(raw)
    people.add(subject_text, "ir.first_frame.subjects")
    if hands:
        people.add(hands, "scene state ledger")

    place = sections["place"]
    setting, frame_setting = _clean(ir.get("setting")), _clean(frame.get("setting"))
    main = setting or frame_setting
    if main:
        place.add(f"Setting: {main.rstrip('.')}", "ir.setting" if setting else "ir.first_frame.setting")
    if setting and frame_setting and not _has(setting, frame_setting):
        place.add(f"In this frame: {frame_setting}", "ir.first_frame.setting")
    when = time_phrase(scene)
    if when:
        place.add(f"Time: {when}", "scene heading")
    lighting, frame_light = _clean(ir.get("lighting")), _clean(frame.get("lighting"))
    weather = weather_phrase(setting, frame_setting, lighting, frame_light, look.ambience, look.light,
                             _clean(ir.get("audio")))
    if weather:
        place.add(f"Weather: {weather}", "ir + sound")

    light = sections["light"]  # the panel's lighting always leads; the planner's light follows while it is not changed
    if _changed(camera, recommended, CameraField.LIGHTING):
        light.add(f"Lighting: {camera.lighting}", "camera (a person's choice)")
    elif lighting or frame_light:
        light.add(f"Lighting: {lighting_words(camera, recommended, lighting or frame_light)}",
                  "camera + ir.lighting" if lighting else "camera + ir.first_frame.lighting")
        if lighting and frame_light and not _has(lighting, frame_light):
            light.add(f"In this frame: {frame_light}", "ir.first_frame.lighting", cut="frame_light")
    elif look.light:
        light.add(f"Lighting: {lighting_words(camera, recommended, look.light)}", "camera + treatment.colour_script")
    else:
        light.add(f"Lighting: {camera.lighting}", "camera preset")
    balance = _clean(cine.get("white_balance"))
    if balance:
        light.add(f"Colour temperature: {balance}", "ir.cinematography.white_balance")

    colour = sections["colour"]
    tone = _clean(cine.get("color_tone"))
    if tone:
        colour.add(f"Colour: {tone}", "ir.cinematography.color_tone")
    if look.palette and not _has(tone, look.palette):
        colour.add(f"Palette: {look.palette}", "treatment.colour_script", cut="grade_script")
    if look.grade:
        colour.add(f"Grade: {look.grade}", "treatment.colour_script", cut="grade_script")

    if look.mood:  # plan/2026-11-12b D7: the scene's mood from its packet; short, so never cut
        sections["mood"].add(f"Scene mood: {look.mood}.", "packet.mood")
    if look.feeling:
        sections["mood"].add(f"Mood: {look.feeling}", "edit.moments.feeling", cut="mood")
    if unseen:
        sections["unseen"].add(unseen, "staging")
    sections["close"].add(CLOSE_PLACE, "fixed")
    sections["close"].add("9:16 vertical framing." if aspect_ratio == "9:16" else f"{aspect_ratio} framing.", "fixed")
    sections["close"].add(CLOSE_SINGLE, "fixed")
    brief = FrameBrief(sections=list(sections.values())).fit(cap)
    record = ((shot or {}).get("design") or {}).get("frame_polish") if polished else None
    if isinstance(record, Mapping) and record:
        for s in brief.sections:
            text = usable(record, s.key, s.text) if s.key in POLISHABLE["first_frame"] else ""
            if text:
                s.parts = [BriefPart(text=text, source="prompt_writer")]
    return brief


def frame_prompt(*, ir: Mapping[str, Any], camera: CameraSettings, aspect_ratio: str, cast: list[CastMember],
                 references: list[str] | None = None, recommended_framing: str = "", unseen: str = "",
                 hands: str = "", recommended: CameraSettings | None = None, scene: Mapping[str, Any] | None = None,
                 shot: Mapping[str, Any] | None = None, genre: str = "") -> str:
    """The image prompt for a shot's first frame: `frame_brief(...).text()`."""
    return frame_brief(ir=ir, camera=camera, aspect_ratio=aspect_ratio, cast=cast, references=references,
                       recommended=recommended, recommended_framing=recommended_framing, unseen=unseen, hands=hands,
                       scene=scene, shot=shot, genre=genre).text()


def expected_frame(ir: Mapping[str, Any], scene: Mapping[str, Any] | None) -> str:
    """What the vision check compares the picture with, beyond who is in it: the opening composition, what the
    frame's subjects do, the time and the weather (§4.6)."""
    frame = _frame(ir)
    raw = frame.get("subjects")
    subjects: list[Any] = raw if isinstance(raw, list) else [raw] if raw else []
    bits = [_clean(frame.get("composition")), *[_clean(x) for x in subjects]]
    when = time_phrase(scene)
    if when:
        bits.append(f"Time: {when}.")
    weather = weather_phrase(_clean(ir.get("setting")), _clean(ir.get("lighting")), _clean(frame.get("setting")),
                             _clean(frame.get("lighting")))
    if weather:
        bits.append(f"Weather: {weather}.")
    return " ".join(b for b in bits if b).strip()


__all__ = [
    "CUT_ORDER",
    "MAX_REFERENCES",
    "OPENS_LINE",
    "PROMPT_CAP",
    "SETUP_LABEL",
    "BriefPart",
    "BriefSection",
    "FrameBrief",
    "PlannedReference",
    "SetupFrame",
    "ShotLook",
    "expected_frame",
    "frame_brief",
    "frame_prompt",
    "lens_look",
    "missing_references",
    "nearest_option",
    "opens_line",
    "plan_references",
    "reference_job",
    "references_block",
    "setup_frame",
    "setup_of",
    "sheet_path",
    "shot_look",
    "time_phrase",
    "weather_phrase",
]
