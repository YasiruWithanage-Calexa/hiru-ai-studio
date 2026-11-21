"""The Camera agent's answer into a shot's design (plan/2026-11-20c D5, D10). No migration: `shots.design` is jsonb.

    recommended_from(c, base)        -> CameraSettings: the panel's eight fields in the catalogue's words (the size and
                                        the light stay the planner's), plus support, height, focus, composition, time
    camera_block(c, ...)             -> `design.camera`: the agent's design, its sentence, the scene's language
    merged(design, c, ...)           -> the design row with both, or the fallback when the clip could not be designed
    current_of(design)               -> the clip's camera as it stands, in the agent's slugs (a one-shot brief, the
                                        gates)

A person's changes stay in `shots.camera_overrides`; nothing here writes them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from contracts import camera as cam
from contracts.producer import CameraSettings

Row = dict[str, Any]
DESIGNED = "designed"
NOT_DESIGNED = "not designed"  # D10: still faulty after the repair: the rule recommendation stands
BLOCK_KEYS = ("moment", "intensity", "power", "angle_reason", "move", "direction", "speed", "start_s", "end_s",
              "trigger", "motivation", "opens_on", "lands_on",
              "end_size", "rack_from", "rack_to", "rack_at_s", "composition_note", "omni", "why", "camera_sentence")


def now() -> str:
    return datetime.now(UTC).isoformat()


def recommended_from(c: Mapping[str, Any], base: CameraSettings) -> CameraSettings:
    """The agent's design in the panel's words. The size (`framing`) and the light are kept from `base` (D4: the
    planner's size; lighting is not the agent's job)."""
    move = str(c.get("move") or "hold")
    speed = "none" if move in cam.STILL_MOVES else (str(c.get("speed") or "slow") if c.get("speed") != "none"
                                                     else "slow")
    data = {**base.model_dump(),
            "angle": cam.label_of("angle", str(c.get("angle") or "eye_level")),
            "lens": str(c.get("lens") or base.lens), "aperture": str(c.get("aperture") or base.aperture),
            "movement": cam.label_of("movement", move), "speed": cam.label_of("speed", speed),
            "axis": cam.label_of("axis", str(c.get("axis") or "side_a")),
            "support": cam.label_of("support", str(c.get("support") or "")) if c.get("support") else "",
            "height": cam.label_of("height", str(c.get("height") or "")) if c.get("height") else "",
            "focus": cam.label_of("focus", str(c.get("focus") or "")) if c.get("focus") else "",
            "composition": cam.label_of("composition", str(c.get("composition") or "")) if c.get("composition")
            else "",
            "time": cam.label_of("time", str(c.get("time") or "")) if c.get("time") else ""}
    return CameraSettings.model_validate(data)


def camera_block(c: Mapping[str, Any], *, language: str, model: str, job_id: str, arc: str = "",
                 peak: str = "") -> Row:
    block: Row = {k: c.get(k) for k in BLOCK_KEYS if k in c}
    scene: Row = {k: v for k, v in (("arc", arc), ("peak_slate", peak)) if v}  # plan/2026-11-20d §6: the scene's arc
    return {**block, "language": language, **scene, "model": model, "job_id": job_id, "state": DESIGNED,
            "designed_at": now()}


def merged(design: Mapping[str, Any], c: Mapping[str, Any] | None, *, base: CameraSettings, language: str,
           model: str, job_id: str, faults: Sequence[str] = (), arc: str = "", peak: str = "") -> Row:
    """The design row with the agent's camera in it. `c` None (or with faults left after the repair): the rule
    recommendation `base` stands and the camera block says "not designed" with the faults (D10)."""
    if c is None or faults:
        block = {"state": NOT_DESIGNED, "faults": list(faults)[:6], "language": language, "model": model,
                 "job_id": job_id, "designed_at": now()}
        return {**design, "recommended": base.model_dump(), "camera": block}
    rec = recommended_from(c, base)
    return {**design, "recommended": rec.model_dump(), "camera": camera_block(c, language=language, model=model,
                                                                               job_id=job_id, arc=arc, peak=peak)}


def designed(design: Mapping[str, Any] | None) -> bool:
    block = (design or {}).get("camera")
    return isinstance(block, Mapping) and block.get("state") == DESIGNED


def current_of(design: Mapping[str, Any] | None) -> Row:
    """The clip's camera as it stands now in the agent's slugs: what a one-shot brief shows and the scene-wide gates
    count. {} for a shot with no design."""
    design = design or {}
    rec = design.get("recommended")
    if not isinstance(rec, Mapping):
        return {}
    try:
        settings = CameraSettings.model_validate(rec)
    except ValueError:
        return {}
    block = design.get("camera") if designed(design) else {}
    return {"move": cam.slug_of("movement", settings.movement) or "hold",
            "speed": cam.slug_of("speed", settings.speed) or "none",
            "angle": cam.slug_of("angle", settings.angle) or "eye_level",
            "height": cam.slug_of("height", settings.height) or "eye",
            "axis": cam.slug_of("axis", settings.axis) or "side_a",
            "support": cam.slug_of("support", settings.support), "lens": settings.lens,
            "camera_sentence": str((block or {}).get("camera_sentence") or ""),
            **{k: (block or {}).get(k) for k in ("moment", "intensity", "power") if (block or {}).get(k)},
            "designed": bool(block)}


def language_of(designs: Sequence[Mapping[str, Any] | None]) -> str:
    """The scene's camera language (D16: stored on each shot's `design.camera.language`), the first one found."""
    for d in designs:
        block = (d or {}).get("camera")
        if isinstance(block, Mapping) and block.get("language"):
            return str(block["language"])
    return ""
