"""The Scene board job (plan/2026-11-14 §3.2-3.3): ONE mannequin storyboard per scene, painted before any first frame.

    state.board_id      a whole board: the row the API created `queued` (part 1 of a new version)
    state.carry         a whole repaint: the previous version's part ids, whose notes and locked panels carry over
    state.update        true: update the current board (plan/2026-11-17, `update`): `board_ids` (every part, set
                        `queued` by the API with its approval cleared), `scene_id`, `shots` (shot ids; empty = all
                        out of date) and `approvals` (board id → the approval cleared, written back to a part none
                        of whose cells changed)

  claim     queued -> running, so a re-delivery never pays twice
  writer    `board_writer` reads the scene and every painted shot's PLAN, writes the world, the geography and a
            mannequin panel per shot (`contracts.board`)
  image     per part (D5): `board_prompt` → `safe_depiction.blocking` → `images.edit` at the row's quality (LOW by
            default, D2); a later part gets the previous part's last panel to repeat. Props are white clay stand-ins
            (plan/2026-11-23c D2): the picture gets the place plate only, the writer still reads the prop sheets
  check     plan/2026-11-23c: the writer's answer is checked in code first (`kit.writer_findings`, into conflicts);
            each painted panel is then looked at (`board_inspector`: extra limbs, a held thing with no hand on it,
            feet on nothing) and a failed one is painted again ALONE, once, told what was wrong
  after     cells cut along the painted gutters, one PNG per shot, the numbered sheet drawn by code; all in the
            private `frames` bucket under `<production>/boards/<board>/`

  update    an edited or added shot's panel painted ALONE with its neighbours attached (one writer call and one
            picture each); a removed or moved shot only tidies the cells; nothing is ever pasted over another panel
            (the image model does not honour a mask: lab/panel_edit run_001, D3)
  marks     plan/2026-11-24d: code finds the stretches (runs of shots in which nobody moves) in the staging map; the
            writer gives each still person ONE ground spot per stretch (`contracts.marks`); a stretch of two or more
            shots gets a blocking plate, painted before the parts at the panels' shape, checked by `board_inspector`
            and attached to every part and every panel painted alone in its stretch. A repaint from the saved words
            keeps a plate whose pin is unchanged; `repaint_plates` paints the named ones again (Repaint marks, D3)

A board is never repainted by itself when a shot changes (the person, 2026-11-13): the API reports it out of date and
a person presses Update board.

A board never paints a face sheet (2026-11-22, was D4): the board picture has no faces, and parallel boards of
different scenes each painted the same person's sheet. The API names who on the board has none (`missing_faces`), and
a person makes it from the canon.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

from contracts import board as kit
from contracts import holding, safe_depiction
from contracts import marks as mk
from contracts import vehicles as vh
from contracts.canon import look_sheet_path, named_in, views_asset, views_label
from contracts.frame_brief import sheet_path
from contracts.producer import PersonEdits
from contracts.sceneplan import line_parts_of, scene_items
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.ports import ImageRefused, Reference
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.frame_render import pictures as pics

_log = logging.getLogger(__name__)
Row = dict[str, Any]
FAILED = "The scene board could not be made. Try again in a moment."
NOT_CONFIGURED = "Image generation is not set up on this server."
NO_WRITER = "The board writer is not set up on this server."
NOTHING = "Every shot of this scene is a black plate: there is nothing to paint."
# plan/2026-11-24d §3.1: absent-safe, said once on the board
NO_MAP = "No staging map: the people's spots are not held between shots."


def bad_cut(numbers: list[int]) -> str:
    """plan/2026-11-22 §3.2: the part's picture could not be cut into one panel per shot. Named by its SHOTS: a person
    sees one board of shots 1 to N, never its parts (2026-11-24)."""
    what = kit.shots_phrase(numbers)
    return f"{what[0].upper()}{what[1:]} came out in a different layout than was asked. Paint the board again."
# the place, up to four props, and on a later part the panel it repeats; a panel painted alone: the place, its props
# and its two neighbours
MAX_IMAGE_REFS = 6


class Board:
    """One scene's reads, as the board needs them: the frame_compose world, its shots and who each shot shows."""

    def __init__(self, ctx: RunContext, world: Row, saved: Row | None = None) -> None:
        self.ctx, self.world = ctx, world
        compose = parts.module("step", "frame_compose")
        self.w = compose.World.of(world)
        self.scene: Row = world["scene"]
        self.shot_rows: list[Row] = sorted(world.get("shots") or [], key=lambda r: int(r.get("number") or 0))
        self.seen: dict[str, dict[str, str]] = {}  # shot id → {canon id: name} the camera sees
        plates = []
        for s in self.shot_rows:
            try:
                if self.w.plate(s):
                    plates.append(str(s["id"]))
                    continue
                self.seen[str(s["id"])] = self.w.seen_names(s)
            except Exception:  # a shot the staging cannot read is painted with nobody named, never dropped
                _log.warning("shot %s could not be staged for the board", s.get("id"), exc_info=True)
                self.seen[str(s["id"])] = {}
        self.by_id = {str(c["id"]): c for c in world["canon"]}
        self._sheets: dict[str, bytes] = {}  # views sheets read once for the view check (§2.7), by path
        names = {cid: str(c.get("name") or "") for cid, c in self.by_id.items() if c.get("kind") == "character"}
        self.shots = kit.board_shots(self.scene, self.shot_rows, world.get("lines") or [],
                                     {k: list(v.values()) for k, v in self.seen.items()}, plates, names)
        # plan/2026-11-24b §2.2: each shot's vehicles and their role; the writer reads them in each shot's plan
        self.vehicles: dict[str, list[vh.ShotVehicle]] = {
            str(r["id"]): vh.shot_vehicles(r, world["canon"], PersonEdits.of(r).vehicles) for r in self.shot_rows}
        for bs in self.shots:
            if bs.painted and self.vehicles.get(bs.id):
                bs.plan["vehicles"] = [{"name": v.name, "role": v.role, **({"where": v.where} if v.where else {})}
                                       for v in self.vehicles[bs.id]]
        order: list[str] = []
        for shot in self.shots:
            if shot.painted:
                order += [c for c in self.seen.get(shot.id, {}) if c not in order]
        self.people = [c for c in order if (self.by_id.get(c) or {}).get("kind") == "character"]
        # A whole board takes fresh colours in person order; an update keeps the board's saved ones (plan/2026-11-17
        # §3.4), so a person added to an early shot shifts no one. `saved_colours` is what the row stores.
        self.saved_colours = (kit.keep_colours(saved, self.people) if saved
                              else {c: kit.COLOURS[i % len(kit.COLOURS)] for i, c in enumerate(self.people)})
        self.colour_of = {c: self.saved_colours[c] for c in self.people}  # id → colour, the people on the board
        self.colours = {str(self.by_id[c]["name"]): col for c, col in self.colour_of.items()}  # name → colour
        self.blocking = self._blocking(world)  # plan/2026-11-24d §3.1
        self.ground: list[mk.GroundMark] = []  # the writer's spots, kept by `check_marks`

    # ── fixed marks (plan/2026-11-24d) ─────────────────────────────────────────────────────────────

    def _blocking(self, world: Row) -> mk.Blocking:
        """The scene's stretches from its staging map. A scene planned with line parts counts the parts in its shots'
        block numbers; the map counts whole blocks (lab phase 0). Nothing readable: no stretches."""
        try:
            lines = list(world.get("lines") or [])
            whole = scene_items(self.scene, lines, parts=False)
            to_whole = mk.whole_index(scene_items(self.scene, lines, parts=True)) if line_parts_of(self.scene) else None
            return mk.stretches(self.scene.get("staging"), whole, self.shot_rows, to_whole=to_whole,
                                seen={k: list(v.values()) for k, v in self.seen.items()},
                                painted=[s.id for s in self.painted])
        except Exception:
            _log.warning("the stretches of scene %s could not be read", self.scene.get("id"), exc_info=True)
            return mk.Blocking()

    def check_marks(self, writer: kit.Writer) -> None:
        """The writer's spots kept (`marks.check`) on the writer and on this board, what is missing in `conflicts`;
        "No staging map" when the scene has none and people are seen in two or more shots."""
        kept, problems = mk.check(writer.marks, self.blocking)
        self.ground = kept
        writer.marks = [m.model_dump() for m in kept]
        if not self.blocking.stretches and sum(1 for s in self.painted if self.seen.get(s.id)) >= 2:
            problems = [NO_MAP]
        writer.conflicts = list(dict.fromkeys([*writer.conflicts, *problems]))

    def stretches_of(self, numbers: list[int]) -> list[mk.Stretch]:
        """The stretches with a complete set of spots that hold any of these shots, in order."""
        ids = {s.id for s in self.shots if s.number in numbers}
        return [s for s in self.blocking.stretches if ids & set(s.shot_ids) and mk.complete(s, self.ground)]

    def ground_words(self, numbers: list[int]) -> list[str]:
        """The "Ground marks" paragraphs of the stretches these shots are in (§3.3)."""
        return [w for s in self.stretches_of(numbers) if (w := mk.paragraph(s, self.ground, self.colours))]

    def panel_marks(self, numbers: list[int]) -> dict[int, str]:
        """Shot number → its marks line, for shots whose stretch has a complete set of spots."""
        held = {sid for s in self.stretches_of(numbers) for sid in s.shot_ids}
        return {s.number: line for s in self.shots if s.number in numbers and s.id in held
                and (line := mk.panel_line(self.blocking, s.id))}

    def stretch_of_number(self, number: int) -> mk.Stretch | None:
        s = next((x for x in self.shots if x.number == number), None)
        found = self.blocking.stretch_of(s.id) if s else None
        return found if found is not None and mk.complete(found, self.ground) else None

    @property
    def views_template(self) -> str:
        """The location views sheet's template; a sheet made before plan/2026-11-24c has none and was an outside one."""
        row = self.by_id.get(str(self.scene.get("location_id") or ""))
        asset = views_asset(row) if row else None
        return str((asset or {}).get("template") or "outside") if asset is not None else ""

    @property
    def painted(self) -> list[kit.BoardShot]:
        return [s for s in self.shots if s.painted]

    def row(self, shot_id: str) -> Row:
        return next(r for r in self.shot_rows if str(r["id"]) == shot_id)

    def shot(self, shot_id: str) -> kit.BoardShot:
        return next(s for s in self.shots if s.id == shot_id)

    def shot_by_number(self, number: int) -> kit.BoardShot:
        return next(s for s in self.shots if s.number == number)

    # ── what the writer reads ──────────────────────────────────────────────────────────────

    def _card(self, cid: str) -> Row:
        return dict(((self.by_id.get(cid) or {}).get("current") or {}).get("card") or {})

    def _plan_text(self, shots: list[kit.BoardShot]) -> str:
        return json.dumps([s.plan for s in shots], ensure_ascii=False)

    def place(self) -> tuple[Row, Row | None]:
        loc = str(self.scene.get("location_id") or "")
        row = self.by_id.get(loc)
        if not row:
            return {"name": "", "look": "", "spots": []}, None
        spots = [{"name": c["name"], "look": self._card(str(c["id"])).get("look", "")}
                 for c in self.world["canon"] if str(c.get("parent_id") or "") == loc and c.get("class") == "spot"]
        place: Row = {"name": row["name"], "look": self._card(loc).get("look", ""), "spots": spots}
        if self.views:  # plan/2026-11-24: the writer names each panel's view
            place["views"] = [{"n": v["n"], "name": v["name"], **({"camera": v["camera"], "sees": v["sees"]}
                                                                  if v.get("sees") else {"what": v.get("what", "")})}
                              for v in self.views]  # plan/2026-11-24c §2.7: each view's camera and sees words
        return place, row

    @property
    def views(self) -> list[Row]:
        """The views of the scene's location sheet (plan/2026-11-24), [] when it has none."""
        row = self.by_id.get(str(self.scene.get("location_id") or ""))
        asset = views_asset(row) if row else None
        return [dict(v) for v in (asset or {}).get("views") or []]

    def view_crop(self, n: int, shot: int = 0) -> bytes | None:
        """View `n` cut from the panel's views sheet (plan/2026-11-24c §2.7): the location's, or the vehicle's a panel
        is INSIDE (plan/2026-11-24b §5); for the board check. None when there is no such view or the sheet cannot be
        read (then the view is not checked)."""
        row = self.sheet_row(shot)
        asset = views_asset(row) if row else None
        views = [dict(v) for v in (asset or {}).get("views") or []]
        view = next((v for v in views if int(v.get("n") or 0) == n), None) if n else None
        if row is None or asset is None or view is None or not view.get("box"):
            return None
        try:
            if str(asset["path"]) not in self._sheets:
                self._sheets[str(asset["path"])] = _download(self.ctx, "references", str(asset["path"]))
            return pics.crop(self._sheets[str(asset["path"])], [int(x) for x in view["box"]])
        except Exception:
            _log.warning("the views sheet could not be read for the board check", exc_info=True)
            return None

    # ── vehicles (plan/2026-11-24b) ──────────────────────────────────────────────────────────────

    def shot_vehicles(self, number: int) -> list[vh.ShotVehicle]:
        s = next((x for x in self.shots if x.number == number), None)
        return list(self.vehicles.get(s.id, [])) if s else []

    def inside_sheet(self, number: int) -> Row | None:
        """The vehicle a shot is INSIDE, when that vehicle has a views sheet (§5): its panel names that sheet's view."""
        inside = vh.inside_of(self.shot_vehicles(number))
        row = self.by_id.get(inside.id) if inside else None
        return row if row is not None and views_asset(row) is not None else None

    def sheet_row(self, number: int = 0) -> Row | None:
        """The row whose views sheet a panel's `view` counts in: the vehicle it is inside (when it has one), else the
        scene's location."""
        return self.inside_sheet(number) if number and self.inside_sheet(number) else \
            self.by_id.get(str(self.scene.get("location_id") or ""))

    def panel_views(self) -> dict[int, list[Row]]:
        """Shot number → the views of the vehicle sheet a panel INSIDE a vehicle names (§5); other panels: none."""
        out = {}
        for s in self.painted:
            row = self.inside_sheet(s.number)
            if row is not None:
                out[s.number] = [dict(v) for v in (views_asset(row) or {}).get("views") or []]
        return out

    def vehicle_pictures(self, shots: list[kit.BoardShot]) -> list[tuple[str, str]]:
        """(label, path) of every vehicle these panels show (§2.3): its views sheet when it has one, else its plate."""
        out: list[tuple[str, str]] = []
        for vid in dict.fromkeys(v.id for s in shots for v in self.vehicles.get(s.id, [])):
            row = self.by_id.get(vid)
            if row is None:
                continue
            asset = views_asset(row)
            if asset is not None:
                out.append((vh.sheet_label(str(row["name"]), vh.make_of(row)), str(asset["path"])))
            elif sheet_path(row):
                out.append((vh.plate_label(str(row["name"]), vh.make_of(row)), sheet_path(row)))
        return out

    def vehicle_line(self, numbers: list[int], labels: list[str]) -> str:
        """The board's "Vehicles (every panel):" line for the panels of `numbers` (in their order on this sheet), the
        pictures named by `labels`."""
        images: dict[str, int] = {}
        for vid in dict.fromkeys(v.id for n in numbers for v in self.shot_vehicles(n)):
            row = self.by_id.get(vid) or {}
            heads = (vh.plate_label(str(row.get("name") or ""), vh.make_of(row)),
                     vh.sheet_label(str(row.get("name") or ""), vh.make_of(row)))
            at = next((i for i, label in enumerate(labels, 1) if label in heads), None)
            if at is not None:
                images[vid] = at
        panels = [(i, self.shot_vehicles(n)) for i, n in enumerate(numbers, 1)]
        return vh.board_line(panels, images, self.by_id)

    def vehicle_cards(self) -> list[Row]:
        """What the writer reads about each vehicle the painted panels show: name, make, look (§2.3)."""
        ids = dict.fromkeys(v.id for s in self.painted for v in self.vehicles.get(s.id, []))
        return [{"name": str(self.by_id[i]["name"]), "make": vh.make_of(self.by_id[i]),
                 "look": str(vh.card_of(self.by_id[i]).get("look") or ""),
                 **({"views": [{k: v.get(k, "") for k in ("n", "name", "camera", "sees")}
                               for v in (views_asset(self.by_id[i]) or {}).get("views") or []]}
                    if views_asset(self.by_id[i]) is not None else {})}
                for i in ids if i in self.by_id]

    def props(self, shots: list[kit.BoardShot]) -> list[Row]:
        """The props these shots' plans name, as canon rows: by name or alias, or as the end of a word the plan uses
        ("smartphone" is the canon "phone", plan/2026-11-23c §3.3; the frame refs audit of 2026-11-18)."""
        text = self._plan_text(shots)
        words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
        out = []
        for c in self.world["canon"]:
            if c.get("kind") != "prop":
                continue
            names = [str(c.get("name") or ""), *(str(a) for a in c.get("aliases") or [])]
            if any(n and named_in(n, text) for n in names) or any(
                    holding.canon_match(w, [c]) is not None for w in words if len(w) >= 4):
                out.append(c)
        return out

    def prop_names(self, shots: list[kit.BoardShot]) -> list[str]:
        return [str(p["name"]) for p in self.props(shots)]

    def place_names(self, shots: list[kit.BoardShot]) -> list[str]:
        """The canon places these panels show, which stay real (never clay): the scene's location, its spots, and
        any other place the plans name (a food three-wheeler is a place, 2026-11-23)."""
        text = self._plan_text(shots)
        place, _ = self.place()
        out = [str(place.get("name") or ""), *(str(s["name"]) for s in place.get("spots") or [])]
        out += [str(c["name"]) for c in self.world["canon"]
                if c.get("kind") == "location" and c.get("name") and named_in(str(c["name"]), text)]
        return list(dict.fromkeys(n for n in out if n))

    def carried(self) -> dict[str, str]:
        """Person name → what they carry through the scene (their scene condition and look accessories), which the
        free check allows in a hand (2026-11-23: Anudi's open umbrella continues from scene 3)."""
        return {str(r["name"]): " ".join(str(r.get(k) or "") for k in ("scene_condition", "accessories")).strip()
                for r in self.people_rows()}

    def people_rows(self) -> list[Row]:
        """Each person as the writer reads them: never a face for the board, but the age and gender that give the
        mannequin its height and build (plan/2026-11-23c §3.1)."""
        looks, conditions = self.world.get("looks") or {}, self.world.get("conditions") or {}
        out = []
        for cid in self.people:
            look, card = looks.get(cid) or {}, self._card(cid)
            out.append({"name": self.by_id[cid]["name"], "gender": card.get("gender", ""), "age": card.get("age", ""),
                        "appearance": card.get("appearance", ""),
                        "outfit": look.get("outfit", ""), "hair": look.get("hair", ""),
                        "accessories": look.get("accessories", ""), "scene_condition": conditions.get(cid, "")})
        return out

    def writer_pictures(self) -> list[tuple[str, str]]:
        """(label, references-bucket path) the writer reads: each person's look sheet (else base sheet), the place, the
        props. The board IMAGE gets only the place (no faces; the props are clay stand-ins, plan/2026-11-23c)."""
        looks = self.world.get("looks") or {}
        out: list[tuple[str, str]] = []
        for cid in self.people:
            row = self.by_id[cid]
            look = looks.get(cid)
            if look is not None and look_sheet_path(look):
                out.append((f"the look sheet for {row['name']}", look_sheet_path(look)))
            elif sheet_path(row):
                out.append((f"the character sheet for {row['name']}", sheet_path(row)))
        out += self.image_pictures(self.painted)
        out += [(f"the reference sheet for {p['name']}", sheet_path(p)) for p in self.props(self.painted)
                if sheet_path(p)]
        return out[: kit.MAX_WRITER_PICTURES]

    def image_pictures(self, shots: list[kit.BoardShot]) -> list[tuple[str, str]]:
        """What the board picture is painted against: the location's views sheet (plan/2026-11-24), else its plate. The
        props are white clay stand-ins (plan/2026-11-23c D2), so their sheets would only invite the real thing."""
        _, loc = self.place()
        if not loc:
            return []
        asset = views_asset(loc)
        place = ([(views_label(str(loc["name"])), str(asset["path"]))] if asset is not None else
                 [(f"the location plate for {loc['name']}", sheet_path(loc))] if sheet_path(loc) else [])
        return place + self.vehicle_pictures(shots)  # plan/2026-11-24b §2.3/§5: after the sheet or the plate

    def bundle(self, labels: list[str]) -> Row:
        place, _ = self.place()
        props = [{"name": p["name"], "details": self._card(str(p["id"])).get("details", "")}
                 for p in self.props(self.painted)]
        return kit.writer_bundle(self.scene, self.shots, self.people_rows(), place, props, labels,
                                 vehicles=self.vehicle_cards(), stretches=mk.stretch_rows(self.blocking))


