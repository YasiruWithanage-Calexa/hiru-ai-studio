"""What a person does in Zora's panel besides writing (plan/2026-11-06e §4.7, §4.8, §4.10): plain JSON, no model.

    use     a proposal's operations applied (they were tried on a copy and passed the planner's checks when offered);
            refused when the plan changed since they were made. A revision first, so it can be undone
    undo    the plan as it was before the last change (itself a revision, so redo is the undo of the undo)
    redo
    lock    a field a person set: no model may write it ("not this"). Unlock lifts it. Not a revision
"""
from __future__ import annotations

from typing import Any

from contracts.zora.doc import Person, ZoraDoc
from contracts.zora.events import ZoraAction, ZoraActionResult
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings
from hiru_ai.steps.zora.zora_board import gate
from hiru_ai.steps.zora.zora_kernel.step import kernel_for
from hiru_ai.steps.zora.zora_ledger.logic import build
from hiru_ai.systems.zora.zora_chat import scene as world_of
from hiru_ai.systems.zora.zora_chat.store import NO_UNDO, Saver
from hiru_ai.systems.zora.zora_chat.turn import handles_for

Row = dict[str, Any]
ROLE = "Your role can comment on the plan but not change it."


def _result(saver: Saver | None, ok: bool, text: str, **more: Any) -> ZoraActionResult:
    stack = saver.stack() if saver is not None else None
    return ZoraActionResult(ok=ok, text=text, can_undo=bool(stack and stack.can_undo()),
                            can_redo=bool(stack and stack.can_redo()), **more)


def act(req: ZoraAction, ctx: RunContext) -> ZoraActionResult:
    if not req.can_edit:
        return ZoraActionResult(ok=False, text=ROLE)
    world = world_of.read(ctx, req.production_id, req.scene_id)
    if isinstance(world, str):
        return ZoraActionResult(ok=False, text=world)
    saver = Saver(ctx, world, actor_user_id=req.actor_user_id, kept=get_settings().zora.revisions_kept)
    before = _handled(world.stored["plan"])
    if req.kind in ("undo", "redo"):
        if saver.stack() is None:
            return _result(saver, False, NO_UNDO)
        done = saver.restore(req.kind)
        if not done.ok:
            return _result(saver, False, done.reason)
        led = build(before, _handled(world.stored["plan"]), attempted=True)
        word = "Undone" if req.kind == "undo" else "Redone"
        return _result(saver, True, f"{word}.", revision=done.revision, ops=led.event(), gate=led.gate())
    doc = ZoraDoc(plan=world.stored["plan"], scene=world.scene,
                  person=Person.model_validate(world.stored.get("person") or {}))
    kernel = kernel_for(doc)
    if req.kind in ("lock", "unlock"):
        res = kernel.apply([{"op": req.kind, "path": req.path}], by="person")
        if res.rejected:
            return _result(saver, False, str(res.rejected[0]["reason"]))
        stored = {**world.stored, "person": kernel.person().model_dump()}
        ctx.need("scenes").save_plan(world.scene_row["id"], [], [], [], {"jonathan": stored})
        verb = "Locked" if req.kind == "lock" else "Unlocked"
        return _result(saver, True, f"{verb}: {req.path}.")
    return _use(req, ctx, world, saver, kernel, before)


def _use(req: ZoraAction, ctx: RunContext, world: world_of.World, saver: Saver, kernel: Any,
         before: Row) -> ZoraActionResult:
    director = ctx.need("director")
    message = director.message(req.message_id) if req.message_id else None
    blocks = list((message or {}).get("blocks") or [])
    block = blocks[req.block] if 0 <= req.block < len(blocks) else {}
    options = block.get("options") or [] if block.get("kind") == "options" else []
    if not options or not 0 <= req.option < len(options):
        return _result(saver, False, "That option is no longer available.")
    if block.get("chosen") is not None:
        return _result(saver, False, "An option on that card was already used.")
    option = options[req.option]
    made_on = str(option.get("intent") or "").removeprefix("zora:")
    if made_on != saver.read_print:
        return _result(saver, False, "The plan changed since these options were made; ask for them again.")
    base = gate.judge(world.scene, kernel.export(), mend=False)
    base_handles = kernel.handles()
    res = kernel.apply(list(option.get("ops") or []), by="author")
    if not res.applied:
        return _result(saver, False, "That option no longer applies to the plan.")
    judged = gate.judge(world.scene, kernel.export())
    after = kernel.export(handles=True)
    plan, overruns = gate.protect(kernel.export(), judged, {})
    saved = saver.save(plan, handles=handles_for(plan, after), mended=judged.mended, problems=judged.problems,
                       measures=judged.measures, person=kernel.person().model_dump(), kind="use",
                       message_id=str(req.message_id or ""))
    if not saved.ok:
        return _result(saver, False, saved.reason)
    new = [p["sentence"] for p in gate.new_problems(base.problems, base_handles, judged.problems, kernel.handles())
           if p.get("fix") != "report"]
    led = build(before, after, attempted=True, mended=judged.mended, problems=new,
                overruns=overruns + gate.overruns(judged.problems))
    blocks[req.block] = {**block, "chosen": req.option, "outcome": f"Used: {option.get('label', '')}"}
    director.set_blocks(req.message_id, blocks)
    return _result(saver, True, f"Used: {option.get('label', 'the option')}.", revision=saved.revision,
                   ops=led.event(), gate=led.gate())


def _handled(plan: Row) -> Row:
    return {**plan, "shots": [{**s, "_h": f"h{i}"} for i, s in enumerate(plan.get("shots") or [], start=1)]}
