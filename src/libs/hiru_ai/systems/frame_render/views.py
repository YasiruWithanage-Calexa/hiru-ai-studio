"""A place's views sheet (plan/2026-11-24; plan/2026-11-24c: place views by type, proven in `lab/place_views`).

    state.reference_entity_id   the place (a location card of any class, a vehicle too)
    state.reference_kind        "views"
    state.views                 a person's six views `[{name, camera?, sees?, what?}]` (edited on the canon page);
                                absent: written
    state.views_layout          the edited sheet's `{layout, light, empty, answers}`, kept; absent: written
    state.views_answers         a person's three answers `{sides, moves, size}` set before writing (D1); they win
    state.views_context         `{within, comes_and_goes: [canon ids], geographies, scenes: [text]}`: what the API found
                                about the scenes set there (the fixed places in it, the vehicles that come and go)

  write   the `views_writer` agent: three answers (they pick one of four templates), the layout, the empty spaces and
          one view per slot, with the plate as a picture when there is one; `contracts.canon.view_findings` checks it
          and asks ONCE more with the findings; still failing, the views are stored with their findings (never silent)
  paint   `contracts.canon.views_sheet_prompt` (the lab's words, dry even light), the place's own plate attached when
          it has one (painted from its card's words when not); vehicles' plates are never attached to a place's sheet
  cut     `pictures.cell_boxes` (6 cells, 3x2); a sheet that does not cut clean is refused, never stored
  store   the `references` bucket, a `reference_assets` entry of kind `views` with its answers, template, empty spaces,
          findings and each view's slot, words and box
"""
from __future__ import annotations

import base64
import io
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from contracts import canon as kit
from contracts import safe_depiction
from contracts.frame_brief import sheet_path
from hiru_ai.core import agents
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.ports import ImageRefused, Reference
from hiru_ai.systems.frame_render import pictures as pics

_log = logging.getLogger(__name__)
Row = dict[str, Any]
FAILED = "The views could not be made. Try again in a moment."
NO_WRITER = "The views writer is not set up on this server."
BAD_CUT = "The views came out in a different layout than was asked. Make the views again."
WRITER_SIDE = 1024  # the lab's `data_url`: the plate shrunk to 1024 px, JPEG 85


def _now() -> str:
    return datetime.now(UTC).isoformat()


