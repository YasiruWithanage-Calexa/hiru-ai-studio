"""The Scene board (plan/2026-11-14): ONE mannequin storyboard image per scene, painted before any first frame, so the
frames of a scene share place, light, props, camera positions and blocking by construction.

Ported from the storyboard lab (`lab/storyboard/run.py`, `frame.py`, plan/2026-11-13e §6c-6k) and kept pure: rows in,
words and pictures out, no store and no model. The engine (`hiru_ai.systems.scene_board`) reads, paints and stores;
the API reads `stale_cells` to say a board is out of date.

  writer      `writer_bundle` (what the board writer reads) → the `board_writer` agent → `Writer`
  image       `board_prompt` (code writes the sheet, the references and the rules; the writer fills the world, the
              geography and the panels) → `gpt-image-2` `images.edit`, LOW (MEDIUM a setting, never HIGH: D2)
  after       `cell_boxes` (gutter-aware crop) → one PNG per shot; `scene_sheet` draws the numbers (the image model
              never does) and black cells for black plates
  out of date `plan_pin` per cell at paint time; `stale_cells` compares it with the shot as it stands
  repaint     `repaint_mask` (transparent over the changed cells) + `repaint_prompt` (D7, method A)
  first frame `mannequin_paragraph`, `state_line`, `panel_text`, `frame_world`, `unmannequin` (§3.5)

People on the board are faceless, colour-coded mannequins: the board fixes WHERE everyone is and HOW they sit or stand,
never their faces, so no face drifts from the board into every frame (run_009, run_010).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Row = dict[str, Any]

# ── sizes and limits ────────────────────────────────────────────────────────────────────────

BOARD_SIZE = (1536, 1024)  # the image model's landscape size; every board is wide, whatever the production
BOARD_ASPECT = "16:9"
QUALITIES = ("low", "medium")  # D2: LOW by default, MEDIUM as a setting, never HIGH (the person's image rule)
DEFAULT_QUALITY = "low"
ONE_IMAGE = 16  # D5: up to 16 painted shots on one board (4x4 measured clean, run_004)
PART_SIZE = 12  # D5: above 16, parts of at most 12 ...
OVERLAP = 1  # ... the last panel of one part repeated as the first of the next
MAX_WRITER_PICTURES = 8  # the writer reads the reference pictures at detail low
WRITER_MAX_OUTPUT = 10000  # run_001 used 4,341 output tokens (1,931 reasoning): over 2x headroom
# Colours in person order (plan §3.2). Over six people the colours repeat (the lab never needed a seventh).
COLOURS = ("red", "blue", "yellow", "green", "purple", "orange")
OVERLAP_LABEL = "the approved last panel of the previous part of this scene's board"


def grid_for(n: int) -> tuple[int, int]:
    """(columns, rows) for n landscape panels on a landscape sheet: `ceil(sqrt(n))` columns."""
    n = max(n, 1)
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def parts_of(items: Sequence[Any]) -> list[list[Any]]:
    """D5: up to `ONE_IMAGE` items on one board; above that, parts of at most `PART_SIZE`, each part's first item the
    previous part's last (so the cut between two images is painted twice, from one picture)."""
    items = list(items)
    if len(items) <= ONE_IMAGE:
        return [items]
    out, start, step = [], 0, PART_SIZE - OVERLAP
    while start < len(items):
        out.append(items[start: start + PART_SIZE])
        if start + PART_SIZE >= len(items):
            break
        start += step
    return out


# ── the writer's input ──────────────────────────────────────────────────────────────────────


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


@dataclass
class BoardShot:
    """One shot of the scene as the board sees it. `painted` False: a black plate (a cut to black, a title card),
    never a panel, drawn by code as a black cell carrying its script line."""

    id: str
    number: int
    slate: str
    painted: bool
    text: str
    plan: Row = field(default_factory=dict)  # what the writer reads (`shot_plan`); empty for a black plate


