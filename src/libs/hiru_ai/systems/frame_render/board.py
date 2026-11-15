"""The Scene board job (plan/2026-11-14 §3.2-3.3): ONE mannequin storyboard per scene, painted before any first frame.

    state.board_id      the row the API created `queued` (part 1 of a new version), or, for a repaint, the part
                        the API set back to `queued` (its approval cleared)
    state.repaint       true: repaint only some panels of `board_id`, in place (D7, method A); a failure leaves its
                        old picture in force (status `done`, with the error)
    state.shots         with `repaint`: the shot numbers to repaint
    state.carry         a whole repaint: the previous version's part ids, whose notes and locked panels carry over

  claim     queued -> running, so a re-delivery never pays twice
  faces     D4: a face sheet for every on-screen person who lacks one (MEDIUM), for the frames that follow
  writer    `board_writer` reads the scene and every painted shot's PLAN, writes the world, the geography and a
            mannequin panel per shot (`contracts.board`)
  image     per part (D5): `board_prompt` → `safe_depiction.blocking` → `images.edit` at the row's quality (LOW by
            default, D2); a later part gets the previous part's last panel to repeat
  after     cells cut along the painted gutters, one PNG per shot, the numbered sheet drawn by code; all in the
            private `frames` bucket under `<production>/boards/<board>/`

A board is never repainted by itself when a shot changes (the person, 2026-11-13): the API reports it out of date.
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
NO_SOURCE = "The board's picture could not be read. Paint the whole board again."
MAX_IMAGE_REFS = 6  # the place, up to four props, and on a later part the panel it repeats
EDIT_LABEL = "the storyboard sheet to edit"


class Board:
    """One scene's reads, as the board needs them: the frame_compose world, its shots and who each shot shows."""

    def __init__(self, ctx: RunContext, world: Row) -> None:
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
        self.colour_of = {c: kit.COLOURS[i % len(kit.COLOURS)] for i, c in enumerate(self.people)}  # id → colour
        self.colours = {str(self.by_id[c]["name"]): col for c, col in self.colour_of.items()}  # name → colour

    @property
    def painted(self) -> list[kit.BoardShot]:
        return [s for s in self.shots if s.painted]

    def row(self, shot_id: str) -> Row:
        return next(r for r in self.shot_rows if str(r["id"]) == shot_id)

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
    groups = kit.parts_of(b.painted)
    rows = [board]
    if len(groups) > 1:  # D5: the first row is part 1; the job adds the others
        extra = [{"id": str(uuid4()), "production_id": board["production_id"], "scene_id": board["scene_id"],
                  "version": board["version"], "part": i + 1, "parts": len(groups), "status": "running",
                  "job_id": board.get("job_id"), "quality": board.get("quality") or kit.DEFAULT_QUALITY,
                  "created_by": board.get("created_by")} for i in range(1, len(groups))]
        frames.create_boards(extra)
        rows += extra
    colours = {c: col for c, col in b.colour_of.items()}
    done = 0
    previous_last: bytes | None = None
    for i, (row, group) in enumerate(zip(rows, groups, strict=True)):
        rid = str(row["id"])
        numbers = [s.number for s in group]
        refs = _pictures(ctx, b.image_pictures(group))
        if previous_last is not None:
            refs.append(Reference(label=kit.OVERLAP_LABEL, data=previous_last))
        prompt = kit.board_prompt(writer, numbers, [r.label for r in refs], b.colours)
        fields: Row = {"parts": len(groups), "writer": writer.dump(), "colours": colours, "prompt": prompt}
        found = safe_depiction.blocking(prompt)
        if found:
            frames.save_board(rid, {**fields, "status": "refused", "error": safe_depiction.frame_error(found)})
            continue
        try:
            picture = painter(prompt, kit.BOARD_ASPECT, refs, quality=str(row.get("quality") or kit.DEFAULT_QUALITY))
        except ImageRefused as exc:
            frames.save_board(rid, {**fields, "status": "refused", "error": str(exc)})
            continue
        except Exception:
            _log.warning("board %s part %s failed", board_id, i + 1, exc_info=True)
            frames.save_board(rid, {**fields, "status": "failed", "error": FAILED})
            continue
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
        cells, path, sheet = _store_part(ctx, b, rid, str(production["id"]), image, cells_shots, numbers, old, boxes)
        for c in cells:  # a kept panel keeps its old pin: it still shows what it was painted against
            if c["shot_id"] in kept and kept[c["shot_id"]].get("pin"):
                c["pin"] = kept[c["shot_id"]]["pin"]
        last = next((c for c in reversed(cells) if c.get("path")), None)
        previous_last = pics.crop(image, last["box"]) if last else None
        frames.save_board(rid, {**fields, "status": "done", "error": None, "storage_path": path, "sheet_path": sheet,
                                "cells": cells})
        done += 1
    status = "done" if done == len(groups) else ("failed" if not done else "partial")
    return {"status": status, "parts": len(groups), "painted": done, "conflicts": len(writer.conflicts)}


