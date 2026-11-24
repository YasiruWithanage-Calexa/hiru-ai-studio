"""A location's views sheet (plan/2026-11-24; the person's method, proven in `lab/location_views`).

    state.reference_entity_id   the location
    state.reference_kind        "views"
    state.views                 a person's six views `[{name, what}]` (edited on the canon page); absent: written
    state.views_layout          their layout and light (kept from the sheet they edited); absent: written
    state.views_context         `{within: [canon ids], geographies: [...], scenes: [...]}`: what the API found about the
                                scenes set at this location (the places that stand in it, their boards' geography)

  write   the `views_writer` agent: the layout, the light and six views (skipped when a person gave the views)
  paint   `contracts.canon.views_sheet_prompt`, the location plate and the plates of the places in it attached,
          1536x1024 at MEDIUM
  cut     `pictures.cell_boxes` (6 cells, 3x2); a sheet that does not cut clean is refused, never stored
  store   the `references` bucket, a `reference_assets` entry of kind `views` with each view's name, words and box
"""
from __future__ import annotations

import logging
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
FAILED = "The location views could not be made. Try again in a moment."
NO_PLATE = "Paint the location plate first: the views are painted from it."
NO_WRITER = "The views writer is not set up on this server."
BAD_CUT = "The views came out in a different layout than was asked. Make the location views again."


def _now() -> str:
    return datetime.now(UTC).isoformat()


def render_views(ctx: RunContext, production: Row, canon: list[Row], entity_id: str, state: Row, job_id: str) -> Row:
    """One views sheet for a location's current card. -> `{status, entity_id?, error?}`."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    by_id = {str(c["id"]): c for c in canon}
    row = by_id.get(entity_id)
    current = (row or {}).get("current")
    if not row or not current or row.get("kind") != "location":
        return {"status": "failed", "error": "Only a place with a card has location views."}
    if not sheet_path(row):
        return {"status": "failed", "error": NO_PLATE}
    if paint is None:
        return {"status": "failed", "error": "Image generation is not set up on this server."}
    context = state.get("views_context") or {}
    within = [by_id[str(i)] for i in context.get("within") or [] if str(i) in by_id and str(i) != entity_id]
    given = [v for v in state.get("views") or [] if isinstance(v, dict) and v.get("name") and v.get("what")]
    if len(given) == kit.VIEWS_COUNT:
        views = [{"name": str(v["name"]), "what": str(v["what"])} for v in given]
        made = state.get("views_layout") or {}
        layout, light = str(made.get("layout") or ""), str(made.get("light") or "")
    else:
        try:
            out = agents.build("views_writer").run({
                "place": _place(row),
                "spots": [_place(c) for c in canon if str(c.get("parent_id") or "") == entity_id],
                "within": [_place(c) for c in within],
                "geographies": [str(g) for g in context.get("geographies") or []][:6],
                "scenes": [str(s) for s in context.get("scenes") or []][:12]}, ctx)
        except ModelUnavailable:
            return {"status": "failed", "error": NO_WRITER}
        except Exception:
            _log.warning("the views writer failed for %s", entity_id, exc_info=True)
            return {"status": "failed", "error": FAILED}
        answer = out.model_dump()
        views = [{"name": v["name"], "what": v["what"]} for v in answer["views"]][: kit.VIEWS_COUNT]
        layout, light = str(answer.get("layout") or ""), str(answer.get("light") or "")
        if len(views) != kit.VIEWS_COUNT:
            return {"status": "failed", "error": f"The views writer gave {len(views)} views, not six. Try again."}
    plates = [(f"the location plate for {row['name']}", sheet_path(row))]
    plates += [(f"the location plate for {c['name']}", sheet_path(c)) for c in within if sheet_path(c)]
    refs = []
    for label, path in plates:
        try:
            refs.append(Reference(label=label, data=bytes(files.download("references", path))))
        except Exception:
            _log.warning("%s could not be read", label, exc_info=True)
    if not refs or refs[0].label != plates[0][0]:
        return {"status": "failed", "error": NO_PLATE}
    prompt = kit.views_sheet_prompt(str(row["name"]), [r.label for r in refs], layout, light, views)
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
    asset = {"kind": kit.VIEWS_SHEET_KIND, "path": path, "version": current.get("version"), "job_id": job_id,
             "created_at": _now(), "layout": layout, "light": light, "prompt": prompt,
             "views": [{"n": i, "name": v["name"], "what": v["what"], "box": [int(x) for x in boxes[i - 1]]}
                       for i, v in enumerate(views, 1)]}
    frames.add_reference_asset(str(current["id"]), kit.keep_assets([asset, *(current.get("reference_assets") or [])]))
    return {"status": "done", "entity_id": entity_id, "version": current.get("version")}


def _place(row: Row) -> Row:
    return {"name": str(row.get("name") or ""), "look": str((((row.get("current") or {}).get("card") or {})
                                                            .get("look")) or "")}