def shot_plan(shot: Mapping[str, Any], script_lines: Sequence[str], spoken: Sequence[Mapping[str, Any]],
              on_screen: Sequence[str]) -> Row:
    """A painted shot's plan, as the writer reads it (lab `fetch.py`): never a first-frame prompt, the PLAN."""
    ir, intent = _mapping(shot.get("ir")), _mapping(shot.get("intent"))
    first = _mapping(ir.get("first_frame"))
    subjects = first.get("subjects")
    return {
        "number": int(shot.get("number") or 0), "slate": shot.get("slate"), "role": shot.get("role"),
        "size": shot.get("framing"), "duration_s": shot.get("duration_s"), "script_lines": list(script_lines),
        "spoken": [{k: str(d[k]) for k in ("speaker", "text", "delivery") if d.get(k)} for d in spoken],
        "story": intent.get("story", ""), "purpose": intent.get("purpose", ""), "on_screen": list(on_screen),
        "setting": ir.get("setting", ""), "composition": first.get("composition", ""),
        "opening_picture": list(subjects) if isinstance(subjects, list) else ([subjects] if subjects else []),
        "subjects": [{k: v for k, v in s.items() if k in ("id", "action", "position")}
                     for s in ir.get("subjects") or [] if isinstance(s, Mapping)],
        "cinematography": ir.get("cinematography") or {}, "lighting": ir.get("lighting", ""),
        "beats": [b.get("action", "") for b in ir.get("beats") or [] if isinstance(b, Mapping)],
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def board_shots(scene: Mapping[str, Any], shots: Sequence[Mapping[str, Any]], lines: Sequence[Mapping[str, Any]],
                seen: Mapping[str, Sequence[str]], plates: Iterable[str]) -> list[BoardShot]:
    """Every shot of the scene in order. `seen`: shot id → the names the camera sees; `plates`: the ids of the shots
    that are black plates (the engine's `frame_compose` decides, as it does for a frame)."""
    script = scene.get("script") or []
    plates = {str(p) for p in plates}
    spoken: dict[str, list[Mapping[str, Any]]] = {}
    for d in lines:
        if d.get("shot_id"):
            spoken.setdefault(str(d["shot_id"]), []).append(d)
    out = []
    for s in sorted(shots, key=lambda r: int(r.get("number") or 0)):
        blocks = range(int(s.get("block_start") or 0), int(s.get("block_end") or 0))
        texts = [str((script[b] or {}).get("text") or "") for b in blocks if b < len(script)]
        sid = str(s["id"])
        painted = sid not in plates
        out.append(BoardShot(id=sid, number=int(s.get("number") or 0), slate=str(s.get("slate") or ""),
                             painted=painted, text=" ".join(t for t in texts if t),
                             plan=shot_plan(s, texts, spoken.get(sid, []), seen.get(sid, [])) if painted else {}))
    return out


def colours_for(people: Sequence[str]) -> dict[str, str]:
    """name (or id) → mannequin colour, in person order."""
    return {p: COLOURS[i % len(COLOURS)] for i, p in enumerate(dict.fromkeys(people))}


def writer_bundle(scene: Mapping[str, Any], shots: Sequence[BoardShot], people: Sequence[Row], place: Row,
                  props: Sequence[Row], reference_labels: Sequence[str]) -> Row:
    """What the board writer reads about the scene (lab `fetch.py` bundle, without file paths)."""
    script = scene.get("script") or []
    staging = (scene.get("staging") or {}) if isinstance(scene.get("staging"), Mapping) else {}
    return {
        "scene": {"heading": scene.get("heading"), "title": scene.get("title"),
                  "time_of_day": scene.get("time_of_day"),
                  "script": [b.get("text") for b in script if isinstance(b, Mapping) and b.get("text")],
                  "mood": ((scene.get("raphael") or {}) if isinstance(scene.get("raphael"), Mapping) else {}
                           ).get("mood", []),
                  "axis": ((scene.get("coverage") or {}) if isinstance(scene.get("coverage"), Mapping) else {}
                           ).get("axis", ""),
                  "staging": [{k: m[k] for k in ("who", "zone", "block", "posture", "holding") if m.get(k)}
                              for m in staging.get("marks") or [] if isinstance(m, Mapping)]},
        "people": list(people), "place": place, "props": list(props),
        "shots": [s.plan for s in shots if s.painted],
        "reference_pictures": [f"image {i}: {label}" for i, label in enumerate(reference_labels, 1)],
    }


def mannequin_note(colours: Mapping[str, str]) -> str:
    """What the writer is told about the mannequins (lab `run.py mannequin_note`)."""
    named = ", ".join(f"{n} = the {c} mannequin" for n, c in colours.items())
    return ("MANNEQUIN BOARD. Every person is painted as a smooth, faceless, colour-coded artist's mannequin, at the "
            f"person's height and build: {named}. So describe each person ONLY by their mannequin's pose: where the "
            "body sits or stands, which way the chest faces, which way the head turns, where each hand is, what it "
            "holds or touches. Never describe a face, expression, mouth, eyes, hair, skin or clothes. Props, the place "
            "and the light are described and painted for real. A person shown INSIDE a photograph, poster or screen "
            "in the scene is not a mannequin: describe that picture as a real photograph. For each panel also list, "
            "in `people`, every person the panel shows with their STATE at the opening of the shot (eyes open or "
            "closed, still, asleep, crying, breathing hard; empty when nothing is notable): the state is never drawn "
            "on the board, it is carried to the first frame.")


def writer_message(bundle: Mapping[str, Any], colours: Mapping[str, str], *,
                   repaint: Mapping[int, str] | None = None) -> str:
    """The writer's user message (lab `writer_input` + the mannequin note). `repaint`: shot number → the person's
    note, when only those panels are being repainted (the notes of other panels are never sent)."""
    n = len(bundle["shots"])
    cols, rows = grid_for(n)
    text = (f"<scene>\n{json.dumps(bundle, ensure_ascii=False, indent=1)}\n</scene>\n\n"
            f"Write the storyboard: {n} panels, one per shot in shot order, laid out {cols} across and {rows} down. "
            "The reference pictures follow, in the same order as `reference_pictures`.\n\n" + mannequin_note(colours))
    if repaint:
        notes = "\n".join(f"- shot {k}: {v}" if v else f"- shot {k}" for k, v in sorted(repaint.items()))
        text += ("\n\nREPAINT. Only these panels are being painted again; the others stay as they are. Write every "
                 "panel as usual, but take particular care with these, and follow the person's note where there is "
                 f"one:\n{notes}")
    return text


# ── the writer's answer ─────────────────────────────────────────────────────────────────────


@dataclass
class PanelPerson:
    name: str
    state: str = ""


@dataclass
class Panel:
    shot: int  # the shot NUMBER
    zone: str
    camera: str
    background: str
    picture: str
    people: list[PanelPerson] = field(default_factory=list)


@dataclass
class Writer:
    world: str
    geography: str
    panels: list[Panel]
    conflicts: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> Writer:
        panels = [Panel(shot=int(p.get("shot") or 0), zone=_clean(p.get("zone")), camera=_clean(p.get("camera")),
                        background=_clean(p.get("background")), picture=_clean(p.get("picture")),
                        people=[PanelPerson(name=_clean(x.get("name")), state=_clean(x.get("state")))
                                for x in p.get("people") or [] if isinstance(x, Mapping)])
                  for p in raw.get("panels") or [] if isinstance(p, Mapping)]
        return cls(world=_clean(raw.get("world")), geography=_clean(raw.get("geography")), panels=panels,
                   conflicts=[_clean(c) for c in raw.get("conflicts") or [] if _clean(c)])

    def dump(self) -> Row:
        return {"world": self.world, "geography": self.geography, "conflicts": self.conflicts,
                "panels": [{"shot": p.shot, "zone": p.zone, "camera": p.camera, "background": p.background,
                            "picture": p.picture, "people": [{"name": x.name, "state": x.state} for x in p.people]}
                           for p in self.panels]}

    def panel(self, number: int) -> Panel | None:
        return next((p for p in self.panels if p.shot == number), None)

    def merged(self, fresh: Writer, numbers: Iterable[int]) -> Writer:
        """This answer with the panels of `numbers` taken from `fresh` (a repaint keeps the world and geography the
        unchanged panels were painted with)."""
        take = set(numbers)
        panels = [fresh.panel(p.shot) or p if p.shot in take else p for p in self.panels]
        return Writer(world=self.world, geography=self.geography, panels=panels,
                      conflicts=list(dict.fromkeys([*self.conflicts, *fresh.conflicts])))


def missing_panels(writer: Writer, numbers: Iterable[int]) -> list[int]:
    """The painted shots the writer gave no panel (a board is painted only when this is empty)."""
    have = {p.shot for p in writer.panels}
    return [n for n in numbers if n not in have]


# ── the image prompt ────────────────────────────────────────────────────────────────────────

# plan/2026-11-13e §6g: a principle for every board, never one scene's words.
BODIES = (
    "Bodies (every panel): each person sits or stands the way a real person does the task in front of them, never "
    "posed for the camera. The body faces the task and only the head turns: someone at a steering wheel sits squarely "
    "behind it, the wheel centred in front of the chest, back against the seat, both hands on the rim; someone at a "
    "desk sits square to it; someone at a stove faces the stove. A camera beside a person sees the body side-on, not "
    "the chest. Nobody looks into or faces the lens unless the panel says so. Head and eyes turn together: the eyes "
    "never roll hard to one side while the face points at the camera; a near-frontal face looks just past the lens.")
NO_TEXT = ("Draw NO text of any kind: no panel numbers, no captions, no titles, no timestamps, no arrows, no labels, "
           "no borders other than the gutters. The people, place and everyday details are Sri Lankan.")
_PLACE_JOB = ("the kind of place: its ground, water, plants, structures and materials. It is ONE view of the place; "
              "each panel has its own camera position, so do not repeat this view in every panel")


def mannequin_line(colours: Mapping[str, str]) -> str:
    named = "; ".join(f"{n} is the {c} mannequin" for n, c in colours.items())
    return ("People (every panel): every person is a smooth, matte, faceless artist's mannequin in one solid colour, "
            f"with jointed limbs and simple hands: {named}. A small raised ridge on the front of the head, where a "
            "nose would be, shows which way the head faces. Each mannequin has the person's real height and build and "
            "sits, stands and holds things exactly as a real person would. No faces, no hair, no clothes, no skin: "
            "only the mannequin colour. Everything else (the place, the props, the light, the weather) is a real, "
            "photorealistic film still.")


def board_job(label: str) -> str:
    """What the board takes from one attached picture. The board has only the place plate, prop sheets and, on a
    later part, the overlap panel: never a face or a look sheet (it has no faces)."""
    if label.startswith("the location plate for "):
        return _PLACE_JOB
    if label.startswith("the reference sheet for "):
        return f"{label[len('the reference sheet for '):]} exactly as shown"
    if label == OVERLAP_LABEL:
        return "panel 1 of this sheet, repeated exactly: the same camera, place, light and mannequins"
    return ""


_FACE_WORDS = re.compile(r"\b(face|features|skin|eyes|hair|stubble|beard|moustache|jaw|cheek|brow)", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def board_world(world: str, names: Iterable[str]) -> str:
    """The writer's World without its sentences describing a person's face (the board has no faces)."""
    names = [n for n in names if n]
    keep = [x for x in _SENTENCES.split(world.strip())
            if not (_FACE_WORDS.search(x) and any(n in x for n in names))]
    return " ".join(keep)


def board_prompt(writer: Writer, numbers: Sequence[int], labels: Sequence[str], colours: Mapping[str, str]) -> str:
    """The image prompt for one board (or one part): the panels of `numbers`, in order (lab `board_prompt` with
    mannequins). `labels` are the attached pictures in order; `colours`: name → colour."""
    n = len(numbers)
    cols, rows = grid_for(n)
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(labels, 1))
    jobs = "; ".join(f"image {i}: {job}" for i, label in enumerate(labels, 1) if (job := board_job(label)))
    order = "left to right, then top to bottom" if rows > 1 else "left to right"
    pos = []
    for i, number in enumerate(numbers):
        p = writer.panel(number)
        if p is None:
            continue
        r, c = divmod(i, cols)
        pos.append(f"PANEL {i + 1} (row {r + 1}, column {c + 1}) — {p.camera.rstrip('.')}. Background: "
                   f"{p.background.rstrip('.')}. {p.picture}")
    head = (f"A cinematic storyboard sheet for a Sri Lankan television drama: {n} photorealistic film stills of ONE "
            f"scene, laid out in a grid {cols} panels across and {rows} down, read {order}. Every panel is a landscape "
            "16:9 still of the same size, separated by thin, even, plain white gutters. All panels are the same "
            "moment's world, painted together: the same people, props, weather, light and colour grade in every "
            "panel.")
    refs = (f"Reference images, in order: {cite}." + (f" Take from {jobs}." if jobs else "")) if labels else ""
    return "\n\n".join(x for x in [
        head, refs, mannequin_line(colours),
        "World (every panel): " + board_world(writer.world, colours),
        "Geography: " + writer.geography,
        "\n".join(pos), BODIES, NO_TEXT,
    ] if x)


def repaint_prompt(writer: Writer, numbers: Sequence[int], repaint: Sequence[int], labels: Sequence[str],
                   colours: Mapping[str, str]) -> str:
    """D7 method A: image 1 is the board itself, with a mask over the cells being repainted. Only those panels are
    described; the rest of the sheet stays exactly as it is."""
    cols, _ = grid_for(len(numbers))
    which = []
    for i, number in enumerate(numbers):
        p = writer.panel(number)
        if number in repaint and p is not None:
            r, c = divmod(i, cols)
            which.append(f"PANEL {i + 1} (row {r + 1}, column {c + 1}) — {p.camera.rstrip('.')}. Background: "
                         f"{p.background.rstrip('.')}. {p.picture}")
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(labels, 1))
    return "\n\n".join([
        "Image 1 is a storyboard sheet of one scene of a Sri Lankan television drama: a grid of photorealistic film "
        "stills separated by thin white gutters. Paint again ONLY the masked panels listed below, each inside its own "
        "cell, in the same world as the rest of the sheet: the same place, light, weather, colour grade and "
        "mannequins. Everything outside the masked cells stays exactly as it is, the gutters too.",
        f"Reference images, in order: {cite}.",
        mannequin_line(colours),
        "World (every panel): " + board_world(writer.world, colours),
        "Geography: " + writer.geography,
        "\n".join(which), BODIES, NO_TEXT,
    ])


