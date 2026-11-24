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
  update      plan/2026-11-17: an edited or added shot's panel is painted ON ITS OWN (`writer_message(edit=...)`,
              `panel_prompt`), its neighbours attached; removed and moved shots only tidy the cells; `keep_colours`,
              `renumber`, `insert_position`, `previous_for` are the pure steps. No mask: the image model does not
              honour one (lab/panel_edit run_001, D3)
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
from dataclasses import dataclass, field, replace
from typing import Any

from contracts import holding, picture_pins
from contracts import vehicles as vehicles_kit
from contracts.canon import VIEWS_LABEL_HEAD, view_key_words

Row = dict[str, Any]

# ── sizes and limits ────────────────────────────────────────────────────────────────────────

# A board has the production's shape (2026-11-16, lab/portrait_board run_001): a wide production paints a 1536x1024
# sheet of landscape panels, a vertical one a 1024x1536 sheet of tall panels, so each panel is the shape of its frame.
BOARD_ASPECT = "16:9"  # the default shape (a production without an orientation, and every board painted before)
TALL = "9:16"
QUALITIES = ("low", "medium")  # D2: LOW by default, MEDIUM as a setting, never HIGH (the person's image rule)
DEFAULT_QUALITY = "low"
ONE_IMAGE = 16  # D5: up to 16 painted shots on one wide board (4x4 measured clean, run_004)
PART_SIZE = 12  # D5: above 16, parts of at most 12 ...
OVERLAP = 1  # ... the last panel of one part repeated as the first of the next
# A tall sheet holds narrower panels: up to 6 on one image, the size measured clean (lab/portrait_board run_001), above
# that parts of at most 6 (plan/2026-11-23c D6: 9 panels of about 340x765 px floated an umbrella and added an arm).
ONE_IMAGE_TALL = 6
PART_SIZE_TALL = 6
_PANEL_SHAPE = {BOARD_ASPECT: "a landscape 16:9 still", TALL: "a tall portrait 9:16 still"}


def board_aspect(aspect: str | None) -> str:
    """The board's shape for a production of this aspect: tall for 9:16, wide for anything else."""
    return TALL if aspect == TALL else BOARD_ASPECT


def aspect_of_board(row: Mapping[str, Any]) -> str:
    """The shape a saved board was painted in, read from its own prompt (the only record of it: boards painted
    before 2026-11-16 are all wide and say so)."""
    return TALL if _PANEL_SHAPE[TALL] in str(row.get("prompt") or "") else BOARD_ASPECT
MAX_WRITER_PICTURES = 8  # the writer reads the reference pictures at detail low
# The whole-board writer's output budget, reasoning included. run_001 used 4,341; with the opening state, views and
# vehicles (plan/2026-11-23c, 2026-11-24c, 2026-11-24b) Love Hour 4 scene 2 (7 shots) used 8,374, and scene 4 (14
# shots, a 22,400-token message) spent all of 10,000 on reasoning and wrote nothing (2026-11-24). A budget only caps the
# spend: a board that needs less pays for less.
WRITER_MAX_OUTPUT = 32000
PANEL_WRITER_MAX_OUTPUT = 12000  # one panel: ~1,100-1,250 in lab/panel_edit; the same message parts as a whole board
PREVIOUS_KEPT = 3  # a cell keeps its last three pictures, so an undo is repainted for free (plan/2026-11-17 §3.6)
# Colours in person order (plan §3.2). Over six people the colours repeat (the lab never needed a seventh).
COLOURS = ("red", "blue", "yellow", "green", "purple", "orange")
OVERLAP_LABEL = "the approved last panel of the previous part of this scene's board"


def grid_for(n: int) -> tuple[int, int]:
    """(columns, rows) for n panels: `ceil(sqrt(n))` columns. On a wide sheet the panels come out wide; on a tall
    sheet (1024x1536) tall: 6 shots are 3 across and 2 down, about 340x765 each (lab/portrait_board run_001)."""
    n = max(n, 1)
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def parts_of(items: Sequence[Any], aspect: str = BOARD_ASPECT) -> list[list[Any]]:
    """D5: up to `ONE_IMAGE` items on one board (`ONE_IMAGE_TALL` on a tall one); above that, parts of at most
    `PART_SIZE` (`PART_SIZE_TALL`), each part's first item the previous part's last (so the cut between two images is
    painted twice, from one picture)."""
    items = list(items)
    one, size = (ONE_IMAGE_TALL, PART_SIZE_TALL) if aspect == TALL else (ONE_IMAGE, PART_SIZE)
    if len(items) <= one:
        return [items]
    out, start, step = [], 0, size - OVERLAP
    while start < len(items):
        out.append(items[start: start + size])
        if start + size >= len(items):
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
        # plan/2026-11-23c §3.1: what the face and hands do and the camera sentence, not the action alone
        "beats": [{k: str(b[k]) for k in ("action", "performance", "camera") if b.get(k)}
                  for b in ir.get("beats") or [] if isinstance(b, Mapping)],
        "opening_state": str(intent.get("opens") or ""),  # the ledger's state as the shot opens ("" without one)
        # plan/2026-11-23d §2.2: the camera the shot prompt and the first frame are written from
        "camera_design": camera_of(shot),
    }


def camera_of(shot: Mapping[str, Any]) -> Row:
    """The Camera agent's camera of a shot (plan/2026-11-23d §2.2), the one its shot prompt and first frame are written
    from: the picture fields of the recommendation with a person's changes on top (`picture_pins.PICTURE_FIELDS`),
    what the frame opens on, the composition note and why the angle. {} when the Camera agent did not design it (the
    planner's `ir.cinematography` is then the camera)."""
    design = _mapping(shot.get("design"))
    block = _mapping(design.get("camera"))
    if block.get("state") != "designed":
        return {}
    settings = {**_mapping(design.get("recommended")), **_mapping(shot.get("camera_overrides"))}
    out: Row = {f: str(settings[f]) for f in picture_pins.PICTURE_FIELDS if settings.get(f)}
    out.update({k: str(block[k]) for k in ("opens_on", "composition_note", "angle_reason") if block.get(k)})
    return out


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


# ── what the plan knows about a shot beyond its own row (plan/2026-11-23c §3.1) ─────────────────────────────────

MARK_KEYS = ("who", "zone", "facing", "frame_side", "posture", "holding", "left_hand", "right_hand", "condition",
             "wearing")
_BREAKDOWN_KEYS = ("blocking", "performance", "props", "light", "must_read")


def marks_at(marks: Sequence[Mapping[str, Any]], block: int, people: Sequence[str] = ()) -> list[Row]:
    """Each person's latest stager mark as `block` opens (every field the stager wrote), for `people` (their names;
    empty = everyone). Read by block number, so a map whose `basis` is empty still answers."""
    want = {p.casefold() for p in people if p}
    latest: dict[str, Mapping[str, Any]] = {}
    for m in sorted((m for m in marks if isinstance(m, Mapping)), key=lambda m: int(m.get("block") or 0)):
        who = str(m.get("who") or "").strip()
        if who and int(m.get("block") or 0) <= block and (not want or who.casefold() in want):
            latest[who.casefold()] = m
    return [{k: str(m[k]) for k in MARK_KEYS if m.get(k)} for m in latest.values()]


def props_at(scene: Mapping[str, Any], block: int) -> list[Row]:
    """The props in no hand as `block` opens (the stager's `props`, latest per prop), without one a person holds by
    then (the holding ledger)."""
    staging = _mapping(scene.get("staging"))
    latest: dict[str, Mapping[str, Any]] = {}
    for p in sorted((p for p in staging.get("props") or [] if isinstance(p, Mapping)),
                    key=lambda p: int(p.get("block") or 0)):
        if str(p.get("prop") or "").strip() and int(p.get("block") or 0) <= block:
            latest[str(p["prop"]).casefold()] = p
    held = set(holding.Ledger.of(staging.get("marks") or []).at(block))
    out = []
    for p in latest.values():
        thing = holding.thing_of(str(p["prop"]))
        if thing is None or thing.key not in held:
            out.append({k: str(p[k]) for k in ("prop", "where", "state") if p.get(k)})
    return out


