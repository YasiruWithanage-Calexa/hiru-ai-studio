"""The context pack: what the author is given about the scene, built from the database's rows by code (pattern rule
5)."""
from __future__ import annotations

import json
from typing import Any

from contracts.david.scene import SceneS, listing
from contracts.david.wire import EndStateW


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def production_part(production: dict[str, Any]) -> str:
    people = [f"- {p['name']} ({p.get('code') or '-'})" + (f": look this episode: {p['look']}" if p.get("look") else "")
              + (f"; voice: {p['voice']}" if p.get("voice") else "") for p in production.get("people") or []]
    rules = [f"- {r}" for r in production.get("rules") or []]
    rows = [f"Style note: {production['style_note']}" if production.get("style_note") else "",
            "Production rules:\n" + "\n".join(rules) if rules else "",
            "People in this episode:\n" + "\n".join(people) if people else ""]
    return "\n".join(r for r in rows if r)


def scene_part(context: dict[str, Any]) -> str:
    rows = [f"Scene: {context['heading']}" if context.get("heading") else "",
            f"Episode: {context['episode_title']}" if context.get("episode_title") else "",
            f"Episode synopsis: {context['synopsis']}" if context.get("synopsis") else "",
            f"The scene before: {context['before']}" if context.get("before") else "",
            f"The scene after: {context['after']}" if context.get("after") else "",
            f"The place card: {context['place']}" if context.get("place") else "",
            f"Director's note: {context['note']}" if context.get("note") else ""]
    return "\n".join(r for r in rows if r)


def person_row(p: dict[str, Any], kind: str) -> str:
    bits = [f"where: {p['where']}" if kind == "continuous" and p.get("where") else "",
            f"facing: {p['facing']}" if kind == "continuous" and p.get("facing") else "",
            f"holding: {p['holding']}" if p.get("holding") else "",
            f"look: {p['look']}" if p.get("look") else ""]
    return f"- {p['who']}: " + "; ".join(b for b in bits if b)


def start_part(kind: str, start: EndStateW | None, canon_looks: dict[str, str], changes: list[dict[str, Any]]) -> str:
    """The state the scene starts from. A `continuous` link passes on everything; a `carry` link only looks and what
    people keep (place, position and light do not); no link starts from canon looks."""
    rows: list[str] = []
    if start is not None and kind in ("continuous", "carry"):
        rows.append(f"Where things stand at the start (the scene before ended like this; {kind}):")
        rows += [person_row(p.model_dump(), kind) for p in start.people]
        if kind == "continuous":
            rows += [f"- prop {x.what}: {x.where}" for x in start.props]
            rows += [f"Time: {start.time}" if start.time else "", f"Light: {start.light}" if start.light else ""]
    elif canon_looks:
        rows.append("Each person's look at the start of this episode (from the canon):")
        rows += [f"- {name}: look: {look}" for name, look in canon_looks.items() if look]
    if changes:
        rows.append("Look changes earlier in this episode (they still hold):")
        rows += [f"- {c['who']} (scene {c['scene']}): {c['before']} -> {c['after']}" for c in changes]
    return "\n".join(r for r in rows if r)


def last_shot_part(kind: str, ir: dict[str, Any] | None) -> str:
    """The scene before's last shot word for word (D8): all of it for a continuous link, only the subjects for a carry
    link, so the wording of clothes and light matches across the cut."""
    if not ir or kind not in ("continuous", "carry"):
        return ""
    return _compact(ir if kind == "continuous" else {"subjects": ir.get("subjects") or []})


def pack(payload: dict[str, Any]) -> dict[str, Any]:
    scene = SceneS.model_validate(payload["scene"])
    kind = str(payload.get("link") or "")
    start = EndStateW.model_validate(payload["start"]) if payload.get("start") else None
    script = listing(scene)
    if payload.get("reading"):
        script += "\n\nThe scene's reading (a person's; keep it):\n" + str(payload["reading"])
    if payload.get("removed"):
        script += "\n\nAdditions a person took out (they must not come back):\n" + "\n".join(
            f"- {r}" for r in payload["removed"])
    parts = {"production": production_part(payload.get("production") or {}),
             "scene": scene_part(payload.get("context") or {}),
             "start": start_part(kind, start, dict(payload.get("canon_looks") or {}),
                                 list(payload.get("look_changes") or [])),
             "last_shot": last_shot_part(kind, payload.get("last_shot_ir")), "script": script}
    tags = [("production", "production"), ("scene", "scene"), ("start", "start_state"), ("last_shot", "last_shot"),
            ("script", "script")]
    text = "\n\n".join(f"<{tag}>\n{parts[key]}\n</{tag}>" for key, tag in tags if parts[key])
    return {"text": text, "parts": parts, "words": len(text.split())}