def _beat(ctx: RunContext, text: str) -> None:
    """Progress on the job (2026-11-24): a board job runs ten minutes and more (the writer, every part, every panel
    check), and the sweeper ends a job with no event for its limit, so each step says what it starts. Best effort."""
    jobs = ctx.ports.jobs
    if jobs is None or ctx.job_id is None:
        return
    try:
        jobs.stage(ctx.job_id, "board", "running", text)
    except Exception:
        _log.warning("board progress could not be written", exc_info=True)


def _download(ctx: RunContext, bucket: str, path: str) -> bytes:
    return bytes(ctx.need("files").download(bucket, path))


def _pictures(ctx: RunContext, wanted: list[tuple[str, str]]) -> list[Reference]:
    out = []
    for label, path in wanted:
        try:
            out.append(Reference(label=label, data=_download(ctx, "references", path)))
        except Exception:
            _log.warning("%s could not be read", label, exc_info=True)
    return out


def write(ctx: RunContext, b: Board, repaint: dict[int, str] | None = None) -> kit.Writer:
    """The board writer's answer. Raises `ModelUnavailable` without a key."""
    pictures = _pictures(ctx, b.writer_pictures())
    message = kit.writer_message(b.bundle([p.label for p in pictures]), b.colours, repaint=repaint)
    out = agents.build("board_writer").run(
        {"message": message, "pictures": [{"mime": p.mime, "b64": base64.b64encode(p.data).decode()}
                                          for p in pictures]},
        ctx, max_output=kit.WRITER_MAX_OUTPUT)
    writer = kit.Writer.of(out.model_dump())
    writer.conflicts = list(dict.fromkeys([*writer.conflicts, *kit.writer_findings(writer, b.shots, b.carried(),
                                                                                    b.views, b.panel_views())]))
    return kit.stamp(writer, {s.number: b.row(s.id) for s in b.painted})  # a repaint reuses these words