def repaint(ctx: RunContext, production: Row, world: Row, board: Row, state: Row, job_id: str,
            warn: Callable[[str], None]) -> Row:
    """D7, method A: only the given panels of one part, by a masked edit of its picture, in place; every other panel
    stays pixel for pixel. Locked panels are never repainted. A failure keeps the old picture in force (the row goes
    back to `done` with the error). → `{status, repainted}`."""
    frames, painter = ctx.need("frames"), ctx.ports.images
    board_id = str(board["id"])

    def keep(error: str, status: str = "failed") -> Row:
        if board.get("storage_path"):  # the old picture is still a board: only the approval was cleared
            frames.save_board(board_id, {"status": "done", "error": error})
        else:
            frames.save_board(board_id, {"status": "failed", "error": error})
        return {"status": status, "error": error}

    if painter is None:
        return keep(NOT_CONFIGURED)
    if not board.get("storage_path"):
        return keep(NO_SOURCE)
    b = Board(ctx, world)
    ensure_faces(ctx, production, world["canon"], b.people, job_id, warn)
    cells = [dict(c) for c in board.get("cells") or []]
    wanted = {int(n) for n in state.get("shots") or []}
    redo = [c for c in cells if c.get("kind") == "painted" and int(c["number"]) in wanted and not c.get("locked")
            and c.get("box")]
    if not redo:
        return keep("No unlocked panel to repaint.")
    try:
        image = _download(ctx, "frames", str(board["storage_path"]))
    except Exception:
        _log.warning("board %s could not be read", board_id, exc_info=True)
        return keep(NO_SOURCE)
    notes = {int(c["number"]): str(c.get("note") or "") for c in redo}
    try:
        fresh = write(ctx, b, notes)
    except ModelUnavailable:
        return keep(NO_WRITER)
    except Exception:
        _log.warning("board writer failed for repaint %s", board_id, exc_info=True)
        return keep(FAILED)
    numbers_all = [int(c["number"]) for c in sorted((c for c in cells if c.get("panel")), key=lambda c: c["panel"])]
    numbers = [int(c["number"]) for c in redo]
    writer = kit.Writer.of(board.get("writer") or {}).merged(fresh, numbers)
    painted_shots = [s for s in b.shots if s.number in numbers_all]
    refs = [Reference(label=EDIT_LABEL, data=image), *_pictures(ctx, b.image_pictures(painted_shots))]
    prompt = kit.repaint_prompt(writer, numbers_all, numbers, [r.label for r in refs], b.colours)
    found = safe_depiction.blocking(prompt)
    if found:
        return keep(safe_depiction.frame_error(found), "refused")
    mask = pics.repaint_mask(pics.image_size(image), [c["box"] for c in redo])
    try:
        picture = painter(prompt, kit.BOARD_ASPECT, refs, quality=str(board.get("quality") or kit.DEFAULT_QUALITY),
                          mask=mask)
    except ImageRefused as exc:
        return keep(str(exc), "refused")
    except Exception:
        _log.warning("repaint of board %s failed", board_id, exc_info=True)
        return keep(FAILED)
    files = ctx.need("files")
    base = f"{production['id']}/boards/{board_id}"
    tag = job_id[:8]  # new files: the old picture stays whole until the new one is recorded
    files.upload("frames", f"{base}/board-{tag}.png", picture.data, "image/png")
    crops: dict[str, bytes] = {}
    by_number = {s.number: s for s in b.shots}
    redo_ids = {str(c["shot_id"]) for c in redo}
    for c in cells:
        if not c.get("box"):
            continue
        data = pics.crop(picture.data, c["box"])
        path = f"{base}/cell_{int(c['number']):03d}-{tag}.png"
        files.upload("frames", path, data, "image/png")
        crops[str(c["shot_id"])] = data
        c["path"] = path
        if str(c["shot_id"]) in redo_ids:
            shot = by_number.get(int(c["number"]))
            if shot is not None:
                c["pin"] = kit.plan_pin(b.row(shot.id))
    shots = [s for s in b.shots if s.id in {str(c["shot_id"]) for c in cells}]
    sheet = pics.scene_sheet(shots, crops)
    files.upload("frames", f"{base}/sheet-{tag}.png", sheet, "image/png")
    frames.save_board(board_id, {"writer": writer.dump(), "prompt": prompt, "status": "done", "error": None,
                                 "storage_path": f"{base}/board-{tag}.png", "sheet_path": f"{base}/sheet-{tag}.png",
                                 "cells": cells})
    return {"status": "done", "repainted": sorted(numbers)}


def run(ctx: RunContext, production: Row, world_of: Callable[[str], Row], state: Row, job_id: str,
        warn: Callable[[str], None]) -> Row:
    """The board job. `world_of(scene_id)` is the frame_render system's shared reads."""
    frames = ctx.need("frames")
    board_id = str(state["board_id"])
    board = frames.board(board_id)
    if board is None:
        return {"status": "failed", "error": "This board no longer exists."}
    if not frames.claim_board(board_id):
        return {"status": "skipped"}
    try:
        world = world_of(str(board["scene_id"]))
        if state.get("repaint"):
            return repaint(ctx, production, world, board, state, job_id, warn)
        return paint(ctx, production, world, board, state, job_id, warn)
    except Exception:
        _log.exception("board %s crashed", board_id)
        frames.save_board(board_id, {"status": "failed", "error": FAILED})
        return {"status": "failed", "error": FAILED}
