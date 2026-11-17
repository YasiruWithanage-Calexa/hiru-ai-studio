"""The Scene board job (plan/2026-11-14 §3.2-3.3): ONE mannequin storyboard per scene, painted before any first frame.

    state.board_id      a whole board: the row the API created `queued` (part 1 of a new version)
    state.carry         a whole repaint: the previous version's part ids, whose notes and locked panels carry over
    state.update        true: update the current board (plan/2026-11-17, `update`): `board_ids` (every part, set
                        `queued` by the API with its approval cleared), `scene_id`, `shots` (shot ids; empty = all
                        out of date) and `approvals` (board id → the approval cleared, written back to a part none
                        of whose cells changed)

  claim     queued -> running, so a re-delivery never pays twice
  faces     D4: a face sheet for every on-screen person who lacks one (MEDIUM), for the frames that follow
  writer    `board_writer` reads the scene and every painted shot's PLAN, writes the world, the geography and a
            mannequin panel per shot (`contracts.board`)
  image     per part (D5): `board_prompt` → `safe_depiction.blocking` → `images.edit` at the row's quality (LOW by
            default, D2); a later part gets the previous part's last panel to repeat
  after     cells cut along the painted gutters, one PNG per shot, the numbered sheet drawn by code; all in the
            private `frames` bucket under `<production>/boards/<board>/`

  update    an edited or added shot's panel painted ALONE with its neighbours attached (one writer call and one
            picture each); a removed or moved shot only tidies the cells; nothing is ever pasted over another panel
            (the image model does not honour a mask: lab/panel_edit run_001, D3)

A board is never repainted by itself when a shot changes (the person, 2026-11-13): the API reports it out of date and
a person presses Update board.
"""
from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from contracts import board as kit
from contracts import safe_depiction
from contracts.canon import look_sheet_path, named_in
from contracts.frame_brief import sheet_path
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.ports import ImageRefused, Reference
from hiru_ai.systems.frame_render import pictures as pics
from hiru_ai.systems.frame_render.faces import ensure_faces

_log = logging.getLogger(__name__)
Row = dict[str, Any]
FAILED = "The scene board could not be made. Try again in a moment."
NOT_CONFIGURED = "Image generation is not set up on this server."
NO_WRITER = "The board writer is not set up on this server."
NOTHING = "Every shot of this scene is a black plate: there is nothing to paint."
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
        self.shots = kit.board_shots(self.scene, self.shot_rows, world.get("lines") or [],
                                     {k: list(v.values()) for k, v in self.seen.items()}, plates)
        self.by_id = {str(c["id"]): c for c in world["canon"]}
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

    @property
    def painted(self) -> list[kit.BoardShot]:
        return [s for s in self.shots if s.painted]

    def row(self, shot_id: str) -> Row:
        return next(r for r in self.shot_rows if str(r["id"]) == shot_id)

    def shot(self, shot_id: str) -> kit.BoardShot:
        return next(s for s in self.shots if s.id == shot_id)

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
        return {"name": row["name"], "look": self._card(loc).get("look", ""), "spots": spots}, row

    def props(self, shots: list[kit.BoardShot]) -> list[Row]:
        """The props these shots' plans name, as canon rows."""
        text = self._plan_text(shots)
        return [c for c in self.world["canon"] if c.get("kind") == "prop" and named_in(str(c.get("name") or ""), text)]

    def people_rows(self) -> list[Row]:
        looks, conditions = self.world.get("looks") or {}, self.world.get("conditions") or {}
        out = []
        for cid in self.people:
            look = looks.get(cid) or {}
            out.append({"name": self.by_id[cid]["name"], "appearance": self._card(cid).get("appearance", ""),
                        "outfit": look.get("outfit", ""), "hair": look.get("hair", ""),
                        "accessories": look.get("accessories", ""), "scene_condition": conditions.get(cid, "")})
        return out

    def writer_pictures(self) -> list[tuple[str, str]]:
        """(label, references-bucket path) the writer reads: each person's look sheet (else base sheet), the place, the
        props. The board IMAGE gets only the place and the props (it has no faces)."""
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
        return out[: kit.MAX_WRITER_PICTURES]

    def image_pictures(self, shots: list[kit.BoardShot]) -> list[tuple[str, str]]:
        _, loc = self.place()
        out = [(f"the location plate for {loc['name']}", sheet_path(loc))] if loc and sheet_path(loc) else []
        out += [(f"the reference sheet for {p['name']}", sheet_path(p)) for p in self.props(shots) if sheet_path(p)]
        return out[: MAX_IMAGE_REFS - 1]

    def bundle(self, labels: list[str]) -> Row:
        place, _ = self.place()
        props = [{"name": p["name"], "details": self._card(str(p["id"])).get("details", "")}
                 for p in self.props(self.painted)]
        return kit.writer_bundle(self.scene, self.shots, self.people_rows(), place, props, labels)


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
    return kit.Writer.of(out.model_dump())


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