# ── the board check (plan/2026-11-23c F2) ────────────────────────────────────────────────────


def _check_panel(ctx: RunContext, b: Board, panel: kit.Panel, data: bytes) -> Row | None:
    """What the vision model sees wrong in one painted panel, or None: no key, the vision model switched off
    (`OPENAI__MODEL_VISION=""`), or a failed call (the panel is kept as it is)."""
    if not (llm.models_enabled() and get_settings().openai.model_vision):
        return None
    view = kit.panel_view(panel, kit.views_of(panel, b.views, b.panel_views()))
    crop = b.view_crop(panel.view, panel.shot) if view is not None else None
    try:
        out = agents.build("board_inspector").run(
            {"image_b64": base64.b64encode(data).decode(), "mime": "image/png",
             "people": [f"{n} is the {c} mannequin" for n, c in b.colours.items()
                        if any(x.name == n for x in panel.people)],
             "panel": f"{panel.camera.rstrip('.')}. {panel.picture}", "hands": kit.hands_text(panel, b.colours),
             # plan/2026-11-24c §2.7: the panel's view, its words and its crop beside the panel
             **({"view": kit.view_named(view), "view_b64": base64.b64encode(crop).decode()}
                if view is not None and crop is not None else {})},
            ctx)
    except Exception:
        _log.warning("panel of shot %s could not be checked", panel.shot, exc_info=True)
        return None
    return dict(out.model_dump())