# ── cells, pins and out of date ─────────────────────────────────────────────────────────────

# The parts of a shot row the writer reads: when one changes, its panel no longer shows the shot.
_PIN_IR = ("setting", "first_frame", "subjects", "cinematography", "lighting", "beats")
_PIN_INTENT = ("story", "purpose", "on_screen")


def plan_pin(shot: Mapping[str, Any]) -> str:
    """What a panel was painted against: a hash of the shot's plan fields the writer read (its size, its blocks, the
    IR's picture fields and the intent's story, purpose and who is seen). Its number is not in it: a move is a change
    of the board's order (`Stale.order`), not of the panel."""
    ir, intent = _mapping(shot.get("ir")), _mapping(shot.get("intent"))
    body = {"framing": shot.get("framing") or "", "blocks": [shot.get("block_start"), shot.get("block_end")],
            "ir": {k: ir.get(k) for k in _PIN_IR}, "intent": {k: intent.get(k) for k in _PIN_INTENT}}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def new_cell(shot: BoardShot, shot_row: Mapping[str, Any], panel: int | None) -> Row:
    """A cell of a board: a painted panel (`panel` its 1-based place in the image) or a black plate."""
    return {"shot_id": shot.id, "number": shot.number, "kind": "painted" if shot.painted else "black",
            "panel": panel, "box": None, "path": None, "pin": plan_pin(shot_row) if shot.painted else "",
            "text": "" if shot.painted else shot.text[:300], "locked": False, "note": ""}


