"""sable_state_propose: a change to the open scene's state ledger, staged as a card for a person. It saves nothing.

The ledger (`scenes.staging`, `contracts.stagemap`) is what the shot prompts are written from: where each person is, how
they stand, their condition. The change is tried on a copy by the same code that applies it on Accept
(`stagemap.apply_state`), and the card says which shots open or end in a different state. A model never writes the
ledger (plan/2026-11-09b D2, D3)."""
from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts import sceneplan
from contracts import stagemap as sm
from hiru_ai.core import tooling, views
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.trial import OPEN_FIRST


class Args(BaseModel):
    changes: list[sm.StateMark] = Field(min_length=1, max_length=8, description="What changes, person by person")
    summary: str = Field(min_length=3, max_length=200, description="One sentence for the person: what this does")


class Result(BaseModel):
    staged: bool
    card: str
    scene: str
    summary: str
    changes: list[str]
    touched: list[str]
    in_doubt: list[str]
    next: str


def said(change: sm.StateMark) -> str:
    bits = [change.posture, change.condition, f"at {change.zone}" if change.zone else "",
            f"facing {change.facing}" if change.facing else ""]
    if not change.posture and change.condition.casefold().split(":")[0] in sm.STILL:
        bits.insert(0, "lying")
    return f"{change.who}: {', '.join(b for b in bits if b)}, from block {change.from_block}"


def _words(row: dict[str, Any]) -> str:
    """What a stored shot says it shows, in words (never its look)."""
    ir = row.get("ir") or {}
    rows = [str(row.get("title") or "")]
    rows += [str(b.get("action") or "") for b in row.get("beats") or [] if isinstance(b, dict)]
    rows += [f"{s.get('action') or ''} {s.get('position') or ''}"
             for s in ir.get("subjects") or [] if isinstance(s, dict)]
    return " . ".join(r for r in rows if r.strip())


def doubts(after: sm.SceneStaging, items: list[Any], rows: list[dict[str, Any]], touched: list[int],
           changes: list[sm.StateMark]) -> list[str]:
    """Report-only: a touched shot whose own words still show the person doing what their new posture rules out
    (a lying person on their feet), or alive while they are dead. A shot with no words gives nothing to check."""
    out: list[str] = []
    for n in touched:
        row = rows[n]
        text = _words(row)
        for change in changes:
            if not text or not re.search(rf"(?<!\w){re.escape(change.who)}(?!\w)", text, re.IGNORECASE):
                continue
            last = max(int(row["block_end"]) - 1, int(row["block_start"]))
            state = sm.state_at(after, items, last).people.get(change.who.casefold())
            if state is None:
                continue
            rule = sm.NOT_WITH.get(state.posture)
            hit = rule.search(text) if rule else None
            if hit:
                out.append(f"{tooling.shot_code(n + 1)} still says {change.who} {hit.group(0)}, but {change.who} is "
                           f"{state.posture} there.")
            elif state.condition.casefold().split(":")[0] in sm.STILL and (word := sm.alive_word(text)):
                out.append(f"{tooling.shot_code(n + 1)} still shows {change.who} '{word}', but {change.who} is "
                           f"{state.condition} there.")
    return out


def run(args: Args, ctx: RunContext) -> Result:
    staging_port = ctx.need("staging", "Staging")
    if ctx.scene_id is None:
        raise ToolRefused(OPEN_FIRST, how_to_fix="Answer without a card and tell the person to open the scene and ask "
                                                 "again.")
    store, scene = tooling.scene_in_scope(ctx)
    scene_id = str(scene["id"])
    lines = store.lines(scene_id)
    canon = store.canon(tooling.production_of(ctx))
    cast = views.cast_names(canon)
    items = sceneplan.scene_items(scene, lines)
    before = sm.SceneStaging.of(scene)
    try:
        after = sm.apply_state(before, items, args.changes, cast, version=int(scene.get("script_version") or 1))
    except sm.StateRefused as exc:
        raise ToolRefused(str(exc), how_to_fix="Fix the person, block, posture or spot and call again; "
                                               "scene_read shows the blocks, staging_check the map.") from exc
    rows = sorted(store.shots(scene_id), key=lambda s: int(s.get("number") or 0))
    spans = [(int(r["block_start"]), int(r["block_end"])) for r in rows]
    touched = sm.changed_blocks(before, after, items, spans)
    label = tooling.scene_label(scene)
    in_doubt = doubts(after, items, rows, touched, args.changes)
    changes = [said(c) for c in args.changes]
    codes = [tooling.shot_code(n + 1) for n in touched]
    card = staging_port.add({"kind": "state", "scene_id": scene_id, "scene": label, "summary": args.summary,
                             "script_version": int(scene.get("script_version") or 1),
                             "marks": [c.model_dump() for c in args.changes], "changes": changes, "touched": codes,
                             "in_doubt": in_doubt, "by": "sable_state_propose"})
    return Result(staged=True, card=card, scene=label, summary=args.summary, changes=changes, touched=codes,
                  in_doubt=in_doubt,
                  next="A person will see this card and choose. Nothing has changed yet. Shots already made are not "
                       "regenerated.")


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