def _faults(answer: Row) -> list[str]:
    """The faults that send a panel back; [] when it is fine."""
    out = [str(p) for p in answer.get("problems") or [] if str(p).strip()][:3]
    named = [w for flag, w in (("extra_limbs", "a mannequin with more or fewer than two arms"),
                               ("floating", "a held thing with no hand on it, floating"),
                               ("ungrounded", "feet not standing on the ground"),
                               ("hands_mismatch", "a hand holding something other than the panel says"),
                               ("view_mismatch", "the background shows another view of the place than the panel's"))
             if (answer.get("hands_match") is False if flag == "hands_mismatch" else
                 answer.get("view_match") is False if flag == "view_mismatch" else answer.get(flag) is True)]
    return (out or named) if named else []


def _mend(ctx: RunContext, b: Board, writer: kit.Writer, panel: kit.Panel, data: bytes, refs: list[Reference],
          aspect: str, quality: str) -> tuple[bytes, Row | None]:
    """The panel checked, and painted again ALONE once when the check finds a fault, told what was wrong. →
    (the picture to keep, the cell's `check`: `{ok, problems, fixed?, repainted?}`; None when nothing could
    look)."""
    _beat(ctx, f"Checking the panel of shot {panel.shot}")
    answer = _check_panel(ctx, b, panel, data)
    if answer is None:
        return data, None
    faults = _faults(answer)
    if not faults:
        return data, {"ok": True, "problems": []}
    painter = ctx.ports.images
    shot = b.shot_by_number(panel.shot)
    view = kit.panel_view(panel, kit.views_of(panel, b.views, b.panel_views()))
    fix = kit.fix_line(faults, kit.view_named(view) if view is not None and answer.get("view_match") is False else "")
    labels = [r.label for r in refs]
    prompt = kit.panel_prompt(writer, panel, labels, b.colours, aspect, props=b.prop_names([shot]),
                              fix=fix, places=b.place_names([shot]), views=b.views,
                              vehicles=b.vehicle_line([panel.shot], labels), panel_views=b.panel_views(),
                              marks=" ".join(b.ground_words([panel.shot])),
                              panel_mark=b.panel_marks([panel.shot]).get(panel.shot, ""))
    if painter is None or safe_depiction.blocking(prompt):
        return data, {"ok": False, "problems": faults}
    _beat(ctx, f"Painting the panel of shot {panel.shot} again")
    try:
        picture = painter(prompt, aspect, refs, quality=quality)
    except Exception:
        _log.warning("the panel of shot %s could not be painted again", panel.shot, exc_info=True)
        return data, {"ok": False, "problems": faults}
    again = _check_panel(ctx, b, panel, picture.data)
    left = _faults(again) if again is not None else faults  # not looked at again: the faults are not known gone
    return picture.data, {"ok": again is not None and not left, "problems": left, "fixed": faults, "repainted": True}


# ── the blocking plates (plan/2026-11-24d §3.4) ──────────────────────────────────────────────────────────────


def _plate_for(b: Board, writer: kit.Writer, s: mk.Stretch) -> tuple[Row, list[tuple[str, str]], str] | None:
    """What a stretch's plate is painted from: (its record without a picture, the pictures, the prompt); None when it
    gets no plate (fewer than two shots, a spot missing, or a sheet whose first view is not the anchor wide)."""
    if not s.plate or not mk.complete(s, b.ground):
        return None
    shots = [x for x in b.painted if x.id in set(s.shot_ids)]
    panels = [p for p in (writer.panel(x.number) for x in shots) if p is not None]
    if not panels:
        return None
    view = mk.plate_view([p.view for p in panels], b.views, b.views_template) if b.views else None
    if b.views and view is None:
        return None
    wanted = b.image_pictures(shots)
    labels = [label for label, _ in wanted]
    numbers = [x.number for x in shots]
    prompt = kit.plate_prompt(writer, s, mk.paragraph(s, b.ground, b.colours), labels, b.colours, view, panels[0],
                              aspect=_aspect(b), props=b.prop_names(shots), places=b.place_names(shots),
                              views=b.views, vehicles=b.vehicle_line(numbers, labels))
    record: Row = {"n": s.n, "shots": list(s.numbers), "shot_ids": list(s.shot_ids), "people": list(s.people),
                   "view": int(view["n"]) if view else 0,
                   "pin": mk.pin(s, b.ground, b.colours, [path for _, path in wanted]), "prompt": prompt}
    return record, wanted, prompt


def _aspect(b: Board) -> str:
    return kit.board_aspect(ASPECT_RATIO[Orientation(b.world["production"].get("orientation") or "horizontal")])


def _paint_plates(ctx: RunContext, b: Board, writer: kit.Writer, production_id: str, board_id: str, quality: str,
                  force: set[int]) -> dict[int, bytes]:
    """Every stretch's plate, painted ONCE before the parts (or kept: a plate of the saved words whose pin is the same
    and that is not in `force`). Each new one is looked at by `board_inspector` and painted again alone, once, when
    it finds a fault. A plate that cannot be painted leaves its stretch with the words (a `conflicts` line). Sets
    `writer.plates`. → stretch n → the plate's picture."""
    painter = ctx.ports.images
    kept = {str(x.get("pin")): x for x in writer.plates if x.get("pin") and x.get("path")}
    plates: list[Row] = []
    out: dict[int, bytes] = {}
    for s in b.blocking.stretches:
        found = _plate_for(b, writer, s)
        if found is None:
            continue
        record, wanted, prompt = found
        old = kept.get(record["pin"])
        if old is not None and s.n not in force:
            try:
                out[s.n] = _download(ctx, "frames", str(old["path"]))
                plates.append({**record, "path": old["path"], "check": old.get("check")})
                continue
            except Exception:
                _log.warning("the plate of %s could not be read; it is painted again", s.label, exc_info=True)
        if painter is None or safe_depiction.blocking(prompt):
            continue
        _beat(ctx, f"Painting the blocking plate for {s.label}")
        refs = _pictures(ctx, wanted)
        aspect = _aspect(b)
        try:
            data = painter(prompt, aspect, refs, quality=quality).data
        except Exception:
            _log.warning("the plate of %s could not be painted", s.label, exc_info=True)
            writer.conflicts = list(dict.fromkeys([*writer.conflicts, f"{s.label.capitalize()}: the blocking plate "
                                                   "could not be painted; its panels hold their marks by words only."]))
            continue
        data, check = _check_plate(ctx, b, writer, s, record, data, prompt, refs, aspect, quality)
        path = f"{production_id}/boards/{board_id}/plate_{s.n}-{uuid4().hex[:8]}.png"
        try:
            ctx.need("files").upload("frames", path, data, "image/png")
        except Exception:
            _log.warning("the plate of %s could not be stored", s.label, exc_info=True)
            continue
        out[s.n] = data
        plates.append({**record, "path": path, "check": check})
    writer.plates = plates
    return out


