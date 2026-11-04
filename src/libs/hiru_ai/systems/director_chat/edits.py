"""The parts of a director turn that change the scene or stage a change, ported from `director_chat/engine/turn.py`
(plan/2026-11-03 Phase 6): the person's own edits, a dialogue change staged as a card, the specialists' rounds, a
translation staged, a confirmation applied. Every model call goes through `Models` (the agents, found by id and run
through the `director_board` panel); everything else is the engine's own code and keeps its order.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID  # noqa: F401

from contracts import director_capabilities as caps
from contracts.director import SCRIPT_OPS, ChoicePayload, TurnPayload
from contracts.production import ProductionSettings
from contracts.shotplan import FitResult
from hiru_ai.core import parts
from hiru_ai.steps.scene_kernel import conductor, loop, options, pending, proposals, translate
from hiru_ai.steps.scene_kernel.logic import TRANSLATOR, ScenePlanKernel
from hiru_ai.steps.scene_kernel.turn_logic import (
    ASK_LANGUAGE,
    NO_SCRIPT_ROLE,
    NOT_TURNED,
    RESHAPE_MIN_SHOTS,
    RESHAPE_RATIO,
    ROLE_REFUSAL,
    WAITING_ON_CARD,
    StoreLike,
    TurnState,
    describe,
    describe_op,
    diff,
    kernel_for,
    line_blocks,
    line_change,
    pin,
    production_notes,
    with_overrun_task,
)
from hiru_ai.steps.scene_kernel.turn_logic import (
    apply as apply_result,
)
from hiru_ai.systems.director_chat import choice
from hiru_ai.systems.director_chat.models import Models

_logger = logging.getLogger(__name__)
Event = tuple[str, dict[str, Any]]
ripple = parts.step("ripple")
verbatim = parts.step("verbatim_check")


def _confirm_pending(row: dict[str, Any], st: TurnState, req: TurnPayload, store: StoreLike, kernel: ScenePlanKernel,
                     settings: ProductionSettings) -> Iterator[Event]:
    """"i confirm" with a pending action open: apply it as the card's button would (same checks, same
    code), write what it did on the card, and say so from that receipt."""
    st.cannot, st.route = None, ""
    ops = list(row.get("ops") or [])
    # As the button checks it (`api/routers/director.py`): each script operation needs EDIT_SCRIPT and each
    # shot-list operation needs DIRECT, so a writer cannot confirm a card that also changes shots.
    script = [op.get("op") in SCRIPT_OPS for op in ops]
    no_script = any(script) and not req.can_edit_script
    if no_script or (not all(script) and not req.can_edit):
        st.blocked = choice.NO_SCRIPT if no_script and req.can_edit else ROLE_REFUSAL
        return
    result = choice.apply_choice(ChoicePayload(production_id=req.production_id, scene_id=req.scene_id,
                                               actor_user_id=req.actor_user_id, can_edit_script=req.can_edit_script,
                                               ops=ops, intent=str(row.get("intent") or "")), store)
    if not result.applied:
        pending.close(store, req.thread_id, pending.CLOSED)
        st.fixed = result.summary
        return
    pending.close(store, req.thread_id, pending.APPLIED)
    pending.record_choice(store, row, result.summary)
    st.fixed, st.lane, st.applied, st.saved = result.summary, "edit", result.applied, True
    if row.get("intent"):  # the goal the card promised: said on the reply, so asking for it again is a new request
        st.goal, st.met = str(row["intent"]), "Goal NOT reached" not in result.summary
    fresh_scene = store.scene(req.production_id, req.scene_id)
    if fresh_scene is not None:
        fresh = kernel_for(fresh_scene, store.lines(req.scene_id), store.shots(req.scene_id),
                           settings.fixed_shot_seconds, store.canon(req.production_id)).fit()
        yield "plan", {"shots": store.shots(req.scene_id), "total_s": fresh.total_s,
                       "issues": [i.message for i in fresh.issues]}


def _follow_up(advice: proposals.Advice, st: TurnState, kernel: ScenePlanKernel,
               models: Models, lead: dict[str, Any],
               req: TurnPayload, history: str, memory: list[str]) -> None:
    """The person said yes to the director's last suggestion. A card still waiting stays the way to
    apply it. Plain advice becomes ONE card (tried on a copy, pinned to ids, Apply / Keep) so that
    "update S02 with that" ends with something to apply, or says plainly that it could not."""
    if advice.kind == "card":
        st.blocked = WAITING_ON_CARD
        return
    message = (f"The person is answering your earlier suggestion with \"{req.message}\". Offer ONE option that "
               f"makes the suggestion on the shot list.\n<suggestion>\n{advice.text}\n</suggestion>")
    card = options.propose(models.options, kernel=kernel,
                           message=message, history=history, lead_charter=lead.get("charter", ""), memory=memory,
                           at_least=1)
    if card is None:
        st.blocked = NOT_TURNED
        st.lane = "chat"
        return
    if len(card["options"]) == 1:
        card["options"].append({"label": "Keep it as it is", "detail": "Nothing changes.", "change": "",
                                "impact": "", "ops": [], "prompt": ""})
    st.options, st.lane = card, "options"


def _translate_turn(kernel: ScenePlanKernel, spec: translate.Spec, st: TurnState, models: Models, lead: dict[str, Any],
                    req: TurnPayload, scene: dict[str, Any], production: dict[str, Any], memory: list[str]) -> None:
    """The person asked for the dialogue in another language: the translator writes it, the turn stages it as a
    card (every line before and after) for someone with `can_edit_script` to apply. Said in code when there is
    nothing to translate, or it cannot be."""
    st.lane = "chat"
    if not req.can_edit_script:
        st.blocked = NO_SCRIPT_ROLE
    elif scene["status"] == "approved":
        st.blocked = "This scene is approved and locked. Unlock it before changing it."
    elif not kernel.shots:
        st.blocked = "This scene has no shots yet. Use Re-split to plan them from the script."
    elif not spec.language:
        st.fixed = ASK_LANGUAGE
    elif not models.enabled:
        st.cannot = conductor.unavailable(req.message)
        st.route, st.goal = st.cannot["route"], loop.cannot_goal(st.cannot)
    else:
        result = translate.propose(
            models.translator, kernel=kernel, spec=spec,
            line_blocks=line_blocks(kernel), production=production_notes(production), memory=memory)
        _stage_translation(kernel, spec, result, st, models, lead, req)


def _stage_translation(kernel: ScenePlanKernel, spec: translate.Spec, result: translate.Result, st: TurnState,
                       models: Models, lead: dict[str, Any], req: TurnPayload) -> None:
    name = spec.name
    if result.error:
        # A translator that did not answer may answer next time: no goal on the reply, so asking again tries again
        # instead of being told "Asking again will not change that" (`engine/loop.py`).
        st.fixed, st.goal = f"I could not translate the lines: {result.error}. Nothing was changed.", ""
        return
    if not result.scope:
        st.fixed = "There are no spoken lines in that part of the scene to translate."
        return
    if not result.ops:
        if result.already and not result.left_out:
            st.fixed, st.met = f"Every spoken line there is already in {name}.", True
        else:
            st.fixed = "I could not translate those lines: " + "; ".join(result.left_out[:3]) + ". Nothing was changed."
            st.goal = ""  # the next try may come back right
        return
    n = len(result.ops)
    lines = f"{n} spoken line{'s' if n != 1 else ''}"
    extra = [f"{result.already} already in {name}"] if result.already else []
    extra += result.left_out[:2]
    card = {"question": f"Translate {lines} to {name}?", "label": f"Translate {lines} to {name}",
            "detail": "Each line is shown before and after; the original words are kept as its source."
                      + (f" Left out: {'; '.join(extra)}." if extra else ""),
            "intent": f"dialogue.{spec.to}" if caps.language_by_code(spec.to) else "",
            "staged": f"{lines} translated to {name}" + (f" ({'; '.join(extra)})" if extra else "")}
    _stage(kernel, result.ops, st, models, lead, can_direct=req.can_edit, by=TRANSLATOR, card=card)
    if st.options is None:
        why = "; ".join(r["reason"] for r in st.rejected[:2]) or "it could not be checked against the shots"
        st.fixed = f"I could not stage the translation: {why}. Nothing was changed."
        st.rejected, st.goal = [], ""


def _screen(kernel: ScenePlanKernel, ops: list[dict[str, Any]], st: TurnState, req: TurnPayload,
            written: str) -> list[dict[str, Any]]:
    """Which of the person's operations may go ahead: the script needs `can_edit_script`, and a
    spoken line may only use words the person wrote."""
    flat, pool, keep = verbatim.flat(written), set(verbatim.words(written)), []
    for op in ops:
        reason = ""
        if op.get("op") in SCRIPT_OPS and not req.can_edit_script:
            reason = "your role can change shots but not the script's words; a writer or producer can"
        elif op.get("op") not in SCRIPT_OPS and not req.can_edit:
            reason = "your role can change the script's words but not the shot list; a director or producer can"
        elif kernel.touches_dialogue(op) and not verbatim.verbatim(op, flat, pool):
            reason = "a line can only use words you wrote, so send me the exact line"
        if reason:
            st.rejected.append({"op": op, "reason": reason, "by": "you"})
        else:
            keep.append(op)
    return keep


def _stage(kernel: ScenePlanKernel, ops: list[dict[str, Any]], st: TurnState, models: Models, lead: dict[str, Any], *,
           can_direct: bool, by: str = "you", card: dict[str, Any] | None = None) -> None:
    """Try a dialogue change on a COPY of the scene, check it against the shots around it, and
    offer it as an options card (Apply / Keep). Nothing is saved: the person decides.

    `by="translator"` stages a translation (plan/2026-11-01c, Phase 4); `card` then says how to word it:
    {question, label, detail, intent, staged}. A translation whose goal the trial copy does not reach is not shown."""
    trial = copy.deepcopy(kernel)
    handles, items = kernel.handles(), copy.deepcopy(kernel.items)
    result = trial.apply(ops, by=by, respect_locks=False)
    st.rejected += result.rejected
    refused = {id(r["op"]) for r in result.rejected}
    pinned = [pin({**o, "was": a.get("was")} if o.get("op") == "block.set" else o, handles, items)
              for o, a in zip([o for o in ops if id(o) not in refused], result.applied, strict=True)]
    if not result.applied or not all(pinned):
        if result.applied:
            st.rejected.append({"op": {}, "reason": "that change cannot be kept for later", "by": "you"})
        return
    rv = ripple.review(kernel, trial, result.applied, result.changes)
    fixes: list[tuple[dict[str, Any], dict[str, Any]]] = []
    task = ripple.continuity_task(rv, "; ".join(describe_op(o) for o in result.applied)) \
        if models.enabled and can_direct else None
    if task:
        outputs = models.specialists([task], scene_text=trial.describe(), lead_charter=lead.get("charter", ""))
        fix_handles = trial.handles()
        for agent, op in models.settle(outputs).ops:
            done = trial.apply([op], by=agent, respect_locks=True, allowed_ops=models.allowed[agent])
            if done.applied and (pinned_fix := pin(op, fix_handles)):
                fixes.append((done.applied[0], pinned_fix))
        st.notes += [f"{o.agent}: {o.note}" for o in outputs if o.note]
    changed = [*result.applied, *(a for a, _ in fixes)]
    words = ripple.words_line(kernel, trial, result.changes)
    clash = [n.text for n in rv.notes if n.check][:2]
    st.flags += [{"text": n.text, "shots": [f"S{x:02d}" for x in n.shots]} for n in rv.notes]
    card = card or {}
    if (goal := card.get("intent")):  # the post-condition, on the copy, before the card is shown
        reached, state = caps.met(str(goal), items=[trial.items[int(o["block"])] for o in result.applied])
        if not reached:
            st.rejected.append({"op": {}, "reason": f"the translation did not come out right: {state}", "by": by})
            return
    apply_option: dict[str, Any] = {
        "label": card.get("label", "Apply this change"),
        "detail": card.get("detail") or " · ".join(diff(o) for o in result.applied),
        "change": "; ".join(describe_op(o) for o in changed),
        "impact": " · ".join(x for x in [words, options.impact(kernel.fit(), trial), *clash] if x),
        "ops": [*pinned, *(p for _, p in fixes)], "prompt": "",
        **({"lines": [line_change(o, items) for o in result.applied]} if by == TRANSLATOR else {}),
        **({"intent": str(goal)} if goal else {})}
    keep_option: dict[str, Any] = {"label": "Keep it as it is", "detail": "Nothing changes.", "change": "",
                                   "impact": "", "ops": [], "prompt": ""}
    shots = sorted({int(o.get("shot") or 0) for o in result.applied} - {0})
    question = card.get("question") or f"Change {ripple.codes(shots) or 'the script'}?"
    st.options = {"kind": "options", "question": question, "options": [apply_option, keep_option]}
    st.staged = card.get("staged") or apply_option["change"]
    st.lane = "options"


def _edit(kernel: ScenePlanKernel, plan: conductor.Plan, st: TurnState, models: Models, lead: dict[str, Any],
          before: FitResult, req: TurnPayload, written: str) -> TurnState:
    ops = _screen(kernel, plan.ops, st, req, written)
    # A change to a spoken line is staged for the person to accept; everything else is applied.
    staged = [o for o in ops if kernel.touches_dialogue(o)]
    now = [o for o in ops if not kernel.touches_dialogue(o)]
    if staged:
        _stage(kernel, staged, st, models, lead, can_direct=req.can_edit)

    # 2. apply the person's own operations (their words pass their own locks)
    rv = ripple.Review()
    if now:
        shots_before = len(kernel.shots)  # the share is of the scene as it was, not what is left
        original = copy.deepcopy(kernel)
        result = kernel.apply(now, by="you", respect_locks=False)
        touched = {h for c in result.changes if c.kind == "structure" for h in c.handles}
        if shots_before >= RESHAPE_MIN_SHOTS and len(touched) / shots_before > RESHAPE_RATIO:
            kernel.undo(result)
            st.reshape = True
            return st
        apply_result(kernel, st, result)
        if result.applied:
            rv = ripple.review(original, kernel, result.applied, result.changes)
            st.flags += [{"text": n.text, "shots": [f"S{x:02d}" for x in n.shots]} for n in rv.notes]

    if not models.enabled or not req.can_edit:  # the specialists work on the shot list: a director's, not a writer's
        return st

    # 3. tasks: the conductor's, plus what the changes made stale
    tasks = list(plan.tasks)
    new_shots = [n for n, s in enumerate(kernel.shots, start=1) if not s.get("id")]
    if new_shots and not any(t["agent"] == "cinematography" for t in tasks):
        tasks.append({"agent": "cinematography", "shots": new_shots,
                      "instruction": "Frame and title the new shots so they cut well with their neighbours."})
    if (fix := ripple.continuity_task(rv, "; ".join(describe_op(o) for o in st.applied))) and \
            not any(t["agent"] == "continuity" for t in tasks):
        tasks.append(fix)
    asked: set[str] = set()  # overruns already put to the editor: never asked about twice
    tasks = with_overrun_task(kernel, tasks, before, asked)

    # 4. round 1, and 5. a bounded round 2 for overruns this turn introduced
    for round_no in (1, 2):
        if not tasks:
            break
        outputs = models.specialists(tasks, scene_text=kernel.describe(), lead_charter=lead.get("charter", ""))
        settled = models.settle(outputs)
        handles = kernel.handles()  # the numbers this round's operations name
        landed: set[int] = set()
        for agent, op in settled.ops:
            result = kernel.apply([op], by=agent, respect_locks=True, allowed_ops=models.allowed[agent])
            if result.applied:
                landed.add(id(op))
            apply_result(kernel, st, result)
        for d in settled.disagreements:
            for p in d["positions"]:
                p["applied"] = any(id(o) in landed for o in p["ops"])
                p["change"] = "; ".join(describe(o) for o in p["ops"])
                p["ops"] = [x for x in (pin(o, handles) for o in p["ops"]) if x]
        st.disagreements += settled.disagreements
        st.notes += [f"{o.agent}: {o.note}" for o in outputs if o.note]
        tasks = with_overrun_task(kernel, [], before, asked) if round_no == 1 else []
    return st
