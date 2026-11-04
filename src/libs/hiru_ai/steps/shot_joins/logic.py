"""shot_joins: the end of shot N against the start of shot N+1, in code (plan/2026-11-04 §5.2).

Four kinds of finding, all from what is stored, none from a model:

  position   a person who ends one shot in one zone opens the next in another, with nothing between the two blocks
             to move them
  side       the same person is on the other side of the frame after the cut (the line has been crossed)
  prop       what a person holds at the end of one shot differs from what they hold at the start of the next
  join_size  a shot that CONTINUES the one before ("continuous" join) is cut in another size
  card       the two shots were designed against different versions of the same person's canon card (a new look, a
             new wardrobe): the second may not match the first

The scene's staging map says where people are; a scene with none gets no position, side or prop findings. The shots are
adjacent, so a change of zone between their blocks is a move the script did not show (`bridges` writes the move).
"""
from __future__ import annotations

from typing import Any

from contracts import sceneplan, stagemap


def code(number: int) -> str:
    return f"S{int(number):02d}"


def _finding(kind: str, message: str, who: list[str] | None = None) -> dict[str, Any]:
    return {"code": kind, "message": message, "who": who or []}


def _places(first: dict[str, Any], second: dict[str, Any], items: list[Any], staging: Any,
            cast: list[str]) -> list[dict[str, Any]]:
    last, opening = int(first["block_end"]) - 1, int(second["block_start"])
    if staging is None or not (0 <= last < len(items)) or not (0 <= opening < len(items)):
        return []
    leaving = stagemap.people_in(items[last:last + 1], cast, holds=False)
    arriving = stagemap.people_in(items[opening:opening + 1], cast, holds=False)
    found = []
    for who in (w for w in leaving if w in arriving):
        was, now = staging.mark_at(items, who, last), staging.mark_at(items, who, opening)
        if was is None or now is None:
            continue
        name = was.who
        if was.zone != now.zone:
            found.append(_finding("position", f"{name} ends {code(first['number'])} in the {was.zone} and opens "
                                              f"{code(second['number'])} in the {now.zone}; "
                                              "nothing in the script moves them",
                                  [name]))
        elif was.frame_side != now.frame_side:
            found.append(_finding("side", f"{name} is on the {was.frame_side} of the frame at the end of "
                                          f"{code(first['number'])} and on the {now.frame_side} at the start of "
                                          f"{code(second['number'])}", [name]))
        if (was.holding or "").strip().casefold() != (now.holding or "").strip().casefold():
            found.append(_finding("prop", f"{name} holds {was.holding or 'nothing'} at the end of "
                                          f"{code(first['number'])} and {now.holding or 'nothing'} at the start of "
                                          f"{code(second['number'])}", [name]))
    return found


def _join(first: dict[str, Any], second: dict[str, Any]) -> list[dict[str, Any]]:
    if second.get("camera_link") == "continuous" and first.get("framing") != second.get("framing"):
        return [_finding("join_size", f"{code(second['number'])} continues {code(first['number'])} but is cut in "
                                      f"{second.get('framing')} where it ends in {first.get('framing')}")]
    return []


def _cards(first: dict[str, Any], second: dict[str, Any], names: dict[str, str]) -> list[dict[str, Any]]:
    was = ((first.get("design") or {}).get("pins") or {}).get("canon") or {}
    now = ((second.get("design") or {}).get("pins") or {}).get("canon") or {}
    return [_finding("card", f"{names.get(cid, cid)} is on card v{was[cid]} in {code(first['number'])} "
                             f"but v{now[cid]} in "
                             f"{code(second['number'])}: the look may differ", [names.get(cid, cid)])
            for cid in sorted(set(was) & set(now)) if was[cid] != now[cid]]


def joins(scene: dict[str, Any], lines: list[dict[str, Any]], shots: list[dict[str, Any]], number: int,
          cast: list[str], canon: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ordered = sorted(shots, key=lambda s: int(s["number"]))
    first = next((s for s in ordered if int(s["number"]) == number), None)
    if first is None:
        raise ValueError(f"there is no shot {code(number)}")
    second = next((s for s in ordered if int(s["number"]) == number + 1), None)
    out: dict[str, Any] = {"first": code(number), "second": code(number + 1) if second else None,
                           "join": second.get("camera_link", "cut") if second else None, "findings": [],
                           "staging_map": bool(scene.get("staging"))}
    if second is None:
        return {**out, "ok": True, "note": "this is the last shot of the scene: nothing follows it here"}
    items = sceneplan.scene_items(scene, lines)
    staging = stagemap.SceneStaging.of(scene)
    names = {str(c["id"]): f"{c['code']} {c['name']}" for c in canon or []}
    out["findings"] = [*_places(first, second, items, staging, cast), *_join(first, second),
                       *_cards(first, second, names)]
    out["ok"] = not out["findings"]
    return out