@dataclass
class Stale:
    """Why a board no longer shows the scene: shots that changed (by number), shots added or removed, a new order."""

    changed: list[int] = field(default_factory=list)  # painted panels whose shot changed
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    order: bool = False

    @property
    def whole(self) -> bool:
        """Only a whole repaint can mend it (shots added, removed or reordered)."""
        return bool(self.added or self.removed or self.order)

    @property
    def any(self) -> bool:
        return self.whole or bool(self.changed)

    def reasons(self) -> list[str]:
        out = []
        if self.changed:
            out.append(f"{shots_phrase(self.changed)} changed")
        if self.added:
            out.append(f"{shots_phrase(self.added)} added")
        if self.removed:
            out.append(f"{shots_phrase(self.removed)} removed")
        if self.order:
            out.append("the shots were reordered")
        return out


def shots_phrase(numbers: Sequence[int]) -> str:
    numbers = sorted(numbers)
    if len(numbers) == 1:
        return f"shot {numbers[0]}"
    return "shots " + ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"


def stale_cells(cells: Sequence[Mapping[str, Any]], shots: Sequence[Mapping[str, Any]]) -> Stale:
    """Compare a board's cells (every part's, in order) with the scene's shots as they stand. A black plate's cell is
    out of date only by order; a painted cell when its pin moved."""
    by_id = {str(s["id"]): s for s in shots}
    seen: dict[str, Mapping[str, Any]] = {}
    for c in cells:  # the overlap panel appears in two parts: the first one owns it
        seen.setdefault(str(c.get("shot_id")), c)
    out = Stale()
    for sid, c in seen.items():
        s = by_id.get(sid)
        if s is None:
            out.removed.append(int(c.get("number") or 0))
        elif c.get("kind") == "painted" and c.get("pin") and c.get("pin") != plan_pin(s):
            out.changed.append(int(s.get("number") or 0))
    out.added = [int(s.get("number") or 0) for sid, s in by_id.items() if sid not in seen]
    board_order = [sid for sid in seen if sid in by_id]
    now_order = [str(s["id"]) for s in sorted(shots, key=lambda r: int(r.get("number") or 0)) if str(s["id"]) in seen]
    out.order = board_order != now_order
    return out


