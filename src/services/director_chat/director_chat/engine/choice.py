"""A director's choice in a disagreement: apply the chosen side's stored edit to the scene.

The API has already checked who is choosing (Permission.DIRECT) and taken the operations from the
stored message, not from the browser. Here the scene is read fresh, each operation finds its shot
by id (numbers may have moved since the board spoke), the kernel applies them as the person's own
choice, and the plan is saved and audited like a turn's edit. A choice that changes nothing says
why, and saves nothing.
"""
from __future__ import annotations

from contracts.director import ChoicePayload, ChoiceResult
from contracts.production import ProductionSettings
from director_chat.engine.turn import StoreLike, describe_op, kernel_for, persist, unpin

GONE = "That shot has changed since the board spoke. Ask the directors again."


def apply_choice(req: ChoicePayload, store: StoreLike) -> ChoiceResult:
    production = store.production(req.production_id)
    scene = store.scene(req.production_id, req.scene_id)
    if production is None or scene is None:
        return ChoiceResult(summary="This scene is no longer available.")
    if scene["status"] == "approved":
        return ChoiceResult(summary="This scene is approved and locked. Unlock it before changing its shots.")
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    lines = store.lines(req.scene_id)
    shot_rows = store.shots(req.scene_id)
    kernel = kernel_for(scene, lines, shot_rows, settings.fixed_shot_seconds)

    handles = kernel.handles()
    ops = [unpin(op, handles) for op in req.ops]
    if any(op is None for op in ops):
        return ChoiceResult(summary=GONE)
    # A person's choice is their own words: it may pass the length locks they set.
    result = kernel.apply([op for op in ops if op is not None], by="you", respect_locks=False)
    if not result.applied:
        reasons = "; ".join(r["reason"] for r in result.rejected) or "nothing to change"
        return ChoiceResult(summary=f"Not applied: {reasons}.")
    persist(store, kernel, scene, shot_rows, lines, production_id=req.production_id,
            actor_user_id=req.actor_user_id, action="scene.director_choice", applied=result.applied)
    return ChoiceResult(applied=result.applied,
                        summary="Applied: " + "; ".join(describe_op(o) for o in result.applied) + ".")