def _check_plate(ctx: RunContext, b: Board, writer: kit.Writer, s: mk.Stretch, record: Row, data: bytes,
                 prompt: str, refs: list[Reference], aspect: str, quality: str) -> tuple[bytes, Row | None]:
    """The plate looked at as a panel is (lab T: its bag on the forearm went into every panel): the hands of the
    stretch's first panel, its view; painted again ONCE, told what was wrong, when the check finds a fault."""
    first = next((p for p in (writer.panel(n) for n in s.numbers) if p is not None), None)
    if first is None:
        return data, None
    probe = replace(first, view=int(record.get("view") or 0))
    _beat(ctx, f"Checking the blocking plate for {s.label}")
    answer = _check_panel(ctx, b, probe, data)
    if answer is None:
        return data, None
    faults = _faults(answer)
    painter = ctx.ports.images
    if not faults or painter is None:
        return data, {"ok": not faults, "problems": faults}
    again = prompt + "\n\n" + kit.fix_line(faults)
    if safe_depiction.blocking(again):
        return data, {"ok": False, "problems": faults}
    _beat(ctx, f"Painting the blocking plate for {s.label} again")
    try:
        picture = painter(again, aspect, refs, quality=quality)
    except Exception:
        _log.warning("the plate of %s could not be painted again", s.label, exc_info=True)
        return data, {"ok": False, "problems": faults}
    look = _check_panel(ctx, b, probe, picture.data)
    left = _faults(look) if look is not None else faults
    return picture.data, {"ok": look is not None and not left, "problems": left, "fixed": faults, "repainted": True}


def _plate_refs(b: Board, plates: dict[int, bytes], numbers: list[int]) -> list[Reference]:
    """The plates of the stretches these shots are in, labelled for the image model (§3.4)."""
    return [Reference(label=mk.plate_label(s), data=plates[s.n]) for s in b.stretches_of(numbers) if s.n in plates]


def _saved_plates(ctx: RunContext, b: Board, writer: kit.Writer, numbers: list[int]) -> list[Reference]:
    """A panel painted alone (an update): the saved plate of its stretch, found by the shot's id."""
    out: list[Reference] = []
    for s in b.stretches_of(numbers):
        saved = next((x for x in writer.plates if x.get("path") and set(s.shot_ids) & set(x.get("shot_ids") or [])),
                     None)
        if saved is None:
            continue
        try:
            out.append(Reference(label=mk.plate_label(s), data=_download(ctx, "frames", str(saved["path"]))))
        except Exception:
            _log.warning("the plate of %s could not be read for a panel", s.label, exc_info=True)
    return out


_STILL_WRONG = re.compile(r"Shot \d+: the board check still sees ")


def _still_wrong(number: int, check: Row | None) -> str:
    """The conflict line for a panel the check still finds wrong after its one repaint."""
    if not check or check.get("ok") or not check.get("repainted"):
        return ""
    return f"Shot {number}: the board check still sees {'; '.join(check.get('problems') or ['a fault'])}."


def _cells_of(b: Board, part: list[kit.BoardShot], index: int, count: int) -> list[kit.BoardShot]:
    """The shots of one part, black plates included: from its first painted shot (the scene's start for part 1) to
    its last painted shot (the scene's end for the last part)."""
    ids = [s.id for s in b.shots]
    start = 0 if index == 0 else ids.index(part[0].id)
    end = len(ids) - 1 if index == count - 1 else ids.index(part[-1].id)
    return b.shots[start: end + 1]


def _store_part(ctx: RunContext, b: Board, board_id: str, production_id: str, image: bytes,
                cells_shots: list[kit.BoardShot], numbers: list[int], old: dict[str, Row] | None = None,
                boxes: list[Any] | None = None) -> tuple[list[Row], str, str]:
    """Cut, store and record one painted part. → (cells, board path, sheet path). `old`: shot id → the previous
    cell (its note and lock carry over); `boxes`: the cells' boxes when the layout is known (a masked repaint)."""
    files = ctx.need("files")
    base = f"{production_id}/boards/{board_id}"
    files.upload("frames", f"{base}/board.png", image, "image/png")
    boxes = boxes or pics.cell_boxes(image, len(numbers))
    crops: dict[str, bytes] = {}
    cells = []
    for s in cells_shots:
        panel = numbers.index(s.number) + 1 if s.painted and s.number in numbers else None
        cell = kit.new_cell(s, b.row(s.id), panel)
        prev = (old or {}).get(s.id)
        if prev:
            cell.update(note=str(prev.get("note") or ""), locked=bool(prev.get("locked")))
        if panel is not None:
            box = [int(v) for v in boxes[panel - 1]]
            data = pics.crop(image, box)
            path = f"{base}/cell_{s.number:03d}.png"
            files.upload("frames", path, data, "image/png")
            crops[s.id] = data
            cell.update(box=box, path=path)
        cells.append(cell)
    sheet = pics.scene_sheet(cells_shots, crops)
    files.upload("frames", f"{base}/sheet.png", sheet, "image/png")
    return cells, f"{base}/board.png", f"{base}/sheet.png"


REJECTED_CUT = "rejected_cut"  # the `checks` entry of a part whose picture could not be cut (2026-11-24)


def _rejected(ctx: RunContext, production_id: str, board_id: str, image: bytes, boxes: list[Any],
              problems: list[str]) -> Row:
    """A part's picture that failed the cut, kept so a person can see it (2026-11-24): the picture as painted and a
    copy with the cut drawn on it, under the part's own folder (never a cell). → the part's `checks` entry. Storing is
    best effort: the part fails the same way when it cannot be stored."""
    base = f"{production_id}/boards/{board_id}"
    entry: Row = {"kind": REJECTED_CUT, "problems": list(problems), "boxes": [[int(v) for v in b] for b in boxes]}
    files = ctx.need("files")
    try:
        files.upload("frames", f"{base}/rejected.png", image, "image/png")
        entry["path"] = f"{base}/rejected.png"
        files.upload("frames", f"{base}/rejected-cut.png", pics.draw_cut(image, boxes, problems), "image/png")
        entry["cut_path"] = f"{base}/rejected-cut.png"
    except Exception:
        _log.warning("the rejected picture of board %s could not be stored", board_id, exc_info=True)
    return entry