def clip_of(scene: Mapping[str, Any], shot: Mapping[str, Any]) -> Mapping[str, Any]:
    """The Raphael clip this shot was written from (the same slate), {} for another planner or none."""
    slate = str(shot.get("slate") or "")
    clips = _mapping(scene.get("raphael")).get("clips") or []
    return next((c for c in clips if isinstance(c, Mapping) and slate and str(c.get("slate") or "") == slate), {})


def breakdown_of(scene: Mapping[str, Any], shot: Mapping[str, Any], clip: Mapping[str, Any]) -> Row:
    """The director's breakdown shot (`raphael_breakdown`) this shot covers: the one sharing most script blocks with
    the clip (the shot's own blocks without a clip). {} when the scene has no breakdown."""
    shots = _mapping(_mapping(scene.get("raphael")).get("breakdown")).get("shots") or []
    mine = {int(b) for b in clip.get("blocks") or [] if str(b).lstrip("-").isdigit()}
    if not mine:
        start, end = holding.window(int(shot.get("block_start") or 0), int(shot.get("block_end") or 0))
        mine = set(range(start, end))
    best, overlap = None, 0
    for b in shots:
        if not isinstance(b, Mapping):
            continue
        n = len(mine & {int(x) for x in b.get("blocks") or [] if str(x).lstrip("-").isdigit()})
        if n > overlap:
            best, overlap = b, n
    return {k: str(best[k]) for k in _BREAKDOWN_KEYS if best.get(k)} if best else {}


def shot_context(scene: Mapping[str, Any], shot: Mapping[str, Any], seen: Sequence[str],
                 names: Mapping[str, str]) -> Row:
    """What the board writer reads about a painted shot beyond its row (plan/2026-11-23c §3.1): who holds what as it
    opens (`contracts.holding`, the same words a frame gets), each seen person's stager mark, the props set down, who
    is only heard, the Raphael clip's summary and the breakdown shot it covers. `seen`: the names the camera sees;
    `names`: canon id → name. Empty fields are left out."""
    start = int(shot.get("block_start") or 0)
    marks = _mapping(scene.get("staging")).get("marks") or []
    clip = clip_of(scene, shot)
    out: Row = {
        "hands": holding.hands_for(scene, shot, list(seen)).sentence,
        "marks": marks_at(marks, start, seen),
        "props_down": props_at(scene, start),
        "heard_only": [names[str(i)] for i in _mapping(shot.get("intent")).get("heard_only") or []
                       if str(i) in names],
        "clip": {k: str(clip[k]) for k in ("summary", "over", "angle") if clip.get(k)},
        "breakdown": breakdown_of(scene, shot, clip),
    }
    return {k: v for k, v in out.items() if v}


def board_shots(scene: Mapping[str, Any], shots: Sequence[Mapping[str, Any]], lines: Sequence[Mapping[str, Any]],
                seen: Mapping[str, Sequence[str]], plates: Iterable[str],
                names: Mapping[str, str] | None = None) -> list[BoardShot]:
    """Every shot of the scene in order. `seen`: shot id → the names the camera sees; `plates`: the ids of the shots
    that are black plates (the engine's `frame_compose` decides, as it does for a frame); `names`: canon id → name,
    for who is only heard. Each painted shot's plan carries its `shot_context` (plan/2026-11-23c §3.1)."""
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
        plan: Row = {}
        if painted:
            plan = {**shot_plan(s, texts, spoken.get(sid, []), seen.get(sid, [])),
                    **shot_context(scene, s, seen.get(sid, []), names or {})}
            plan = {k: v for k, v in plan.items() if v not in ("", [], {})} | {"number": plan["number"]}
        out.append(BoardShot(id=sid, number=int(s.get("number") or 0), slate=str(s.get("slate") or ""),
                             painted=painted, text=" ".join(t for t in texts if t), plan=plan))
    return out


def colours_for(people: Sequence[str]) -> dict[str, str]:
    """name (or id) → mannequin colour, in person order."""
    return {p: COLOURS[i % len(COLOURS)] for i, p in enumerate(dict.fromkeys(people))}


def keep_colours(saved: Mapping[str, str], people: Sequence[str]) -> dict[str, str]:
    """plan/2026-11-17 §3.4: an update keeps the board's colours. `saved` (id → colour, the row's `colours`) wins; a
    person not in it gets the first colour no one on the board uses (over six, the colours repeat in order). The
    merged map keeps everyone saved, so a person who leaves and comes back keeps their colour."""
    out = {str(k): str(v) for k, v in saved.items()}
    for p in dict.fromkeys(people):
        if p in out:
            continue
        used = set(out.values())
        out[p] = next((c for c in COLOURS if c not in used), COLOURS[len(out) % len(COLOURS)])
    return out


def writer_bundle(scene: Mapping[str, Any], shots: Sequence[BoardShot], people: Sequence[Row], place: Row,
                  props: Sequence[Row], reference_labels: Sequence[str], vehicles: Sequence[Row] = ()) -> Row:
    """What the board writer reads about the scene (lab `fetch.py` bundle, without file paths). plan/2026-11-23c §3.1:
    every field the stager wrote (facing, side of frame, both hands, condition, wearing), the props it set down, its
    zones, and Raphael's whole treatment geography, colour script and key image (the axis was its first 300 letters)."""
    script = scene.get("script") or []
    staging = _mapping(scene.get("staging"))
    raphael = _mapping(scene.get("raphael"))
    treatment = _mapping(_mapping(raphael.get("edit")).get("treatment"))
    geography = str(treatment.get("geography") or "")
    out: Row = {
        "heading": scene.get("heading"), "title": scene.get("title"), "time_of_day": scene.get("time_of_day"),
        "script": [b.get("text") for b in script if isinstance(b, Mapping) and b.get("text")],
        "mood": raphael.get("mood", []),
        "geography": geography,
        "axis": "" if geography else _mapping(scene.get("coverage")).get("axis", ""),
        "colour_script": [{k: str(c[k]) for k in ("palette", "light", "grade") if c.get(k)}
                          for c in treatment.get("colour_script") or [] if isinstance(c, Mapping)],
        "key_image": str(treatment.get("key_image") or ""),
        "zones": [str(z) for z in staging.get("zones") or []],
        "staging": [{"block": int(m.get("block") or 0), **{k: str(m[k]) for k in MARK_KEYS if m.get(k)}}
                    for m in staging.get("marks") or [] if isinstance(m, Mapping)],
        "props_set_down": [{k: p[k] for k in ("block", "prop", "where", "state") if p.get(k) not in (None, "")}
                           for p in staging.get("props") or [] if isinstance(p, Mapping)],
    }
    return {
        "scene": {k: v for k, v in out.items() if v not in ("", [], None)},
        "people": list(people), "place": place, "props": list(props),
        # plan/2026-11-24b §2.3: each vehicle's name, make, look and its role and `where` per shot
        **({"vehicles": list(vehicles)} if vehicles else {}),
        "shots": [s.plan for s in shots if s.painted],
        "reference_pictures": [f"image {i}: {label}" for i, label in enumerate(reference_labels, 1)],
    }


