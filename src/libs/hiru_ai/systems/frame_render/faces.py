"""Face sheets (plan/2026-11-14 §3.1): six head-and-shoulder views of one character, painted at MEDIUM from the portrait
cut out of their base sheet, stored as `kind: "face"` on the current card's `reference_assets`. Every frame of a person
the camera sees attaches it FIRST (`contracts.frame_brief.plan_references`), board or not.

Made only on request (`state.reference_kind = "face"`). A Scene board or a frame from a board no longer makes the
missing ones (2026-11-22, was D4): boards of different scenes painted in parallel each paid for the same person's
sheet. They name who has none (`contracts.canon.missing_faces`) and a person makes it.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from contracts import safe_depiction
from contracts.canon import (
    FACE_SHEET_KIND,
    FACE_SHEET_QUALITY,
    SHEET_ASPECT,
    face_sheet_prompt,
    keep_assets,
)
from contracts.frame_brief import sheet_path
from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import ImageRefused, Reference
from hiru_ai.systems.frame_render.pictures import portrait_crop

_log = logging.getLogger(__name__)
Row = dict[str, Any]
FAILED = "The face sheet could not be made. Try again in a moment."
NOT_CONFIGURED = "Image generation is not set up on this server."


def render_face(ctx: RunContext, production: Row, canon: list[Row], entity_id: str, job_id: str) -> Row:
    """A face sheet for a character's CURRENT card → the `references` bucket, newest first among its face sheets. The
    row in `canon` is updated in place, so the frames of the same job attach it."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    row = next((c for c in canon if str(c["id"]) == entity_id), None)
    current = (row or {}).get("current")
    if not row or not current:
        return {"status": "failed", "error": "This canon entry has no card yet."}
    if row.get("kind") != "character":
        return {"status": "failed", "error": "Only a character has a face sheet."}
    base = sheet_path(row)
    if not base:
        return {"status": "failed", "error": f"Paint {row['name']}'s base sheet first: the face sheet is made from it."}
    if paint is None:
        return {"status": "failed", "error": NOT_CONFIGURED}
    prompt = face_sheet_prompt()
    if safe_depiction.blocking(prompt):  # a fixed prompt: never true, kept so every paint is scanned
        return {"status": "refused", "error": safe_depiction.frame_error(safe_depiction.blocking(prompt))}
    try:
        portrait = portrait_crop(bytes(files.download("references", base)))
    except Exception:
        _log.warning("base sheet of %s could not be read", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    try:
        picture = paint(prompt, SHEET_ASPECT, [Reference(label=f"the portrait of {row['name']}", data=portrait)],
                        sheet=True, quality=FACE_SHEET_QUALITY)
    except ImageRefused as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _log.warning("face sheet for %s failed", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    path = f"{production['id']}/{entity_id}/{current['id']}-face-{job_id[:8]}.png"
    files.upload("references", path, picture.data, picture.mime)
    assets = keep_assets([{"path": path, "kind": FACE_SHEET_KIND, "version": current.get("version"),
                           "job_id": job_id, "created_at": datetime.now(UTC).isoformat()},
                          *(current.get("reference_assets") or [])])
    frames.add_reference_asset(str(current["id"]), assets)
    current["reference_assets"] = assets
    return {"status": "done", "entity_id": entity_id, "kind": FACE_SHEET_KIND, "version": current.get("version")}