def owner_cell(boards: Sequence[Mapping[str, Any]], shot_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """(the board part, its cell) that owns a shot's panel: the first part that paints it."""
    for b in sorted(boards, key=lambda r: int(r.get("part") or 1)):
        for c in b.get("cells") or []:
            if str(c.get("shot_id")) == str(shot_id):
                return b, c
    return None


# ── the first frame from a panel (§3.5) ─────────────────────────────────────────────────────


def mannequin_paragraph(colours: Mapping[str, str], faced: Iterable[str] = ()) -> str:
    """What the frame is told about the mannequins on its approved draft (lab `frame.py mannequin_paragraph`).
    `colours`: name → colour of the people this frame shows."""
    if not colours:
        return ""
    named = "; ".join(f"{n} is the {c} mannequin" for n, c in colours.items())
    faced = set(faced)
    face = ("Take each face, age and features ONLY from that person's face sheet and the clothes ONLY from their look "
            "sheet. " if faced else "Take each face and the clothes ONLY from that person's sheets. ")
    return (f"The approved draft shows every person as a coloured, faceless mannequin: {named}. Replace each mannequin "
            "with that real person, keeping exactly the mannequin's place in the frame, size, seated or standing pose, "
            "hand positions and the direction the head faces (the ridge on the mannequin's head is the nose). " + face
            + "No mannequin, no plastic and none of the mannequin's colour remains anywhere in the frame: the person "
            "has natural skin and real clothes. Nobody looks into the lens unless this shot says so.")


def state_line(opening: Sequence[str], people: Sequence[PanelPerson]) -> str:
    """Each person's state at the opening of the shot, as planned (run_016: without it, a person lying still woke
    up): the plan's opening picture, then the writer's per-person state where the plan does not already say it. The
    scene-wide `scene_looks.condition` stays OUT (it holds the whole scene's action, plan/2026-11-13e §2)."""
    said = " ".join(_clean(x) for x in opening if _clean(x))
    extra = [f"{p.name}: {p.state.rstrip('.')}." for p in people
             if p.state and p.name and p.state.lower().rstrip(".") not in said.lower()]
    text = " ".join([said, *extra]).strip()
    if not text:
        return ""
    return (f"Each person at the opening of this shot, as planned: {text} Keep each body exactly as flat, bent or "
            "upright as its mannequin, and each person's eyes and state exactly as planned.")


def unmannequin(text: str, colours: Mapping[str, str]) -> str:
    """The writer's mannequin words turned back into people: "the red mannequin" → "Nimal", "red head" → "head"."""
    for name, c in colours.items():
        text = re.sub(rf"\bthe {c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b(smooth,? )?{c} (?=(head|hands?|arms?|body|figure|shoulders?|chest|torso|thigh|knee|"
                      r"forearm|feet|foot|legs?)\b)", "", text, flags=re.IGNORECASE)
    return re.sub(r"\bmannequin's\b", "person's", re.sub(r"\bsmooth (?=head\b)", "", text))


_BOARD_WORDS = re.compile(r"\b(panels?|storyboard|grid|gutters?|mannequins?)\b", re.IGNORECASE)


def frame_world(world: str) -> str:
    """The board's World for a frame: without its sentences about the board itself (panels, grid, gutters) or the
    mannequin treatment, which would invite a grid or a plastic figure."""
    return " ".join(x for x in _SENTENCES.split(world.strip()) if not _BOARD_WORDS.search(x))


def panel_text(panel: Panel, colours: Mapping[str, str]) -> str:
    """"This shot: <camera>. Background: <background>. <picture>" in people's names."""
    return unmannequin(f"This shot: {panel.camera.rstrip('.')}. Background: {panel.background.rstrip('.')}. "
                       f"{panel.picture}", colours)


def frame_sections(writer: Writer, number: int, colours: Mapping[str, str], opening: Sequence[str],
                   faced: Iterable[str] = ()) -> list[str]:
    """The paragraphs a frame painted from its panel adds to its brief, in order: the mannequins, the state, the
    scene's world and this panel. `colours`: name → colour of the people this frame shows."""
    panel = writer.panel(number)
    if panel is None:
        return []
    return [x for x in (mannequin_paragraph(colours, faced), state_line(opening, panel.people),
                        ("The scene: " + unmannequin(frame_world(writer.world), colours)) if writer.world else "",
                        panel_text(panel, colours)) if x]