def mannequin_note(colours: Mapping[str, str]) -> str:
    """What the writer is told about the mannequins (lab `run.py mannequin_note`)."""
    named = ", ".join(f"{n} = the {c} mannequin" for n, c in colours.items())
    return ("MANNEQUIN BOARD. Every person is painted as a smooth, faceless, colour-coded artist's mannequin, at the "
            f"person's height and build: {named}. So describe each person ONLY by their mannequin's pose: where the "
            "body sits or stands, which way the chest faces, which way the head turns, where each hand is, what it "
            "holds or touches. Never describe a face, expression, mouth, eyes, hair, skin or clothes. The place and "
            "the light are described and painted for real. PROPS ARE STAND-INS too (plan/2026-11-23c): every prop (a "
            "phone, a bag, an umbrella) is painted as a plain matte white clay stand-in of its real size and "
            "outline, so write it as \"the clay <its name>\" (the clay phone, the clay umbrella) with "
            "the hand that grips it or the surface it rests on; never its colour, screen, brand or lettering. The "
            "place and its spots stay real, even a vehicle the place is built around (a food cart). A VEHICLE IS "
            "NEVER CLAY (plan/2026-11-24b): every vehicle in `vehicles` is painted real, exactly as its vehicle "
            "picture shows it; describe it by its make and colour as that picture and its card show them: in a "
            "panel whose shot is INSIDE it, it is the place; in the others it stands where its `where` says. A "
            "person shown INSIDE a photograph, poster or screen in the scene is not a mannequin: describe that "
            "picture as a real photograph. For each panel also list, in `people`, every person the panel shows with "
            "their STATE at the opening of the shot (eyes open or closed, still, asleep, crying, breathing hard; empty "
            "when nothing is notable; the state is never drawn on the board, it is carried to the first frame) and "
            "what their `left_hand` and `right_hand` hold or do (\"the clay phone\", \"empty, at her side\"); and in "
            "`props` every prop the panel shows: who holds it and in which hand, or what it rests on, and its side "
            "of the picture.")


def writer_message(bundle: Mapping[str, Any], colours: Mapping[str, str], *,
                   repaint: Mapping[int, str] | None = None, edit: Edit | None = None) -> str:
    """The writer's user message (lab `writer_input` + the mannequin note). `repaint`: shot number → the person's
    note, carried into a whole repaint (the notes of other panels are never sent). `edit`: ONE panel for an approved
    board (plan/2026-11-17): the fixed board, the shot's plan, the pictures, the mannequin note with the board's saved
    colours and, last, `ONE_PANEL`; `bundle` is not read."""
    if edit is not None:
        return _edit_message(edit, colours)
    n = len(bundle["shots"])
    # No grid here (plan/2026-11-22): the board may be painted in parts, each with a grid of its own, and code writes
    # every panel's row and column into the image prompt.
    text = (f"<scene>\n{json.dumps(bundle, ensure_ascii=False, indent=1)}\n</scene>\n\n"
            f"Write the storyboard: {n} panels, one per shot in shot order. "
            "The reference pictures follow, in the same order as `reference_pictures`.\n\n" + mannequin_note(colours))
    if repaint:
        notes = "\n".join(f"- shot {k}: {v}" if v else f"- shot {k}" for k, v in sorted(repaint.items()))
        text += ("\n\nREPAINT. Only these panels are being painted again; the others stay as they are. Write every "
                 "panel as usual, but take particular care with these, and follow the person's note where there is "
                 f"one:\n{notes}")
    return text


# plan/2026-11-17 §3.2: the one-panel instructions (lab/panel_edit `prompt/one_panel.md`). They go at the END of the
# user message, so the writer's system prompt stays byte for byte the same (and cached) for boards and panels.
ONE_PANEL = (
    "ONE PANEL. This time the storyboard already exists and has been approved. You are NOT writing a new board: you "
    "write ONE panel for ONE shot that was added to the scene or whose plan changed. Every other panel stays exactly "
    "as it was painted, so the new panel must fit among them.\n\n"
    "- The `world` and `geography` you are given are FIXED: the approved board was painted with them. Do not restate, "
    "improve or contradict them. Your panel lives inside them: the same place, light, weather, props and mannequin "
    "colours.\n"
    "- The other panels' text is given in shot order, and the panels just before and after this one are attached as "
    "pictures. Hold the continuity they set: where each person stands, which way they face, what they hold, which "
    "side of frame the place's fixed landmarks are on for the same camera setup. Every rule above (geography as a "
    "path, same setup same side, camera and body agree, close-ups off the lens, screen direction) applies between "
    "your panel and its neighbours.\n"
    "- If the new plan cannot be painted without breaking what a neighbouring panel shows (a prop already in a hand, "
    "a person already gone), follow the plan and say so in `conflicts`. Never change another panel.\n"
    "- Answer with this one panel only: `panels` holds it alone, with its shot number; leave `world` and `geography` "
    "empty.")


@dataclass
class Edit:
    """One panel to write for an approved board (plan/2026-11-17 §3.2). `board` is the approved board as it stands,
    its panels numbered as the scene's shots stand now; `kind` "add" (a new shot, no panel yet) or "change" (its old
    panel is marked `being_replaced`). `before` / `after`: the neighbouring shots' numbers whose panels are attached
    (None at the scene's ends); `pictures`: the labels of the attached pictures, in order."""

    kind: str
    number: int
    plan: Row
    board: Writer
    pictures: list[str] = field(default_factory=list)
    before: int | None = None
    after: int | None = None
    note: str = ""


def writer_neighbour_label(side: str, number: int) -> str:
    """How the writer is told about an attached neighbouring panel (lab `writer_request`)."""
    return f"panel {number} of the approved board (just {side} this one)"


def _edit_message(edit: Edit, colours: Mapping[str, str]) -> str:
    board = edit.board.dump()
    board.pop("conflicts", None)
    n = edit.number
    if edit.kind == "add":
        around = " and ".join(f"shot {x}" for x in (edit.before, edit.after) if x is not None)
        task = (f"ADD. Shot {n} is a new shot" + (f", between {around}" if edit.before and edit.after else
                                                   (f", next to {around}" if around else "")) +
                ". Write its panel. The approved panels are numbered as the scene's shots stand now; the new shot's "
                "plan is below.")
    else:
        for p in board["panels"]:
            if p["shot"] == n:
                p["being_replaced"] = True
        task = (f"CHANGE. Shot {n}'s plan changed. Write panel {n} again from the new plan below; its old text is "
                "marked `being_replaced` and is shown only so you know what the neighbours were painted next to.")
    if edit.note:
        task += f" The person's note for this panel: {edit.note}"
    listing = "\n".join(f"image {i}: {label}" for i, label in enumerate(edit.pictures, 1))
    pictures = f"The pictures follow, in this order:\n{listing}\n\n" if listing else ""
    return (f"<approved_board>\n{json.dumps(board, ensure_ascii=False, indent=1)}\n</approved_board>\n\n"
            f"<shot>\n{json.dumps(edit.plan, ensure_ascii=False, indent=1)}\n</shot>\n\n{task}\n\n"
            f"{pictures}{mannequin_note(colours)}\n\n{ONE_PANEL}")


def panel_answer(raw: Mapping[str, Any], number: int) -> Panel | None:
    """The one panel of a one-panel answer, numbered as the shot is now (the writer's own number is not trusted).
    `world` and `geography` of the answer are ignored: the board's are fixed."""
    panels = Writer.of(raw).panels
    if not panels:
        return None
    p = next((x for x in panels if x.shot == number), panels[0])
    return replace(p, shot=number)


# ── the writer's answer ─────────────────────────────────────────────────────────────────────


@dataclass
class PanelPerson:
    name: str
    state: str = ""
    left_hand: str = ""  # plan/2026-11-23c: what the left hand holds or does ("the clay phone", "empty, at her side")
    right_hand: str = ""


@dataclass
class PanelProp:
    """A prop a panel shows (plan/2026-11-23c), painted as a white clay stand-in: who holds it and in which hand, or
    what it rests on."""

    name: str
    held_by: str = ""  # a person's name, "" when it rests
    hand: str = ""  # left | right | both | "" (worn, or resting)
    rests_on: str = ""  # the surface, when nobody holds it
    frame_side: str = ""  # left | right | centre


@dataclass
class Panel:
    shot: int  # the shot NUMBER
    zone: str
    camera: str
    background: str
    picture: str
    people: list[PanelPerson] = field(default_factory=list)
    props: list[PanelProp] = field(default_factory=list)
    view: int = 0  # plan/2026-11-24: the location sheet's view its background comes from; 0 = none named


def _person_dump(x: PanelPerson) -> Row:
    out: Row = {"name": x.name, "state": x.state}
    if x.left_hand or x.right_hand:
        out.update(left_hand=x.left_hand, right_hand=x.right_hand)
    return out