def paint(ctx: RunContext, production: Row, world: Row, board: Row, state: Row, job_id: str,
          warn: Callable[[str], None]) -> Row:
    """A whole board (every part) for a new version. → `{status, parts, error?}`."""
    frames, painter = ctx.need("frames"), ctx.ports.images
    board_id = str(board["id"])
    if painter is None:
        frames.save_board(board_id, {"status": "failed", "error": NOT_CONFIGURED})
        return {"status": "failed", "error": NOT_CONFIGURED}
    # 2026-11-24 (the person): a repaint paints the pictures again from the words already written; the board writer
    # runs only for a first board or when a person asks to rewrite (a shot changed since, or a note asks for it).
    saved = [r for r in (frames.board(str(i)) for i in state.get("saved") or []) if r]
    rewrite = bool(state.get("rewrite")) or not saved
    b = Board(ctx, world, saved=None if rewrite else (saved[0].get("colours") or {}))
    if not b.painted:
        frames.save_board(board_id, {"status": "failed", "error": NOTHING})
        return {"status": "failed", "error": NOTHING}
    carry = [frames.board(str(i)) for i in state.get("carry") or []]
    old: dict[str, Row] = {}
    for prev in (r for r in carry if r):
        for c in prev.get("cells") or []:
            old.setdefault(str(c.get("shot_id")), {**c, "_board": prev})
    notes = {int(c["number"]): str(c.get("note") or "") for c in old.values()
             if c.get("note") and not c.get("locked")}
    reused = None if rewrite else kit.reuse_writer(saved, b.shot_rows, [s.id for s in b.painted])
    _beat(ctx, "Painting from the panels already written" if reused is not None else "Writing the panels")
    if reused is not None:
        writer = reused  # the last paint's "check still sees" lines are about pictures this repaint replaces
        writer.conflicts = [c for c in writer.conflicts if not _STILL_WRONG.match(c)]
    else:
        try:
            writer = write(ctx, b, notes or None)
        except ModelUnavailable:
            frames.save_board(board_id, {"status": "failed", "error": NO_WRITER})
            return {"status": "failed", "error": NO_WRITER}
        except Exception:
            _log.warning("board writer failed for board %s", board_id, exc_info=True)
            frames.save_board(board_id, {"status": "failed", "error": FAILED})
            return {"status": "failed", "error": FAILED}
    b.check_marks(writer)  # plan/2026-11-24d §3.2: the spots kept, what is missing said
    missing = kit.missing_panels(writer, [s.number for s in b.painted])
    if missing:
        error = f"The board writer left out {kit.shots_phrase(missing)}. Paint the board again."
        frames.save_board(board_id, {"status": "failed", "error": error, "writer": writer.dump()})
        return {"status": "failed", "error": error}
    # The board has the production's shape (2026-11-16): a vertical production's panels are tall, like its frames.
    aspect = kit.board_aspect(ASPECT_RATIO[Orientation(production.get("orientation") or "horizontal")])
    groups = kit.parts_of(b.painted, aspect)
    rows = [board]
    if len(groups) > 1:  # D5: the first row is part 1; the job adds the others
        extra = [{"id": str(uuid4()), "production_id": board["production_id"], "scene_id": board["scene_id"],
                  "version": board["version"], "part": i + 1, "parts": len(groups), "status": "running",
                  "job_id": board.get("job_id"), "quality": board.get("quality") or kit.DEFAULT_QUALITY,
                  "created_by": board.get("created_by")} for i in range(1, len(groups))]
        frames.create_boards(extra)
        rows += extra
    colours = dict(b.saved_colours)
    # plan/2026-11-24d §3.4: the plates first, at the board's quality, kept when the saved words' plate still fits
    try:
        plates = _paint_plates(ctx, b, writer, str(production["id"]), board_id,
                               str(board.get("quality") or kit.DEFAULT_QUALITY),
                               {int(n) for n in state.get("repaint_plates") or []})
    except Exception:  # never fails a board: its parts are painted with the words only
        _log.warning("the blocking plates of board %s could not be painted", board_id, exc_info=True)
        plates, writer.plates = {}, []
    done = 0
    previous_last: bytes | None = None
    for i, (row, group) in enumerate(zip(rows, groups, strict=True)):
        rid = str(row["id"])
        numbers = [s.number for s in group]
        refs = _pictures(ctx, b.image_pictures(group))
        refs += _plate_refs(b, plates, numbers)  # after the place and vehicles, before the overlap panel
        if previous_last is not None:
            refs.append(Reference(label=kit.OVERLAP_LABEL, data=previous_last))
        labels = [r.label for r in refs]
        prompt = kit.board_prompt(writer, numbers, labels, b.colours, aspect,
                                  props=b.prop_names(group), places=b.place_names(group), views=b.views,
                                  vehicles=b.vehicle_line(numbers, labels), panel_views=b.panel_views(),
                                  marks=b.ground_words(numbers), panel_marks=b.panel_marks(numbers))
        fields: Row = {"parts": len(groups), "writer": writer.dump(), "colours": colours, "prompt": prompt}
        found = safe_depiction.blocking(prompt)
        if found:
            frames.save_board(rid, {**fields, "status": "refused", "error": safe_depiction.frame_error(found)})
            continue
        _beat(ctx, f"Painting part {i + 1} of {len(groups)}")
        try:
            picture = painter(prompt, aspect, refs, quality=str(row.get("quality") or kit.DEFAULT_QUALITY))
        except ImageRefused as exc:
            frames.save_board(rid, {**fields, "status": "refused", "error": str(exc)})
            continue
        except Exception:
            _log.warning("board %s part %s failed", board_id, i + 1, exc_info=True)
            frames.save_board(rid, {**fields, "status": "failed", "error": FAILED})
            continue
        try:  # a failure cutting or storing this part fails this part only; the others still paint (2026-11-16)
            image = picture.data
            cells_shots = _cells_of(b, group, i, len(groups))
            boxes = pics.cell_boxes(image, len(numbers))
            problems = pics.cut_problems(image, boxes)
            if problems:  # plan/2026-11-22: never a crop with two panels or an empty cell; a person paints again
                _log.warning("board %s part %s came out in another layout: %s", board_id, i + 1, "; ".join(problems))
                frames.save_board(rid, {**fields, "status": "failed", "error": bad_cut(numbers),
                                        "checks": [_rejected(ctx, str(production["id"]), rid, image, boxes,
                                                             problems)]})
                previous_last = None
                continue
            kept = {s.id: old[s.id] for s in cells_shots
                    if s.painted and s.id in old and old[s.id].get("locked") and old[s.id].get("path")}
            if kept:  # a locked panel is never repainted: its old picture is put back where its cell now is
                pasted = {}
                for sid, prev in kept.items():
                    try:
                        pasted[numbers.index(b.row(sid)["number"]) + 1] = _download(ctx, "frames", str(prev["path"]))
                    except Exception:
                        _log.warning("locked panel of shot %s could not be read; it is repainted", sid, exc_info=True)
                image = pics.paste(image, pasted, {p: boxes[p - 1] for p in pasted})
            cells, path, sheet = _store_part(ctx, b, rid, str(production["id"]), image, cells_shots, numbers, old,
                                             boxes)
            for c in cells:  # a kept panel keeps its old pin: it still shows what it was painted against
                if c["shot_id"] in kept and kept[c["shot_id"]].get("pin"):
                    c["pin"] = kept[c["shot_id"]]["pin"]
            places = _pictures(ctx, b.image_pictures(group))
            mended = False
            for c in cells:  # plan/2026-11-23c F2: every new panel is looked at; a wrong one is painted again alone
                p = writer.panel(int(c["number"]))
                if p is None or not c.get("box") or c["shot_id"] in kept:
                    continue
                data, check = _mend(ctx, b, writer, p, pics.crop(image, c["box"]),
                                    [*places, *_plate_refs(b, plates, [p.shot])], aspect,
                                    str(row.get("quality") or kit.DEFAULT_QUALITY))
                if check is None:
                    continue
                c["check"] = check
                if check.get("repainted"):
                    fix = f"{production['id']}/boards/{rid}/cell_{int(c['number']):03d}-fix.png"
                    ctx.need("files").upload("frames", fix, data, "image/png")
                    c.update(path=fix, source="panel", box=None)
                    mended = True
                line = _still_wrong(int(c["number"]), check)
                if line and line not in writer.conflicts:
                    writer.conflicts.append(line)
            if mended:
                sheet = _sheet(ctx, b, cells, f"{production['id']}/boards/{rid}", "checked")
            fields["writer"] = writer.dump()
            last = next((c for c in reversed(cells) if c.get("path")), None)
            # the next part repeats this part's last panel; a panel the board check painted again has its own picture
            # and no box on the sheet (2026-11-24: cropping box None failed a part that was painted and stored)
            previous_last = (None if last is None else pics.crop(image, last["box"]) if last.get("box") else
                             _download(ctx, "frames", str(last["path"])))
        except Exception:
            _log.exception("board %s part %s could not be cut or stored", board_id, i + 1)
            frames.save_board(rid, {**fields, "status": "failed", "error": FAILED})
            previous_last = None
            continue
        frames.save_board(rid, {**fields, "status": "done", "error": None, "storage_path": path, "sheet_path": sheet,
                                "cells": cells})
        done += 1
    status = "done" if done == len(groups) else ("failed" if not done else "partial")
    return {"status": status, "parts": len(groups), "painted": done, "conflicts": len(writer.conflicts)}


class _Failed(Exception):
    """One panel of an update could not be painted: the reason, in words for the person."""


def _approval(state: Row, board_id: str) -> Row:
    """The approval the API cleared when it queued the update (§3.3), to write back to a part none of whose cells
    changed."""
    saved = (state.get("approvals") or {}).get(board_id) or {}
    if not saved.get("approved_at"):
        return {}
    return {"approved_at": saved["approved_at"], "approved_by": saved.get("approved_by")}


