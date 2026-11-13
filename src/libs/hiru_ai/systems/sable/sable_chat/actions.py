"""A Sable change card's Accept, carried out in code (plan/2026-11-13 phase 8). No model.

The card holds the row kernel's operations (`steps/coverage_kernel`, tried on a copy when Sable staged them) and the
fingerprint of the rows they were tried on. Accept replays them on the rows as they are now, as the author's (a model's:
a field a person locked is refused and nothing gets a lock, whatever the card says), all or nothing, and saves them in
place with the shared row save (`core.coverage_rows`): ids kept, touched clips' versions moved so what was made from
them reads out of date, and a revision, so the change can be undone in the scene's chat. Refused when the shots
changed since the card was made.
"""
from __future__ import annotations

from typing import Any

from contracts.coverage import checks
from contracts.coverage.ledger import changes
from contracts.sable.events import SableAction, SableActionResult
from hiru_ai.core import coverage_rows, parts
from hiru_ai.core.context import RunContext

Row = dict[str, Any]
BY = "author"
STALE = "The shots changed since this card was made, so nothing was applied. Ask me again."
NOTHING = "That no longer changes anything in the shots."


def apply(req: SableAction, ctx: RunContext) -> SableActionResult:
    world = coverage_rows.read(ctx, req.production_id, req.scene_id)
    if isinstance(world, str):
        return SableActionResult(ok=False, text=world)
    if req.made_on != world.cov.fingerprint():
        return SableActionResult(ok=False, text=STALE)
    ops = [dict(o.get("op") or {}) for o in req.ops if isinstance(o, dict)]
    after = world.cov.copy()
    result = parts.step("coverage_kernel", "logic").Kernel(after).apply(ops, by=BY)
    if result.rejected:
        why = "; ".join(str(r["reason"]) for r in result.rejected)
        return SableActionResult(ok=False, text=f"Part of this change no longer lands ({why}), so nothing was "
                                                "applied. Ask me again.")
    done = changes(world.cov, after)
    if not done:
        return SableActionResult(ok=False, text=NOTHING)
    saver = coverage_rows.Saver(ctx, world, actor_user_id=req.actor_user_id, chat="sable")
    saved = saver.save(after, kind="use", message_id=str(req.message_id or ""))
    if not saved.ok:
        return SableActionResult(ok=False, text=saved.reason)
    left = [f.sentence for f in checks.new(world.cov, after)]
    what = req.summary.strip().rstrip(".") or "the change"
    text = f"Applied: {what}." + (f" To check: {left[0]}" if left else "")
    return SableActionResult(ok=True, text=text, revision=saved.revision, changes=done + list(result.notes))