def _prop_dump(x: PanelProp) -> Row:
    return {"name": x.name, "held_by": x.held_by, "hand": x.hand, "rests_on": x.rests_on, "frame_side": x.frame_side}


def panel_dump(p: Panel) -> Row:
    out: Row = {"shot": p.shot, "zone": p.zone, "camera": p.camera, "background": p.background,
                "picture": p.picture, "people": [_person_dump(x) for x in p.people]}
    if p.props:  # a board painted before plan/2026-11-23c is stored as it was
        out["props"] = [_prop_dump(x) for x in p.props]
    if p.view:  # plan/2026-11-24
        out["view"] = p.view
    return out


def _panel_of(p: Mapping[str, Any]) -> Panel:
    return Panel(shot=int(p.get("shot") or 0), zone=_clean(p.get("zone")), camera=_clean(p.get("camera")),
                 background=_clean(p.get("background")), picture=_clean(p.get("picture")),
                 people=[PanelPerson(name=_clean(x.get("name")), state=_clean(x.get("state")),
                                     left_hand=_clean(x.get("left_hand")), right_hand=_clean(x.get("right_hand")))
                         for x in p.get("people") or [] if isinstance(x, Mapping)],
                 props=[PanelProp(name=_clean(x.get("name")), held_by=_clean(x.get("held_by")),
                                  hand=_clean(x.get("hand")).lower(), rests_on=_clean(x.get("rests_on")),
                                  frame_side=_clean(x.get("frame_side")).lower())
                        for x in p.get("props") or [] if isinstance(x, Mapping) and _clean(x.get("name"))],
                 view=_int(p.get("view")))


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class Writer:
    world: str
    geography: str
    panels: list[Panel]
    conflicts: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> Writer:
        panels = [_panel_of(p) for p in raw.get("panels") or [] if isinstance(p, Mapping)]
        return cls(world=_clean(raw.get("world")), geography=_clean(raw.get("geography")), panels=panels,
                   conflicts=[_clean(c) for c in raw.get("conflicts") or [] if _clean(c)])

    def dump(self) -> Row:
        return {"world": self.world, "geography": self.geography, "conflicts": self.conflicts,
                "panels": [panel_dump(p) for p in self.panels]}

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
            "only the mannequin colour. The place, the light and the weather are a real, photorealistic film still.")


# plan/2026-11-23c D2, D4, D5: props are stand-ins as people are mannequins. White, never grey: an unnamed grey figure
# is a background person (`STAND_INS`).
def prop_line(props: Sequence[str], places: Sequence[str] = ()) -> str:
    """What the image model is told about the props: plain white clay stand-ins of their real size and outline.
    `places`: the canon places the panels show (the location, its spots, a place built around a vehicle such as a food
    three-wheeler), which stay real (2026-11-23: the food three-wheeler came out as a white clay van)."""
    named = f" ({', '.join(dict.fromkeys(p for p in props if p))})" if any(props) else ""
    real = ", ".join(dict.fromkeys(p for p in places if p))
    # plan/2026-11-24b: the clay-vehicle sentence is the lab's `CLAY_NEW` (lab/vehicle_role: scene 4's white van)
    return ("Props (every panel): every prop" + named + " and every small thing a person holds or carries is a plain, "
            "smooth, matte white clay stand-in of the real object: its real size and outline, and nothing else: no "
            "screen, buttons, logo, lettering, pattern or colour. " + vehicles_kit.CLAY_NEW + " Each stand-in is "
            "held, carried or set down exactly "
            "as the real thing would be. The place itself is real: its ground, walls, water, plants, what is built "
            "into it" + (f", and {real}" if real else "") + ", painted as a real photograph, never as clay.")


# plan/2026-11-23c §3.2: the faults of the board of 2026-11-23 (an umbrella held by nothing, a third arm, a foot over a
# drain), as a rule for every panel.
SUPPORT = ("Bodies and things (every panel): every mannequin has exactly two arms and two hands, each hand where the "
           "panel says. A held stand-in is gripped by the hand the panel names, its handle or edge inside the closed "
           "fingers; nothing hangs or floats in the air. Feet stand flat on the ground the panel names. A bag hangs "
           "from the shoulder or forearm the panel names.")


def _bare(name: str) -> str:
    """A prop's name without "the" or "clay" in front."""
    return re.sub(r"^(?:the |a |an )?(?:white )?(?:clay )?", "", name.strip(), flags=re.IGNORECASE)


def hands_text(panel: Panel, colours: Mapping[str, str]) -> str:
    """The panel's hands and set-down props in the image model's words (the mannequin colours): "Hands: the blue
    mannequin: left hand the clay umbrella's handle; right hand empty. The clay bag rests on the bench." "" when the
    writer gave none (a board painted before plan/2026-11-23c)."""
    def who(name: str) -> str:
        return f"the {colours[name]} mannequin" if name in colours else name

    bits = [f"{who(x.name)}: left hand {x.left_hand.rstrip('.') or 'empty'}; right hand "
            f"{x.right_hand.rstrip('.') or 'empty'}" for x in panel.people if x.left_hand or x.right_hand]
    bits += [f"the clay {_bare(x.name)} rests on {x.rests_on.rstrip('.')}" for x in panel.props
             if not x.held_by and x.rests_on]
    return ("Hands: " + ". ".join(bits) + ".") if bits else ""


def views_paragraph(labels: Sequence[str], views: Sequence[Mapping[str, Any]]) -> str:
    """The references paragraph of a board painted against a location's views sheet (lab/location_views run_002,
    `board_prompt`). The sheet's label carries its views' names, numbered left to right, then top to bottom. Changed
    from the lab, said: "its buildings, the food three-wheeler, the wall, the pavement and the drain" is "its
    buildings, its fixed things and every place that stands in it" (the lab's words named one place)."""
    names = "; ".join(f"view {v['n']} {v['name']}" for v in views)
    cite = []
    for i, label in enumerate(labels, 1):
        cite.append(f"image {i} is {label}, numbered left to right, then top to bottom: {names}"
                    if label.startswith(VIEWS_LABEL_HEAD) else f"image {i} is {label}")
    sheet = next(i for i, label in enumerate(labels, 1) if label.startswith(VIEWS_LABEL_HEAD))
    jobs = "; ".join(f"image {i}: {job}" for i, label in enumerate(labels, 1)
                     if not label.startswith(VIEWS_LABEL_HEAD) and (job := board_job(label)))
    return (f"Reference images, in order: {'; '.join(cite)}. Take from image {sheet} the place itself: its buildings, "
            "its fixed things and every place that stands in it, their materials and where each one stands. Every "
            "panel below names the view its background comes from: paint that view's background, the same things on "
            "the same sides, seen from the panel's own camera (closer or tighter as the panel says). Never copy the "
            "sheet's gutters or layout." + (f" Take from {jobs}." if jobs else ""))