def render_views(ctx: RunContext, production: Row, canon: list[Row], entity_id: str, state: Row, job_id: str) -> Row:
    """One views sheet for a place's current card. -> `{status, entity_id?, findings?, error?}`."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    by_id = {str(c["id"]): c for c in canon}
    row = by_id.get(entity_id)
    current = (row or {}).get("current")
    if not row or not current or row.get("kind") != "location":
        return {"status": "failed", "error": "Only a place with a card has views."}
    if paint is None:
        return {"status": "failed", "error": "Image generation is not set up on this server."}
    context = state.get("views_context") or {}
    scenes = [str(s) for s in context.get("scenes") or []][:12]
    look = _look(row)
    plate = _plate(ctx, row)
    given_answers = _answers(state.get("views_answers"))
    given = [v for v in state.get("views") or [] if isinstance(v, Mapping) and v.get("name")
             and (v.get("what") or v.get("sees"))]
    if len(given) == kit.VIEWS_COUNT:  # a person's views, painted as given (plan/2026-11-24 Q2)
        made = state.get("views_layout") or {}
        answers = given_answers or _answers(made.get("answers"))
        written: Row = {"answers": answers or {}, "layout": str(made.get("layout") or ""),
                        "light": str(made.get("light") or ""),
                        "empty": [str(e) for e in made.get("empty") or [] if str(e).strip()],
                        "views": [{"slot": str(v["name"]), "camera": str(v.get("camera") or ""),
                                   "sees": str(v.get("sees") or ""), "what": str(v.get("what") or "")}
                                  for v in given]}
        template = _template(answers, [v["slot"] for v in written["views"]])
        findings = kit.view_findings(written, look, scenes) if answers else []
    else:
        inp = {"place": {"name": str(row.get("name") or ""), "look": look},
               "vehicle": row.get("class") == "vehicle",
               "spots": [_place(c) for c in canon if str(c.get("parent_id") or "") == entity_id],
               "within": [_place(by_id[i]) for i in _ids(context.get("within"), by_id, entity_id)],
               "comes_and_goes": [_place(by_id[i]) for i in _ids(context.get("comes_and_goes"), by_id, entity_id)],
               "geographies": [str(g) for g in context.get("geographies") or []][:6],
               "scenes": scenes, "picture": _writer_picture(plate[1]) if plate else None,
               "answers": given_answers}
        try:
            written = _write(ctx, inp, given_answers)
        except ModelUnavailable:
            return {"status": "failed", "error": NO_WRITER}
        except Exception:
            _log.warning("the views writer failed for %s", entity_id, exc_info=True)
            return {"status": "failed", "error": FAILED}
        findings = kit.view_findings(written, look, scenes)
        if findings:  # §2.3: ONE re-ask with the findings as a list
            try:
                again = _write(ctx, {**inp, "findings": findings}, given_answers)
                left = kit.view_findings(again, look, scenes)
                if len(again["views"]) == kit.VIEWS_COUNT:
                    written, findings = again, left
            except Exception:  # the first answer stands, with its findings shown
                _log.warning("the views writer's second answer failed for %s", entity_id, exc_info=True)
        template = kit.view_template(written["answers"])
    views = written["views"][: kit.VIEWS_COUNT]
    if len(views) != kit.VIEWS_COUNT:
        return {"status": "failed", "error": f"The views writer gave {len(views)} views, not six. Try again."}
    label = f"the {'vehicle' if template == 'vehicle' else 'location'} plate for {row['name']}"
    refs = [Reference(label=label, data=plate[1])] if plate else []
    prompt = kit.views_sheet_prompt(str(row["name"]), look, label if refs else "", template,
                                    str(written.get("layout") or ""), written.get("empty") or [], views)
    found = safe_depiction.blocking(prompt)
    if found:
        return {"status": "refused", "error": safe_depiction.frame_error(found)}
    try:
        picture = paint(prompt, kit.VIEWS_ASPECT, refs, quality=kit.VIEWS_SHEET_QUALITY)
    except ImageRefused as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _log.warning("views sheet for %s failed", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    try:
        boxes = pics.cell_boxes(picture.data, kit.VIEWS_COUNT)
        bad = pics.cut_problems(picture.data, boxes)
    except Exception:  # a picture that cannot be read is no sheet
        _log.warning("the views sheet for %s could not be cut", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    if bad:  # never a view with two cells in it or an empty one
        return {"status": "failed", "error": BAD_CUT}
    path = f"{production['id']}/{entity_id}/views/{current['id']}-{job_id[:8]}.png"
    files.upload("references", path, picture.data, picture.mime)
    answers = written.get("answers") or {}
    asset = {"kind": kit.VIEWS_SHEET_KIND, "path": path, "version": current.get("version"), "job_id": job_id,
             "created_at": _now(), "layout": str(written.get("layout") or ""), "light": str(written.get("light") or ""),
             "answers": {k: answers[k] for k in ("sides", "moves", "size", "why") if k in answers},
             "template": template, "empty": list(written.get("empty") or []), "findings": findings,
             "prompt": prompt,
             "views": [{"n": i, "name": str(v.get("slot") or v.get("name")), "camera": str(v.get("camera") or ""),
                        "sees": str(v.get("sees") or ""), "what": kit.view_words(v),
                        "box": [int(x) for x in boxes[i - 1]]} for i, v in enumerate(views, 1)]}
    frames.add_reference_asset(str(current["id"]), kit.keep_assets([asset, *(current.get("reference_assets") or [])]))
    return {"status": "done", "entity_id": entity_id, "version": current.get("version"), "findings": findings}


def _write(ctx: RunContext, inp: Row, given: Row | None) -> Row:
    """The writer's answer as a plain dict; a person's answers replace the writer's (D1), its `why` kept."""
    out = agents.build("views_writer").run(inp, ctx).model_dump()
    if given:
        out["answers"] = {**out.get("answers", {}), **given}
    return out


def _answers(raw: Any) -> Row | None:
    """Three answers `{sides, moves, size}` read from a request or a kept sheet; None when they are not all there."""
    if not isinstance(raw, Mapping):
        return None
    sides, size, moves = str(raw.get("sides") or ""), str(raw.get("size") or ""), raw.get("moves")
    if sides not in kit.VIEW_SIDES or size not in kit.VIEW_SIZES or not isinstance(moves, bool):
        return None
    return {"sides": sides, "moves": moves, "size": size}


def _template(answers: Row | None, slots: list[str]) -> str:
    """The template of a person's views: their answers', else the one whose slots they keep (a built sheet's six names
    fit none: painted as they are, under the outside head)."""
    if answers:
        return kit.view_template(answers)
    return next((t for t in kit.VIEW_TEMPLATES if kit.template_slots(t) == slots), "outside")


def _ids(raw: Any, by_id: Mapping[str, Row], entity_id: str) -> list[str]:
    return [str(i) for i in raw or [] if str(i) in by_id and str(i) != entity_id]


def _plate(ctx: RunContext, row: Row) -> tuple[str, bytes] | None:
    """The place's own plate (path, bytes), or None: a place without one is painted from its card's words (§2.4)."""
    path = sheet_path(row)
    if not path:
        return None
    try:
        return path, bytes(ctx.need("files").download("references", path))
    except Exception:
        _log.warning("the plate of %s could not be read", row.get("name"), exc_info=True)
        return None


def _writer_picture(data: bytes) -> Row | None:
    """The plate as the writer sees it (the lab's `data_url`: 1024 px, JPEG 85); None when it cannot be read."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((WRITER_SIDE, WRITER_SIDE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    except Exception:
        _log.warning("the plate could not be shrunk for the views writer", exc_info=True)
        return None
    return {"mime": "image/jpeg", "b64": base64.b64encode(buf.getvalue()).decode()}


def _look(row: Row) -> str:
    return str((((row.get("current") or {}).get("card") or {}).get("look")) or "")


def _place(row: Row) -> Row:
    return {"name": str(row.get("name") or ""), "look": _look(row)}