def _board_writer(rows: list[Row]) -> kit.Writer:
    """The board's writer (every part stores the same one; a panel only a later part has is added)."""
    return kit.saved_writer(rows)


def _with_panel(writer: kit.Writer, panel: kit.Panel, conflicts: list[str] | None = None) -> kit.Writer:
    panels = sorted([*(p for p in writer.panels if p.shot != panel.shot), panel], key=lambda p: p.shot)
    return kit.Writer(world=writer.world, geography=writer.geography, panels=panels,
                      conflicts=list(dict.fromkeys([*writer.conflicts, *(conflicts or [])])),
                      marks=list(writer.marks), plates=list(writer.plates))


def _renumbered(parts_cells: list[list[Row]], writer: kit.Writer, shots: list[Row]
                ) -> tuple[list[list[Row]], kit.Writer]:
    """`kit.renumber` over every part at once, each part's cells then put in shot order."""
    flat, writer = kit.renumber([c for p in parts_cells for c in p], writer, shots)
    out, i = [], 0
    for p in parts_cells:
        out.append(sorted(flat[i: i + len(p)], key=lambda c: int(c.get("number") or 0)))
        i += len(p)
    return out, writer


def _neighbours(parts_cells: list[list[Row]], shot_id: str, number: int) -> list[tuple[str, Row]]:
    """(before | after, cell) of the painted panels nearest this shot, as the board stands now (a panel painted
    earlier in the same update included); one at the scene's ends."""
    seen: dict[str, Row] = {}
    for p in parts_cells:
        for c in p:
            if c.get("kind") == "painted" and c.get("path") and str(c["shot_id"]) != shot_id:
                seen.setdefault(str(c["shot_id"]), c)
    cells = sorted(seen.values(), key=lambda c: int(c.get("number") or 0))
    before = [c for c in cells if int(c.get("number") or 0) < number]
    after = [c for c in cells if int(c.get("number") or 0) > number]
    out = []
    if before:
        out.append(("before", before[-1]))
    if after:
        out.append(("after", after[0]))
    return out


def _paint_panel(ctx: RunContext, b: Board, writer: kit.Writer, parts_cells: list[list[Row]], shot: kit.BoardShot,
                 note: str, aspect: str, quality: str) -> tuple[bytes, kit.Panel, list[str], Row | None]:
    """ONE panel painted alone (plan/2026-11-17 §3.2): the one-panel writer, then `panel_prompt` → safe depiction →
    one picture, the place and its neighbouring panels attached (the props are clay stand-ins, plan/2026-11-23c),
    then the board check (F2). → (picture, panel, conflicts, check). Raises `_Failed` with the reason."""
    painter = ctx.ports.images
    if painter is None:
        raise _Failed(NOT_CONFIGURED)
    near = []
    for side, cell in _neighbours(parts_cells, shot.id, shot.number):
        try:
            near.append((side, int(cell["number"]), _download(ctx, "frames", str(cell["path"]))))
        except Exception:
            _log.warning("the panel of shot %s could not be read as a neighbour", cell.get("number"), exc_info=True)
    places = _pictures(ctx, b.image_pictures([shot])[: max(MAX_IMAGE_REFS - len(near), 0)])
    places += _saved_plates(ctx, b, writer, [shot.number])  # plan/2026-11-24d: its stretch's plate
    edit = kit.Edit(kind="change" if writer.panel(shot.number) else "add", number=shot.number, plan=shot.plan,
                    board=writer, before=next((n for s, n, _ in near if s == "before"), None),
                    after=next((n for s, n, _ in near if s == "after"), None), note=note,
                    pictures=[*(p.label for p in places),
                              *(kit.writer_neighbour_label(s, n) for s, n, _ in near)])
    message = kit.writer_message({}, b.colours, edit=edit)
    sent = [*(p.data for p in places), *(d for _, _, d in near)]
    try:
        out = agents.build("board_writer").run(
            {"message": message, "pictures": [{"mime": "image/png", "b64": base64.b64encode(d).decode()}
                                              for d in sent]},
            ctx, max_output=kit.PANEL_WRITER_MAX_OUTPUT)
    except ModelUnavailable:
        raise _Failed(NO_WRITER) from None
    except Exception:
        _log.warning("the one-panel writer failed for shot %s", shot.number, exc_info=True)
        raise _Failed(FAILED) from None
    raw = out.model_dump()
    panel = kit.panel_answer(raw, shot.number)
    if panel is None:
        raise _Failed(f"The board writer gave no panel for shot {shot.number}.")
    panel = replace(panel, shot_id=shot.id, pin=kit.plan_pin(b.row(shot.id)))  # a repaint reuses these words
    refs = [*places, *(Reference(label=kit.neighbour_label(s, n), data=d) for s, n, d in near)]
    labels = [r.label for r in refs]
    prompt = kit.panel_prompt(writer, panel, labels, b.colours, aspect, props=b.prop_names([shot]),
                              places=b.place_names([shot]), views=b.views,
                              vehicles=b.vehicle_line([shot.number], labels), panel_views=b.panel_views(),
                              marks=" ".join(b.ground_words([shot.number])),
                              panel_mark=b.panel_marks([shot.number]).get(shot.number, ""))
    found = safe_depiction.blocking(prompt)
    if found:
        raise _Failed(safe_depiction.frame_error(found))
    try:
        picture = painter(prompt, aspect, refs, quality=quality)
    except ImageRefused as exc:
        raise _Failed(str(exc)) from None
    except Exception:
        _log.warning("the panel of shot %s could not be painted", shot.number, exc_info=True)
        raise _Failed(FAILED) from None
    conflicts = [*kit.Writer.of(raw).conflicts,
                 *kit.writer_findings(kit.Writer(world="", geography="", panels=[panel]), [shot], b.carried(),
                                      b.views, b.panel_views())]
    data, check = _mend(ctx, b, writer, panel, picture.data, refs, aspect, quality)
    line = _still_wrong(shot.number, check)
    return data, panel, [*conflicts, *([line] if line else [])], check


def _sheet(ctx: RunContext, b: Board, cells: list[Row], base: str, tag: str) -> str:
    """The part's numbered sheet drawn again from its stored cells (grid cuts and panels side by side)."""
    shots, pictures = [], {}
    for c in cells:
        sid = str(c["shot_id"])
        known = next((s for s in b.shots if s.id == sid), None)
        shots.append(kit.BoardShot(id=sid, number=int(c.get("number") or 0), slate=known.slate if known else "",
                                   painted=c.get("kind") == "painted", text=str(c.get("text") or "")))
        if c.get("kind") == "painted" and c.get("path"):
            try:
                pictures[sid] = _download(ctx, "frames", str(c["path"]))
            except Exception:
                _log.warning("the panel of shot %s could not be read for the sheet", c.get("number"), exc_info=True)
    path = f"{base}/sheet-{tag}.png"
    ctx.need("files").upload("frames", path, pics.scene_sheet(shots, pictures), "image/png")
    return path