def panel_view(panel: Panel, views: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The view of the sheet the panel names, or None."""
    return next((v for v in views if int(v.get("n") or 0) == panel.view), None) if panel.view else None


def view_named(view: Mapping[str, Any]) -> str:
    """A view with its key words (plan/2026-11-24c §2.7): "view 4 (Reverse): the road and the far side, the frontage
    out of frame", so the painter knows what the view shows and what it does not."""
    said = view_key_words(view)
    return f"view {view['n']} ({view['name']})" + (f": {said}" if said else "")


def views_of(panel: Panel, views: Sequence[Mapping[str, Any]],
             panel_views: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> Sequence[Mapping[str, Any]]:
    """The views a panel's `view` counts in: its own sheet's (plan/2026-11-24b §5: a panel INSIDE a vehicle with a
    views sheet names that vehicle's view), else the place's."""
    return (panel_views or {}).get(panel.shot, views)


def view_line(panel: Panel, views: Sequence[Mapping[str, Any]]) -> str:
    """ " Background view: view 4 (Reverse): the road and the far side, the frontage out of frame." (lab
    `board_prompt`, with the view's key words of plan/2026-11-24c §2.7), "" when the panel names no view of the
    sheet."""
    view = panel_view(panel, views)
    return f" Background view: {view_named(view)}." if view else ""


def board_job(label: str) -> str:
    """What the board takes from one attached picture. The board has only the place plate, prop sheets and, on a
    later part, the overlap panel: never a face or a look sheet (it has no faces)."""
    if label.startswith("the location plate for "):
        return _PLACE_JOB
    if label.startswith((vehicles_kit.PLATE_HEAD, vehicles_kit.SHEET_HEAD)):  # plan/2026-11-24b §2.3
        return vehicles_kit.job("at", board=True)
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


# plan/2026-11-22 (lab/board_grid run.py `no_leak`, unchanged): the writer used to name a grid of its own in `world`
# ("a four-column, four-row grid ... fill the first fourteen cells"), told the whole scene's layout, and every part's
# prompt then asked for two grids. A sentence that names a layout AND the sheet is dropped; the head sentence alone
# decides the grid.
_LAYOUT = re.compile(r"grid|columns?\b|across|\bdown\b|cells?\b|panels? in shot order", re.I)
_SHEETY = re.compile(r"storyboard|panel|cell|grid", re.I)


def board_layout_free(world: str) -> str:
    """The World paragraph without the writer's sentences about the sheet's layout."""
    kept = [s for s in re.split(r"(?<=\.)\s+", world) if not (_LAYOUT.search(s) and _SHEETY.search(s))]
    return " ".join(kept)


def board_prompt(writer: Writer, numbers: Sequence[int], labels: Sequence[str], colours: Mapping[str, str],
                 aspect: str = BOARD_ASPECT, props: Sequence[str] = (), places: Sequence[str] = (),
                 views: Sequence[Mapping[str, Any]] = (), vehicles: str = "",
                 panel_views: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> str:
    """The image prompt for one board (or one part): the panels of `numbers`, in order (lab `board_prompt` with
    mannequins). `labels` are the attached pictures in order; `colours`: name → colour; `aspect`: the board's shape
    (`board_aspect`), which every panel takes; `props`: the canon props the panels show, painted as white clay
    stand-ins (plan/2026-11-23c)."""
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
        hands = hands_text(p, colours)
        pos.append(f"PANEL {i + 1} (row {r + 1}, column {c + 1}) — {p.camera.rstrip('.')}. Background: "
                   f"{p.background.rstrip('.')}. {p.picture}" + (f" {hands}" if hands else "")
                   + view_line(p, views_of(p, views, panel_views)))
    head = (f"A cinematic storyboard sheet for a Sri Lankan television drama: {n} photorealistic film stills of ONE "
            f"scene, laid out in a grid {cols} panels across and {rows} down, read {order}. Every panel is "
            f"{_PANEL_SHAPE[board_aspect(aspect)]} of the same size, separated by thin, even, plain white gutters. "
            "All panels are the same "
            "scene's world, painted together: the same people, props, light and colour grade in every panel. The "
            "weather and the ground (dry or wet, rain falling or not) are as each panel says: they can change during "
            "the scene, and a panel that says it is dry has no rain and no wet ground.")
    refs = (f"Reference images, in order: {cite}." + (f" Take from {jobs}." if jobs else "")) if labels else ""
    if views and any(label.startswith(VIEWS_LABEL_HEAD) for label in labels):  # plan/2026-11-24
        refs = views_paragraph(labels, views)
    return "\n\n".join(x for x in [
        head, refs, mannequin_line(colours), prop_line(props, places),
        "World (every panel): " + board_layout_free(board_world(writer.world, colours)),
        vehicles,  # plan/2026-11-24b §2.3: the lab's vehicles line, before Geography
        "Geography: " + writer.geography,
        "\n".join(pos), BODIES, SUPPORT, NO_TEXT,
    ] if x)


# ── one panel painted on its own (plan/2026-11-17 §3.2, lab/panel_edit run_002) ─────────────────────────────

# run_002: without it, run_001's over-the-shoulder put the camera BESIDE the customer.
CAMERA_RULE = ("The camera stands exactly where the panel says, and what is nearest the lens is what the panel puts "
               "nearest. When the camera is behind or past someone's shoulder, that person's back and shoulder are "
               "large in the near foreground, cut by the frame edge, and everything else is seen beyond them.")
_ONE_SHAPE = {BOARD_ASPECT: "wide landscape 16:9", TALL: "tall portrait 9:16"}
NEIGHBOURS = ("The approved storyboard panels attached last sit next to this one on the same board. Paint this panel "
              "so it sits beside them unnoticed: the same mannequins in the same colours and finish, the same place, "
              "props, light, colour grade and level of detail. The weather and the ground are as this panel says, "
              "even where a neighbour's differ (rain can start or stop during a scene). Do not copy their framing: "
              "this panel has its own camera, described below.")
_SHEET_WORDS = ("panel", "gutter", "grid", "storyboard image", "sheet")


def neighbour_label(side: str, number: int) -> str:
    """How the image model is told about an attached neighbouring panel (`side`: before | after)."""
    return f"the approved storyboard panel just {side} this one (shot {number})"


def is_neighbour(label: str) -> bool:
    return label.startswith("the approved storyboard panel just ")


def panel_world(world: str) -> str:
    """The board's world without its sentences about the SHEET ("six equal portrait panels ... gutters"): they
    contradict a picture of one panel (the board writer puts layout into `world`; lab `solo_world`)."""
    return " ".join(x for x in _SENTENCES.split(world.strip()) if not any(w in x.lower() for w in _SHEET_WORDS))


def panel_prompt(writer: Writer, panel: Panel, labels: Sequence[str], colours: Mapping[str, str],
                 aspect: str = BOARD_ASPECT, props: Sequence[str] = (), fix: str = "",
                 places: Sequence[str] = (), views: Sequence[Mapping[str, Any]] = (), vehicles: str = "",
                 panel_views: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> str:
    """The image prompt for ONE panel painted alone, filling the picture (lab `solo_prompt` + `CAMERA_RULE`).
    `labels`: the attached pictures in order (the place, then the neighbouring panels, `neighbour_label`);
    `writer`: the approved board (its world and geography); `aspect`: the board's shape, so the panel matches;
    `props`: the canon props, as white clay stand-ins; `fix`: `fix_line` when the panel is painted again after the
    board check found a fault (plan/2026-11-23c F2)."""
    hands = hands_text(panel, colours)
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(labels, 1))
    jobs = "; ".join(f"image {i}: {job}" for i, label in enumerate(labels, 1) if (job := board_job(label)))
    refs = (f"Reference images, in order: {cite}." + (f" Take from {jobs}." if jobs else "")) if labels else ""
    if views and any(label.startswith(VIEWS_LABEL_HEAD) for label in labels):  # plan/2026-11-24
        refs = views_paragraph(labels, views)
    return "\n\n".join(x for x in [
        "ONE photorealistic film still for the storyboard of a Sri Lankan television drama: a single "
        f"{_ONE_SHAPE[board_aspect(aspect)]} panel filling the whole picture, with no gutters, no border and no other "
        "panels.",
        refs,
        NEIGHBOURS if any(is_neighbour(x) for x in labels) else "",
        CAMERA_RULE,
        mannequin_line(colours), prop_line(props, places),
        "World: " + panel_world(board_world(writer.world, colours)),
        vehicles,  # plan/2026-11-24b §2.3
        "Geography: " + writer.geography,
        f"THE PANEL — {panel.camera.rstrip('.')}. Background: {panel.background.rstrip('.')}. {panel.picture}"
        + (f" {hands}" if hands else "") + view_line(panel, views_of(panel, views, panel_views)),
        BODIES, SUPPORT, fix, NO_TEXT.replace("no borders other than the gutters", "no borders, no gutters"),
    ] if x)


def fix_line(problems: Sequence[str], view: str = "") -> str:
    """What a panel painted again is told about its first painting's faults (plan/2026-11-23c F2). `view`: the
    panel's view (`view_named`) when the check found its background showing another view (plan/2026-11-24c §2.7)."""
    said = "; ".join(" ".join(str(p).split()).rstrip(".") for p in problems if str(p).strip())
    return ("A first painting of this panel was wrong" + (f": {said}." if said else ".") + " Paint it again "
            "without that fault: two arms and two hands on every mannequin, every held thing gripped by its hand, "
            "both feet on the ground"
            + (f"; the background is {view}, its things on its sides" if view else "") + ".") if said else ""


# ── the free check of the writer's answer (plan/2026-11-23c §3.4) ──────────────────────────────────────────────


_CLAY_THING = re.compile(r"\bclay\s+([a-z][a-z-]*)", re.IGNORECASE)  # one word: it is looked up in the plan text
_NOT_A_THING = re.compile(r"\b(?:stand-ins?|shapes?|objects?)\b", re.IGNORECASE)


def _held(text: str) -> str:
    """The thing a hand holds, read only from the writer's stand-in words ("grips the clay phone around its lower
    edges" → "phone"; 2026-11-23: the whole sentence was read and "edges" came out as a thing). "" when the hand holds
    no clay thing (empty, at a side, on a counter)."""
    m = _CLAY_THING.search(str(text or ""))
    if m is None:
        return ""
    words = _NOT_A_THING.sub("", re.split(r"['’]s\b", m.group(1))[0]).strip()
    thing = holding.thing_of(words)
    return thing.key if thing is not None else ""


def writer_findings(writer: Writer, shots: Sequence[BoardShot], carried: Mapping[str, str] | None = None,
                    views: Sequence[Mapping[str, Any]] = (),
                    panel_views: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> list[str]:
    """What code finds wrong in the writer's panels before anything is painted, as conflict lines: more than two
    things in a person's hands (a worn bag is not in a hand), a prop neither held nor resting on anything, someone
    only heard on the board, and a held thing that neither the shot's plan nor what the person carries through the
    scene gives them. `carried`: person name → their scene condition and look accessories (an open umbrella in the
    rain continues from the scene before). Never a model call."""
    plans = {s.number: s.plan for s in shots if s.painted}
    out: list[str] = []
    for p in writer.panels:
        plan = plans.get(p.shot)
        if plan is None:
            continue
        said = json.dumps(plan, ensure_ascii=False).lower()
        for x in p.people:
            hands = [h for h in (_held(x.left_hand), _held(x.right_hand)) if h]
            more = {_held(f"clay {pr.name}") for pr in p.props
                    if pr.held_by.casefold() == x.name.casefold() and pr.hand in ("left", "right", "both")}
            things = list(dict.fromkeys([*hands, *(m for m in more if m)]))
            if len(things) > 2:
                out.append(f"Shot {p.shot}: {x.name} is given {len(things)} things to hold ({', '.join(things)}); "
                           "a person has two hands.")
            mine = f"{said} {str((carried or {}).get(x.name) or '').lower()}"
            for key in things:
                if key not in mine:
                    out.append(f"Shot {p.shot}: {x.name} holds the {key}, which neither the plan of this shot nor "
                               "what they carry through the scene gives them.")
        sheet = views_of(p, views, panel_views)
        if sheet and p.view and not any(int(v.get("n") or 0) == p.view for v in sheet):  # plan/2026-11-24
            out.append(f"Shot {p.shot}: names view {p.view}, which the location sheet does not have.")
        for pr in p.props:
            if not pr.held_by and not pr.rests_on:
                out.append(f"Shot {p.shot}: the {_bare(pr.name)} is neither held nor resting on anything.")
        heard = {h.casefold() for h in plan.get("heard_only") or []}
        for x in p.people:
            if x.name.casefold() in heard:
                out.append(f"Shot {p.shot}: {x.name} is only heard in this shot but is on the board.")
    return list(dict.fromkeys(out))


# ── cells, pins and out of date ─────────────────────────────────────────────────────────────

# The parts of a shot row the writer reads: when one changes, its panel no longer shows the shot.
_PIN_IR = ("setting", "first_frame", "subjects", "cinematography", "lighting", "beats")
_PIN_INTENT = ("story", "purpose", "on_screen")


# plan/2026-11-23c D7: the writer now also reads the opening state and who is only heard ("v2:"); plan/2026-11-23d
# §2.2: and the Camera agent's camera ("v3:"). A cell is compared in the version it was pinned in, so a painted board
# stays current until its shot really changes; a cell pinned before versions has no prefix.
PIN_VERSION = "v3"
_PIN_INTENT_V2 = (*_PIN_INTENT, "opens", "heard_only")


def _pin_hash(shot: Mapping[str, Any], intent_keys: Sequence[str], camera: bool = False) -> str:
    ir, intent = _mapping(shot.get("ir")), _mapping(shot.get("intent"))
    body: Row = {"framing": shot.get("framing") or "", "blocks": [shot.get("block_start"), shot.get("block_end")],
                 "ir": {k: ir.get(k) for k in _PIN_IR}, "intent": {k: intent.get(k) for k in intent_keys}}
    if camera:
        body["camera"] = camera_of(shot)
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def plan_pin(shot: Mapping[str, Any]) -> str:
    """What a panel was painted against: a hash of the shot's plan fields the writer read (its size, its blocks, the
    IR's picture fields, the intent's story, purpose, who is seen and heard, the opening state, and the Camera agent's
    camera). Its number is not in it: a move is a change of the board's order (`Stale.order`), not of the panel."""
    return f"{PIN_VERSION}:{_pin_hash(shot, _PIN_INTENT_V2, camera=True)}"


def legacy_pin(shot: Mapping[str, Any]) -> str:
    """The pin a cell painted before plan/2026-11-23c carries."""
    return _pin_hash(shot, _PIN_INTENT)


def pin_matches(pin: str, shot: Mapping[str, Any]) -> bool:
    """The cell's pin still shows the shot: compared in the version it was made in."""
    if pin.startswith(f"{PIN_VERSION}:"):
        return pin == plan_pin(shot)
    if pin.startswith("v2:"):
        return pin == f"v2:{_pin_hash(shot, _PIN_INTENT_V2)}"
    return pin == legacy_pin(shot)


def new_cell(shot: BoardShot, shot_row: Mapping[str, Any], panel: int | None, source: str = "sheet") -> Row:
    """A cell of a board: a painted panel or a black plate. `source` "sheet": cut from a grid picture (`panel` its
    1-based place in it, `box` its crop); "panel": a picture of its own, painted alone (plan/2026-11-17 §3.2). Every
    cell is pinned to its shot's plan, a black plate too (so a plate that becomes a painted shot is seen)."""
    return {"shot_id": shot.id, "number": shot.number, "kind": "painted" if shot.painted else "black",
            "panel": panel, "box": None, "path": None, "pin": plan_pin(shot_row), "source": source,
            "text": "" if shot.painted else shot.text[:300], "locked": False, "note": ""}


@dataclass
class Stale:
    """Why a board no longer shows the scene (plan/2026-11-17 §3.1). Numbers are the shots' numbers NOW (a removed
    shot's, its number on the board). `paint`: shot ids an update paints (changed or added, never a locked panel);
    `tidy`: shot ids whose cells an update drops or moves. `whole` is set by the caller: only a whole repaint can mend
    the board (none painted, a part failed, or the board is in the wrong shape)."""

    changed: list[int] = field(default_factory=list)  # panels (or black plates) whose shot changed
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    moved: list[int] = field(default_factory=list)
    locked: list[int] = field(default_factory=list)  # changed, but the panel is locked: left as it is
    paint: list[str] = field(default_factory=list)
    tidy: list[str] = field(default_factory=list)
    whole: bool = False

    @property
    def order(self) -> bool:
        return bool(self.moved)

    @property
    def any(self) -> bool:
        return self.whole or bool(self.changed or self.added or self.removed or self.moved)

    @property
    def updatable(self) -> bool:
        """Something an update can mend (a locked panel alone is not)."""
        return not self.whole and bool(self.paint or self.tidy)

    def reasons(self) -> list[str]:
        out = []
        free = [n for n in self.changed if n not in self.locked]
        if free:
            out.append(f"{shots_phrase(free)} changed")
        if self.added:
            out.append(f"{shots_phrase(self.added)} added")
        if self.removed:
            out.append(f"the board's {shots_phrase(self.removed)} removed")  # its number on the board, not now
        if self.moved:
            out.append("the shots were reordered")
        if self.locked:
            verb = "is" if len(self.locked) == 1 else "are"
            out.append(f"{shots_phrase(self.locked)} {verb} locked and out of date: unlock to update")
        return out

    def items(self) -> list[tuple[int, str]]:
        """(shot number, what an update does to it) in number order: changed | added | removed | moved | locked."""
        out = [(n, "locked" if n in self.locked else "changed") for n in self.changed]
        out += [(n, "added") for n in self.added] + [(n, "removed") for n in self.removed]
        out += [(n, "moved") for n in self.moved if n not in self.changed]
        return sorted(out)


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
    locked = {str(c.get("shot_id")) for c in cells if c.get("locked")}
    out = Stale()
    changed_ids: list[str] = []
    for sid, c in seen.items():
        s = by_id.get(sid)
        if s is None:
            out.removed.append(int(c.get("number") or 0))
            out.tidy.append(sid)
        elif c.get("pin") and not pin_matches(str(c["pin"]), s):
            out.changed.append(int(s.get("number") or 0))
            if sid in locked:
                out.locked.append(int(s.get("number") or 0))
            else:
                changed_ids.append(sid)
    ordered = sorted(shots, key=lambda r: int(r.get("number") or 0))
    out.added = [int(s.get("number") or 0) for s in ordered if str(s["id"]) not in seen]
    board_order = [sid for sid in seen if sid in by_id]
    now_order = [str(s["id"]) for s in ordered if str(s["id"]) in seen]
    if board_order != now_order:  # every shot whose place among the others is not the board's
        out.moved = sorted(int(by_id[sid].get("number") or 0) for i, sid in enumerate(now_order)
                           if board_order[i] != sid)
        out.tidy += [sid for i, sid in enumerate(now_order) if board_order[i] != sid]
    want = set(changed_ids) | {str(s["id"]) for s in ordered if str(s["id"]) not in seen}
    out.paint = [str(s["id"]) for s in ordered if str(s["id"]) in want]
    out.changed.sort()
    out.locked.sort()
    return out


# ── an update's pure steps (plan/2026-11-17 §3.4-3.6) ───────────────────────────────────────────────────────────


def renumber(cells: Sequence[Mapping[str, Any]], writer: Writer, shots: Sequence[Mapping[str, Any]]
             ) -> tuple[list[Row], Writer]:
    """Every cell's `number` and every writer panel's `shot` set from the scene's shots as they stand, in one step:
    a frame reads its panel's words by NUMBER (`frame_sections`), so the two always move together. `cells`: every
    part's cells (the map from a panel's old number to its shot comes from them). A cell whose shot is gone keeps its
    number (an update drops it); a writer panel whose shot is gone, or that no cell names, is dropped."""
    now = {str(s["id"]): int(s.get("number") or 0) for s in shots}
    by_old: dict[int, str] = {}
    for c in cells:
        by_old.setdefault(int(c.get("number") or 0), str(c.get("shot_id")))
    out = []
    for c in cells:
        sid = str(c.get("shot_id"))
        out.append({**c, "number": now[sid]} if sid in now else dict(c))
    panels = []
    for p in writer.panels:
        owner = by_old.get(p.shot)
        if owner is not None and owner in now:
            panels.append(replace(p, shot=now[owner], people=list(p.people), props=list(p.props)))
    panels.sort(key=lambda p: p.shot)
    return out, Writer(world=writer.world, geography=writer.geography, panels=panels,
                       conflicts=list(writer.conflicts))


def insert_position(parts: Sequence[Sequence[Mapping[str, Any]]], shots: Sequence[Mapping[str, Any]],
                    shot_id: str) -> int:
    """The part (0-based) an added shot joins: the one that holds the nearest shot before it, the first part for a
    new first shot. A part may grow past `PART_SIZE`: an updated part is never painted as a grid (§3.5)."""
    ordered = [str(s["id"]) for s in sorted(shots, key=lambda r: int(r.get("number") or 0))]
    if shot_id not in ordered:
        return 0
    for sid in reversed(ordered[: ordered.index(shot_id)]):
        for i, cells in enumerate(parts):
            if any(str(c.get("shot_id")) == sid for c in cells):
                return i
    return 0


def previous_for(cell: Mapping[str, Any], pin: str) -> Row | None:
    """The picture this cell had when its shot's plan was `pin` (§3.6): an undo puts a plan back, and its panel comes
    back with no model call. → `{pin, path, panel}` or None."""
    if not pin:
        return None
    return next((dict(p) for p in cell.get("previous") or [] if isinstance(p, Mapping) and p.get("pin") == pin
                 and p.get("path")), None)


def remember(cell: Mapping[str, Any], panel: Panel | None) -> list[Row]:
    """The cell's `previous` with its current picture added first (at most `PREVIOUS_KEPT`, no pin twice)."""
    old = [dict(p) for p in cell.get("previous") or [] if isinstance(p, Mapping)]
    if not cell.get("path") or not cell.get("pin"):
        return old[:PREVIOUS_KEPT]
    now = {"pin": cell["pin"], "path": cell["path"], "panel": _panel_dump(panel) if panel else None}
    return [now, *(p for p in old if p.get("pin") != cell["pin"])][:PREVIOUS_KEPT]


def _panel_dump(p: Panel) -> Row:
    return panel_dump(p)


def panel_of(raw: Mapping[str, Any] | None, number: int) -> Panel | None:
    """A stored panel (`previous[].panel`) back as a Panel numbered `number`."""
    if not isinstance(raw, Mapping):
        return None
    return panel_answer({"panels": [raw]}, number)


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


# The stand-in rule (2026-11-16, lab/portrait_board run_001): without it, the board's unnamed background figures
# ("two small neutral-grey pedestrian mannequins") were painted into the first frame as grey mannequins.
STAND_INS = ("The approved draft shows people as plain mannequins: they are stand-ins for where people stand and how "
             "they hold themselves, nothing more. Every figure in it, named or not, including small grey figures in "
             "the background, is a real, clothed Sri Lankan person in this frame. Draw no mannequins, dummies, "
             "statues or faceless figures.")
# A mannequin no colour names: "two small neutral-grey pedestrian mannequins" → "two pedestrians", "a grey mannequin"
# → "a person".
_UNNAMED = re.compile(r"\b(?:(?:small|tiny|distant|faceless|plain|smooth|matte|neutral[- ]gr[ae]y|gr[ae]y|"
                      r"background)[ ,-]+)*(pedestrian )?mannequin(s?)\b", re.IGNORECASE)


def _person(m: re.Match[str]) -> str:
    if m.group(1):
        return "pedestrians" if m.group(2) else "pedestrian"
    return "people" if m.group(2) else "person"


def unmannequin(text: str, colours: Mapping[str, str]) -> str:
    """The writer's mannequin words turned back into people: "the red mannequin" → "Nimal", "red head" → "head", and
    a mannequin no colour names (a background figure) → "person" / "pedestrians"."""
    for name, c in colours.items():
        text = re.sub(rf"\bthe {c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b(smooth,? )?{c} (?=(head|hands?|arms?|body|figure|shoulders?|chest|torso|thigh|knee|"
                      r"forearm|feet|foot|legs?)\b)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmannequin's\b", "person's", re.sub(r"\bsmooth (?=head\b)", "", text))
    return _UNNAMED.sub(_person, text)


# plan/2026-11-23d (shot 1 of scene 4, 2026-11-23): the writer's World also says how the board is painted ("Render
# them without human surface details or clothing", "every portable object is its actual size and outline, without
# marking"); such a sentence must never reach a real frame.
_BOARD_WORDS = re.compile(r"\b(panels?|storyboard|grid|gutters?|mannequins?|clay|stand-ins?|faceless|surface details|"
                          r"clothing details|without (?:human|clothing|facial|faces|hair|markings?|lettering)|"
                          r"outlines?)\b", re.IGNORECASE)


# plan/2026-11-23c D2: the props' twin of `STAND_INS`.
PROP_STAND_INS = ("The approved draft shows the props as plain white clay stand-ins: they mark where each prop is, its "
                  "size, its angle and the hand that holds it, nothing more. Paint every one as the real prop from "
                  "its reference sheet, in exactly that place and hand. No white clay shape, blank object or "
                  "unfinished prop remains in the frame.")
_CLAY_OF = re.compile(r"\b(?:an? |the )?(?:(?:plain|smooth|matte|white),? )*clay stand-ins? (?:of|for) ",
                      re.IGNORECASE)
_CLAY = re.compile(r"\b(?:(?:plain|smooth|matte|white),? )*clay (?=[a-z])", re.IGNORECASE)


def unprop(text: str) -> str:
    """The writer's stand-in words turned back into the props: "the clay umbrella" → "the umbrella", "a white clay
    stand-in of the phone" → "the phone"."""
    return _CLAY.sub("", _CLAY_OF.sub("", text))


def frame_world(world: str) -> str:
    """The board's World for a frame: without its sentences about the board itself (panels, grid, gutters) or the
    mannequin treatment, which would invite a grid or a plastic figure."""
    return " ".join(x for x in _SENTENCES.split(world.strip()) if not _BOARD_WORDS.search(x))


def panel_text(panel: Panel, colours: Mapping[str, str]) -> str:
    """"This shot: <camera>. Background: <background>. <picture>" in people's names."""
    return unprop(unmannequin(f"This shot: {panel.camera.rstrip('.')}. Background: {panel.background.rstrip('.')}. "
                              f"{panel.picture}", colours))


def frame_sections(writer: Writer, number: int, colours: Mapping[str, str], opening: Sequence[str],
                   faced: Iterable[str] = (), *, blocking: bool = False) -> list[str]:
    """The paragraphs a frame painted from its panel adds to its brief, in order: the stand-in rule, the mannequins,
    the state, the scene's world and this panel. `colours`: name → colour of the people this frame shows.
    `blocking` (plan/2026-11-23d §2.2): the frame is written from its shot prompt, so the panel gives only where
    everyone stands and faces, what each hand holds, the props and the place; never its camera."""
    panel = writer.panel(number)
    if panel is None:
        return []
    clay = bool(panel.props) or "clay" in f"{writer.world} {panel.picture}".lower()
    stand_ins = STAND_INS.replace("The approved draft", "The approved scene board panel") if blocking else STAND_INS
    props = PROP_STAND_INS.replace("The approved draft", "The approved scene board panel") if blocking \
        else PROP_STAND_INS
    people = mannequin_paragraph(colours, faced)
    if blocking:
        people = people.replace("The approved draft", "The approved scene board panel").replace(
            "keeping exactly the mannequin's place in the frame, size, seated or standing pose",
            "keeping the mannequin's place among the others, which way they face, their seated or standing pose")
    hands = held_text(panel, colours)
    return [x for x in (stand_ins, props if clay else "", people,
                        state_line(opening, panel.people),
                        ("The scene: " + unprop(unmannequin(frame_world(writer.world), colours))) if writer.world
                        else "",
                        blocking_text(panel, colours) if blocking else panel_text(panel, colours),
                        hands) if x]


def blocking_text(panel: Panel, colours: Mapping[str, str]) -> str:
    """The panel without its camera, in people's names: what the frame takes when its shot prompt sets the camera."""
    return unprop(unmannequin(f"On the approved board: {panel.picture} Behind them: "
                              f"{panel.background.rstrip('.')}.", colours))


def held_text(panel: Panel, colours: Mapping[str, str]) -> str:
    """Each person's two hands as approved on the board, in people's names and real props: "Hands as approved on
    the scene board: Anudi: left hand grips the umbrella's shaft; right hand holds the phone at chest height." "" for a
    board painted before plan/2026-11-23c (no hands)."""
    bits = [f"{x.name}: left hand {x.left_hand.rstrip('.') or 'empty'}; "
            f"right hand {x.right_hand.rstrip('.') or 'empty'}" for x in panel.people if x.left_hand or x.right_hand]
    bits += [f"the {_bare(x.name)} rests on {x.rests_on.rstrip('.')}" for x in panel.props
             if not x.held_by and x.rests_on]
    return unprop(unmannequin("Hands as approved on the scene board: " + ". ".join(bits) + ".", colours)) \
        if bits else ""


# ── the approved panel of a shot, for its shot prompt and first frame (plan/2026-11-23d §2.2) ────────────────


BOARD_CHANGED = "The approved scene board changed since this shot prompt was written."
# What `writer_findings` and the board check write about a shot: a panel that breaks a fact is not attached (D2).
_FAULT_MARKS = ("things to hold", "neither the plan of this shot", "only heard in this shot",
                "neither held nor resting", "the board check still sees")


def current_parts(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The scene's current board: every part of the newest version, in part order (the API's `boards.current`)."""
    if not rows:
        return []
    top = max(int(r.get("version") or 1) for r in rows)
    return sorted((r for r in rows if int(r.get("version") or 1) == top), key=lambda r: int(r.get("part") or 1))


@dataclass
class ApprovedPanel:
    """A shot's panel on the current, approved board, still showing the shot (its pin matches)."""

    stamp: str  # "<part id>:<cell path>": what a shot prompt records it was written from
    part: Mapping[str, Any]
    cell: Mapping[str, Any]
    panel: Panel


def approved_panel(rows: Sequence[Mapping[str, Any]], shot: Mapping[str, Any]) -> ApprovedPanel | None:
    """The shot's panel when the current board's part is done and approved and the panel still shows the shot (the
    API's `shot_panel` "ready"); None otherwise (no board, painting, failed, unapproved, out of date, a black plate)."""
    owner = owner_cell(current_parts(rows), str(shot.get("id")))
    if owner is None:
        return None
    part, cell = owner
    if part.get("status") != "done" or not part.get("approved_at") or cell.get("kind") != "painted" \
            or not cell.get("path") or (cell.get("pin") and not pin_matches(str(cell["pin"]), shot)):
        return None
    panel = Writer.of(_mapping(part.get("writer"))).panel(int(cell.get("number") or 0))
    if panel is None:
        return None
    return ApprovedPanel(stamp=f"{part.get('id')}:{cell.get('path')}", part=part, cell=cell, panel=panel)


def board_reason(record: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]],
                 shot: Mapping[str, Any]) -> str:
    """D2 (plan/2026-11-23d): a shot prompt written before the board was approved, or before its panel changed, is
    out of date: the approved panel wins and the prompt is written again from it. "" when there is no approved
    panel (the prompt stands) or it was written from this one."""
    found = approved_panel(rows, shot)
    if found is None or not isinstance(record, Mapping):
        return ""
    return "" if str(record.get("board") or "") == found.stamp else BOARD_CHANGED


def panel_faults(writer: Writer, number: int) -> list[str]:
    """The board's conflict lines that code wrote about this shot's panel breaking a fact (D2): such a panel is not
    attached to the frame."""
    head = f"Shot {number}:"
    return [c for c in writer.conflicts if c.startswith(head) and any(m in c for m in _FAULT_MARKS)]


def panel_facts(panel: Panel, colours: Mapping[str, str]) -> Row:
    """What the shot prompter is told the approved board shows (plan/2026-11-23d §2.2), in people's names and real
    props: where everyone stands and faces, each person's two hands, the props resting somewhere. Never its camera."""
    people = [{"name": x.name, "left_hand": unprop(unmannequin(x.left_hand, colours)) or "empty",
               "right_hand": unprop(unmannequin(x.right_hand, colours)) or "empty"}
              for x in panel.people if x.left_hand or x.right_hand]
    return {"blocking": blocking_text(panel, colours), "hands": people,
            "props": [{"name": _bare(x.name), **({"held_by": x.held_by, "hand": x.hand} if x.held_by else {}),
                       **({"rests_on": x.rests_on} if x.rests_on else {}),
                       **({"frame_side": x.frame_side} if x.frame_side else {})} for x in panel.props]}