def paint(ctx: RunContext, production: Row, world: Row, board: Row, state: Row, job_id: str,
          warn: Callable[[str], None]) -> Row:
    """A whole board (every part) for a new version. → `{status, parts, error?}`."""
    frames, painter = ctx.need("frames"), ctx.ports.images
    board_id = str(board["id"])
    if painter is None:
        frames.save_board(board_id, {"status": "failed", "error": NOT_CONFIGURED})
        return {"status": "failed", "error": NOT_CONFIGURED}
    b = Board(ctx, world)
    if not b.painted:
        frames.save_board(board_id, {"status": "failed", "error": NOTHING})
        return {"status": "failed", "error": NOTHING}
    ensure_faces(ctx, production, world["canon"], b.people, job_id, warn)  # D4
    carry = [frames.board(str(i)) for i in state.get("carry") or []]
    old: dict[str, Row] = {}
    for prev in (r for r in carry if r):
        for c in prev.get("cells") or []:
            old.setdefault(str(c.get("shot_id")), {**c, "_board": prev})
    notes = {int(c["number"]): str(c.get("note") or "") for c in old.values()
             if c.get("note") and not c.get("locked")}
    try:
        writer = write(ctx, b, notes or None)
    except ModelUnavailable:
        frames.save_board(board_id, {"status": "failed", "error": NO_WRITER})
        return {"status": "failed", "error": NO_WRITER}
    except Exception:
        _log.warning("board writer failed for board %s", board_id, exc_info=True)
        frames.save_board(board_id, {"status": "failed", "error": FAILED})
        return {"status": "failed", "error": FAILED}
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
    done = 0
    previous_last: bytes | None = None
    for i, (row, group) in enumerate(zip(rows, groups, strict=True)):
        rid = str(row["id"])
        numbers = [s.number for s in group]
        refs = _pictures(ctx, b.image_pictures(group))
        if previous_last is not None:
            refs.append(Reference(label=kit.OVERLAP_LABEL, data=previous_last))
        prompt = kit.board_prompt(writer, numbers, [r.label for r in refs], b.colours, aspect)
        fields: Row = {"parts": len(groups), "writer": writer.dump(), "colours": colours, "prompt": prompt}
        found = safe_depiction.blocking(prompt)
        if found:
            frames.save_board(rid, {**fields, "status": "refused", "error": safe_depiction.frame_error(found)})
            continue
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
            last = next((c for c in reversed(cells) if c.get("path")), None)
            previous_last = pics.crop(image, last["box"]) if last else None
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
    writer = kit.Writer.of(rows[0].get("writer") or {})
    have = {p.shot for p in writer.panels}
    for r in rows[1:]:
        for p in kit.Writer.of(r.get("writer") or {}).panels:
            if p.shot not in have:
                writer.panels.append(p)
                have.add(p.shot)
    writer.panels.sort(key=lambda p: p.shot)
    return writer


def _with_panel(writer: kit.Writer, panel: kit.Panel, conflicts: list[str] | None = None) -> kit.Writer:
    panels = sorted([*(p for p in writer.panels if p.shot != panel.shot), panel], key=lambda p: p.shot)
    return kit.Writer(world=writer.world, geography=writer.geography, panels=panels,
                      conflicts=list(dict.fromkeys([*writer.conflicts, *(conflicts or [])])))


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
                 note: str, aspect: str, quality: str) -> tuple[bytes, kit.Panel, list[str]]:
    """ONE panel painted alone (plan/2026-11-17 §3.2): the one-panel writer, then `panel_prompt` → safe depiction →
    one picture, the place, the shot's props and its neighbouring panels attached. → (picture, panel, conflicts).
    Raises `_Failed` with the reason."""
    painter = ctx.ports.images
    if painter is None:
        raise _Failed(NOT_CONFIGURED)
    near = []
    for side, cell in _neighbours(parts_cells, shot.id, shot.number):
        try:
            near.append((side, int(cell["number"]), _download(ctx, "frames", str(cell["path"]))))
        except Exception:
            _log.warning("the panel of shot %s could not be read as a neighbour", cell.get("number"), exc_info=True)
    places = _pictures(ctx, b.image_pictures([shot])[: MAX_IMAGE_REFS - len(near)])
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
    refs = [*places, *(Reference(label=kit.neighbour_label(s, n), data=d) for s, n, d in near)]
    prompt = kit.panel_prompt(writer, panel, [r.label for r in refs], b.colours, aspect)
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
    return picture.data, panel, kit.Writer.of(raw).conflicts


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
    aspect = kit.aspect_of_board(rows[0])
    quality = str(rows[0].get("quality") or kit.DEFAULT_QUALITY)
    tag = job_id[:8]
    changed: set[int] = set()
    updated: list[int] = []
    failed: dict[int, str] = {}
    if any(b.shot(sid).painted for sid in to_paint):
        ensure_faces(ctx, production, world["canon"], b.people, job_id, warn)  # D4, for the frames that follow

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
                                panels=[p for p in writer.panels if p.shot != shot.number])
            updated.append(shot.number)
            continue
        old_panel = writer.panel(shot.number) if cell is not None and cell.get("kind") == "painted" else None
        history = kit.remember(cell, old_panel) if cell is not None else []
        prev = kit.previous_for(cell, pin) if cell is not None else None
        back = kit.panel_of(prev.get("panel"), shot.number) if prev else None
        if prev and back is not None:  # §3.6: an undo put this plan back; its picture comes back for free
            put(sid, {"kind": "painted", "path": prev["path"], "pin": pin, "source": "panel", "box": None,
                      "panel": 1, "text": "", "previous": [p for p in history if p.get("pin") != pin]})
            writer = _with_panel(writer, back)
            updated.append(shot.number)
            continue
        note = str((cell or {}).get("note") or "")
        try:
            data, panel, conflicts = _paint_panel(ctx, b, writer, parts_cells, shot, note, aspect, quality)
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
                  "text": "", "previous": history}, fresh)
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