def update(ctx: RunContext, production: Row, world: Row, rows: list[Row], state: Row, job_id: str,
           warn: Callable[[str], None]) -> Row:
    """plan/2026-11-17 §3.1: mend the current board for the scene's shots as they stand, never repainting it whole.
    A changed or added shot's panel is painted ALONE, its neighbours attached (or its earlier picture put back when
    an undo returned its plan, §3.6); a removed shot's cell is dropped; moved shots are put in order; a black plate
    is drawn by code. A locked panel is never repainted. Then every cell and writer panel is renumbered together,
    each touched part's sheet drawn again, and each part written once: a part none of whose cells changed gets the
    person's approval back (§3.3; D2 as recommended: removing or moving a shot changes no picture). A panel that
    fails keeps its old cell (an added shot stays out of date); the others still update. → `{status, updated,
    failed, locked}`."""
    frames, files = ctx.need("frames"), ctx.need("files")
    b = Board(ctx, world, saved=rows[0].get("colours") or {})
    original = [[dict(c) for c in r.get("cells") or []] for r in rows]
    st = kit.stale_cells([c for p in original for c in p], b.shot_rows)
    wanted = {str(x) for x in state.get("shots") or []}
    to_paint = [sid for sid in st.paint if not wanted or sid in wanted]
    now_ids = {str(s["id"]) for s in b.shot_rows}
    parts_cells, writer = _renumbered([[c for c in p if str(c["shot_id"]) in now_ids] for p in original],
                                      _board_writer(rows), b.shot_rows)
    b.ground, _ = mk.check(writer.marks, b.blocking)  # plan/2026-11-24d: the saved spots, for a panel painted alone
    aspect = kit.aspect_of_board(rows[0])
    quality = str(rows[0].get("quality") or kit.DEFAULT_QUALITY)
    tag = job_id[:8]
    changed: set[int] = set()
    updated: list[int] = []
    failed: dict[int, str] = {}

    def put(sid: str, fields: Row, new: Row | None = None) -> None:
        """Write `fields` into every cell of this shot (the overlap panel is in two parts), or insert `new`."""
        hit = False
        for i, cells in enumerate(parts_cells):
            for j, c in enumerate(cells):
                if str(c["shot_id"]) == sid:
                    cells[j] = {**c, **fields}
                    changed.add(i)
                    hit = True
        if not hit and new is not None:
            i = kit.insert_position(parts_cells, b.shot_rows, sid)
            parts_cells[i] = sorted([*parts_cells[i], {**new, **fields}], key=lambda c: int(c.get("number") or 0))
            changed.add(i)

    for sid in to_paint:
        shot, row = b.shot(sid), b.row(sid)
        pin = kit.plan_pin(row)
        cell = next((c for p in parts_cells for c in p if str(c["shot_id"]) == sid), None)
        fresh = kit.new_cell(shot, row, None, source="panel")
        if not shot.painted:  # a black plate: drawn by code, nothing painted
            put(sid, {k: fresh[k] for k in ("kind", "panel", "box", "path", "pin", "text", "source")}, fresh)
            writer = kit.Writer(world=writer.world, geography=writer.geography, conflicts=writer.conflicts,
                                panels=[p for p in writer.panels if p.shot != shot.number],
                                marks=list(writer.marks), plates=list(writer.plates))
            updated.append(shot.number)
            continue
        old_panel = writer.panel(shot.number) if cell is not None and cell.get("kind") == "painted" else None
        history = kit.remember(cell, old_panel) if cell is not None else []
        prev = None
        if cell is not None:  # a picture painted before plan/2026-11-23c carries the old pin
            prev = kit.previous_for(cell, pin) or kit.previous_for(cell, kit.legacy_pin(row))
        back = kit.panel_of(prev.get("panel"), shot.number) if prev else None
        back = replace(back, shot_id=sid, pin=pin) if back is not None else None
        if prev and back is not None:  # §3.6: an undo put this plan back; its picture comes back for free
            put(sid, {"kind": "painted", "path": prev["path"], "pin": pin, "source": "panel", "box": None,
                      "panel": 1, "text": "", "previous": [p for p in history if p.get("pin") != pin]})
            writer = _with_panel(writer, back)
            updated.append(shot.number)
            continue
        note = str((cell or {}).get("note") or "")
        try:
            _beat(ctx, f"Updating the panel of shot {shot.number}")
            data, panel, conflicts, check = _paint_panel(ctx, b, writer, parts_cells, shot, note, aspect, quality)
        except _Failed as exc:
            failed[shot.number] = str(exc)
            continue
        owner = next((str(r["id"]) for r, p in zip(rows, parts_cells, strict=True)
                      if any(str(c["shot_id"]) == sid for c in p)), None)
        owner = owner or str(rows[kit.insert_position(parts_cells, b.shot_rows, sid)]["id"])
        path = f"{production['id']}/boards/{owner}/cell_{sid}-{tag}.png"
        try:
            files.upload("frames", path, data, "image/png")
        except Exception:
            _log.warning("the panel of shot %s could not be stored", shot.number, exc_info=True)
            failed[shot.number] = FAILED
            continue
        put(sid, {"kind": "painted", "path": path, "pin": pin, "source": "panel", "box": None, "panel": 1,
                  "text": "", "previous": history, **({"check": check} if check else {})}, fresh)
        writer = _with_panel(writer, panel, conflicts)
        updated.append(shot.number)

    parts_cells, writer = _renumbered(parts_cells, writer, b.shot_rows)
    done_ids = {str(c["shot_id"]) for p in parts_cells for c in p if int(c.get("number") or 0) in updated}
    for cells in parts_cells:  # `fresh`: what THIS update changed, for the card's "look at it and approve it again"
        for j, c in enumerate(cells):
            if str(c["shot_id"]) in done_ids:
                cells[j] = {**c, "fresh": True}
            elif c.get("fresh"):
                cells[j] = {k: v for k, v in c.items() if k != "fresh"}
    errors =[f"Shot {n} could not be updated: {why}" for n, why in sorted(failed.items())]
    for i, r in enumerate(rows):
        rid = str(r["id"])
        fields: Row = {"cells": parts_cells[i], "writer": writer.dump(), "colours": b.saved_colours,
                       "status": "done", "error": " ".join(errors) or None, "parts": len(rows)}
        if parts_cells[i] != original[i]:  # numbers, order, a dropped or a new picture: the sheet is drawn again
            try:
                fields["sheet_path"] = _sheet(ctx, b, parts_cells[i], f"{production['id']}/boards/{rid}", tag)
            except Exception:
                _log.warning("the sheet of board %s could not be drawn", rid, exc_info=True)
        if i not in changed:
            fields.update(_approval(state, rid))
        frames.save_board(rid, fields)
    status = "partial" if failed and updated else ("failed" if failed else "done")
    out: Row = {"status": status, "updated": sorted(updated), "failed": failed, "locked": st.locked}
    if errors:
        out["error"] = " ".join(errors)
    return out


def _run_update(ctx: RunContext, production: Row, world_of: Callable[[str], Row], state: Row, job_id: str,
                warn: Callable[[str], None]) -> Row:
    frames = ctx.need("frames")
    ids = [str(i) for i in state.get("board_ids") or []]
    rows = [frames.board(i) for i in ids]
    if not ids or any(r is None for r in rows):
        return {"status": "failed", "error": "This board no longer exists."}
    if not frames.claim_board(ids[0]):  # a re-delivery: the first delivery has the board
        return {"status": "skipped"}
    for i in ids[1:]:
        frames.claim_board(i)
    parts_rows = [r for r in rows if r is not None]
    try:
        world = world_of(str(state.get("scene_id") or parts_rows[0]["scene_id"]))
        return update(ctx, production, world, parts_rows, state, job_id, warn)
    except Exception:
        _log.exception("the update of board %s crashed", ids[0])
        for r in parts_rows:  # nothing was written: the board stays as it was, with its approval
            frames.save_board(str(r["id"]), {"status": "done", "error": FAILED, **_approval(state, str(r["id"]))})
        return {"status": "failed", "error": FAILED}


def run(ctx: RunContext, production: Row, world_of: Callable[[str], Row], state: Row, job_id: str,
        warn: Callable[[str], None]) -> Row:
    """The board job. `world_of(scene_id)` is the frame_render system's shared reads."""
    if state.get("update"):
        return _run_update(ctx, production, world_of, state, job_id, warn)
    frames = ctx.need("frames")
    board_id = str(state["board_id"])
    board = frames.board(board_id)
    if board is None:
        return {"status": "failed", "error": "This board no longer exists."}
    if not frames.claim_board(board_id):
        return {"status": "skipped"}
    try:
        world = world_of(str(board["scene_id"]))
        return paint(ctx, production, world, board, state, job_id, warn)
    except Exception:
        _log.exception("board %s crashed", board_id)
        frames.save_board(board_id, {"status": "failed", "error": FAILED})
        return {"status": "failed", "error": FAILED}
