"""What a director turn is made of that needs no model, ported from `director_chat/engine/turn.py` (plan/2026-11-03
Phase 6): loading a scene into the kernel, the reply a turn writes in code, a stored operation pinned to ids and found
again, and saving a plan. The turn itself (who is asked what, and in which order) is the `director_chat` system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from contracts import director_capabilities as caps
from contracts import sceneplan
from contracts.director import SCRIPT_OPS
from contracts.shotplan import FitResult
from hiru_ai.steps.scene_kernel import proposals
from hiru_ai.steps.scene_kernel.logic import ApplyResult, ScenePlanKernel

_logger = logging.getLogger(__name__)


class StoreLike(Protocol):
    """The slice of the world `persist` and the choice need: one scene and where a plan is saved."""

    def production(self, production_id: UUID) -> dict[str, Any] | None: ...
    def scene(self, production_id: UUID, scene_id: UUID) -> dict[str, Any] | None: ...
    def lines(self, scene_id: UUID) -> list[dict[str, Any]]: ...
    def shots(self, scene_id: UUID) -> list[dict[str, Any]]: ...
    def canon(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def save_plan(self, scene_id: UUID, shots: list[dict[str, Any]], removed: list[str],
                  lines: list[dict[str, Any]], scene_fields: dict[str, Any],
                  removed_lines: list[str] | None = None) -> None: ...
    def audit(self, row: dict[str, Any]) -> None: ...


RESHAPE_RATIO = 0.6
RESHAPE_MIN_SHOTS = 4
NOTHING_WAITING = "There is nothing waiting to apply."
NOT_TURNED = ("I could not turn that suggestion into a change I can make here. Tell me the change itself, for "
              "example \"make shot 3 six seconds\" or \"shot 2 close-up\".")
WAITING_ON_CARD = "That is waiting on the card above: choose Apply on the option you want."
SHORT_FOLLOW_WORDS = 8
ROLE_REFUSAL = "Your role can comment but not make this change; a director, producer or writer can."
NO_SCRIPT_ROLE = "Your role can change shots but not the script's words; a writer or producer can."
ASK_LANGUAGE = ('Which language should the dialogue be in? For example: "put all the dialogue in Sinhala" or '
                '"translate S02 to Tamil".')
BLOCK_PINS = ("line_id", "after_line_id", "at_start", "block_kind", "block_was", "after_kind", "after_text")
SCRIPT_CONFLICT = "Someone changed this script meanwhile. Ask again and I will work from the new version."


def kernel_for(scene: dict[str, Any], lines: list[dict[str, Any]], shots: list[dict[str, Any]],
               fixed: int | None, canon: list[dict[str, Any]] | None = None) -> ScenePlanKernel:
    items = [sceneplan.item_row(i) for i in sceneplan.scene_items(scene, lines)]
    by_line = {str(ln["id"]): ln for ln in lines}
    for item in items:  # a translated line carries the words it was written in
        stored = by_line.get(str(item.get("line_id")), {})
        item |= {k: stored[k] for k in sceneplan.LINE_SOURCE if stored.get(k)}
    # An unlocked length travels as the planner's choice: kept unless the speech needs longer.
    return ScenePlanKernel(items, sceneplan.plan_from_rows(shots), envelope_s=int(scene["envelope_s"]),
                           fixed_seconds=fixed, canon=canon,
                           location_id=str(scene["location_id"]) if scene.get("location_id") else None)


def split_points(kernel: ScenePlanKernel) -> dict[int, int]:
    """Where a plain "split shot N" cuts: before the shot's second line, else its middle block."""
    out = {}
    for n, s in enumerate(kernel.shots, start=1):
        blocks = range(s["start"], s["end"])
        lines = [b for b in blocks if kernel.items[b]["kind"] == "dialogue"]
        if len(lines) >= 2:
            out[n] = lines[1]
        elif s["end"] - s["start"] >= 2:
            out[n] = s["start"] + (s["end"] - s["start"]) // 2
    return out


def line_blocks(kernel: ScenePlanKernel) -> dict[int, list[int]]:
    """Shot number → the blocks of its spoken lines: where "change S01's line to …" lands."""
    return {n: [b for b in range(s["start"], s["end"]) if kernel.items[b]["kind"] == "dialogue"]
            for n, s in enumerate(kernel.shots, start=1)}


def rows(kernel: ScenePlanKernel, scene: dict[str, Any], result: FitResult, shot_rows: list[dict[str, Any]],
         lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """→ (shots, lines, removed shot ids). Ids are kept; a shot the kernel split keeps its id on
    the first part (`contracts.sceneplan`), so the shot count may differ from the kernel's."""
    return sceneplan.rows_after_fit(scene, kernel.shots, result, lines,
                                    before={str(s["id"]): s for s in shot_rows})


def describe_op(op: dict[str, Any]) -> str:
    n = f"S{int(op['shot']):02d}" if op.get("shot") is not None else ""
    name = op["op"]
    if name == "set":
        return f"{n} {op['field'].replace('_', ' ')} → {op['value']}"
    if name == "retime":
        return f"{n} is now {op['seconds']} s"
    if name == "split":
        return f"{n} split in two"
    if name == "merge":
        return f"{n} merged with the next shot"
    if name == "regroup":
        return f"moved the cut after {n}"
    if name == "set_join":
        return f"{n} joins with a {op['link']} cut"
    if name == "beat.set":
        return f"{n} beat {int(op['beat']) + 1}: {op['field'].replace('_', ' ')}"
    if name == "insert":
        return f"new {op.get('framing', '')} shot after S{int(op['after_shot']):02d}: {op['description']}"
    if name == "remove":
        return f"removed {n}"
    if name == "set_envelope":
        return f"scene envelope is now {op['seconds']} s"
    if name == "unlock_length":
        return f"{n} length released to the planner"
    if name == "block.set":
        what = {"text": "line", "speaker": "speaker", "delivery": "delivery"}.get(op.get("field", ""), "")
        who = f"{op['speaker']} " if op.get("speaker") and op.get("field") == "text" else ""
        label = f"{who}{what}" if op.get("kind") == "dialogue" else str(op.get("kind", "block"))
        return f"S{int(op.get('shot') or 0):02d} {label} → “{op['value']}”"
    if name == "block.insert":
        who = f" for {op['speaker']}" if op.get("speaker") else ""
        return f"new {op.get('kind', 'block')}{who} in S{int(op.get('shot') or 0):02d}: “{op['value']}”"
    if name == "block.remove":
        return f"removed the {op.get('kind', 'block')} “{op.get('was', '')}” from S{int(op.get('shot') or 0):02d}"
    if name in ("canon.add", "canon.remove"):
        return f"{n} canon {'+' if name == 'canon.add' else '−'} {op['value']}"
    if name == "check.waive":
        return f"{n} now ignores the {op['value']} check"
    if name == "check.restore":
        return f"{n} shows the {op['value']} check again"
    if name == "dop_note.set":
        return f"{n} DoP note → “{op['value']}”" if op.get("value") else f"{n} DoP note cleared"
    return name


@dataclass
class TurnState:
    lane: str = "chat"
    applied: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    continuity: list[str] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)  # {text, shots}: how an edit sits with its neighbours
    staged: str = ""  # a dialogue change waiting for the person to accept it
    memory: list[str] = field(default_factory=list)
    reshape: bool = False
    blocked: str = ""  # why edits could not be applied (approved scene, role, no shots)
    changed: set[str] = field(default_factory=set)  # kernel handles this turn touched
    options: dict[str, Any] | None = None  # an options block (the `options` lane)
    cannot: dict[str, str] | None = None  # lane cannot: {request, reason, route}
    fixed: str = ""  # a reply written in code, never by a model ("There is nothing waiting to apply.")
    route: str = ""  # where the person can get an unmet request done (kept on the reply for the next turn)
    saved: bool = False  # the scene was saved by someone else already (a pending action applied)
    goal: str = ""  # what the person asked for, as an id (`dialogue.si`, `cannot:<route>`): kept on the reply (Phase 5)
    met: bool = False


def cannot_text(cannot: dict[str, str]) -> str:
    """Why a request is not possible here, and where it is."""
    return f"{cannot['reason']} {cannot['route']}"


def template_reply(st: TurnState, fit_text: str) -> str:
    """The rule-based reply (no key, or the model failed)."""
    if st.blocked:
        return st.blocked
    if st.fixed:
        return st.fixed
    if st.cannot and not st.applied:
        return cannot_text(st.cannot)
    if st.staged and not st.applied:
        return ("I have not changed the script yet: " + st.staged + ". Choose Apply below to put it in, or keep the "
                "script as it is.")
    if st.reshape:
        return ("That would change most of this scene, so I have not applied it. Use Re-split to plan the "
                "scene again from the script.")
    parts = []
    if st.applied:
        parts.append("Done: " + "; ".join(describe_op(o) for o in st.applied) + ".")
    if st.rejected:
        parts.append("Not applied: " + "; ".join(r["reason"] for r in st.rejected) + ".")
    if st.memory:
        parts.append("Noted for the whole production: " + " ".join(st.memory))
    if not parts:
        parts.append("I can change the shot list when you name the change, for example: \"make shot 3 six "
                     "seconds\", \"split shot 2\", \"merge shots 4 and 5\", \"shot 1 wide\", \"add a reaction of "
                     "Kamala after shot 2\". " + fit_text)
    return " ".join(parts)


def production_notes(production: dict[str, Any]) -> str:
    return " ".join(x for x in (str(production.get("title") or ""), str(production.get("summary") or "")) if x)[:600]


def state_fact(kernel: ScenePlanKernel) -> str:
    """The dialogue as it is now, in one sentence."""
    counts = caps.dialogue_counts(kernel.items)
    total = sum(counts.values())
    if not total:
        return "This scene has no spoken lines."
    names = {**{lang.code: lang.name for lang in caps.LANGUAGES}, "mixed": "mixed script"}
    parts = [f"{counts[k]} in {name}" for k, name in names.items() if counts.get(k)]
    return f"Right now {total} spoken line{'s' if total != 1 else ''}: {', '.join(parts)}."


def receipts(st: TurnState, kernel: ScenePlanKernel, history: list[dict[str, Any]]) -> proposals.Receipts:
    """What backs a reply that says something was changed: this turn's applied operations, the recorded
    effect of cards chosen in the recent chat, and the dialogue as it is."""
    effects = tuple(str(b.get("outcome", "")) for m in history[-8:] for b in m.get("blocks") or []
                    if b.get("kind") == "options" and b.get("chosen") is not None and b.get("outcome"))
    return proposals.Receipts(
        applied=bool(st.applied),
        applied_dialogue=any(o.get("op") in SCRIPT_OPS and o.get("field", "text") == "text" for o in st.applied),
        effects=effects, dialogue=caps.dialogue_script(kernel.items))


def scene_now(kernel: ScenePlanKernel) -> str:
    """Five computed lines about the scene as it stands, for the reply: no model wrote them."""
    r = kernel.fit()
    return "\n".join([state_fact(kernel), f"Shots: {len(r.shots)}.",
                       f"Runs {r.total_s} s of a {r.envelope_s} s envelope."])


def fit_text(kernel: ScenePlanKernel) -> str:
    r = kernel.fit()
    return f"The scene runs {r.total_s} s in {len(r.shots)} shots (envelope {r.envelope_s} s)."


def norm(text: str) -> str:
    return " ".join(str(text).lower().strip(" .!").split())


def blocks_text(m: dict[str, Any]) -> str:
    """A director message as the models read it in the history: its words, and what happened on
    its cards (a choice already made and what it changed, or that none was made yet), so "have
    you applied it?" is answered from the record."""
    parts = []
    for b in m.get("blocks") or []:
        kind = b.get("kind")
        if kind == "text":
            parts.append(str(b.get("text", "")))
        elif kind == "options":
            labels = [str(o.get("label", "")) for o in b.get("options") or []]
            chosen = b.get("chosen")
            if isinstance(chosen, int) and 0 <= chosen < len(labels):
                outcome = str(b.get("outcome") or "") or "Its effect was not recorded."
                parts.append(f"[Card: {b.get('question', '')} The person chose \"{labels[chosen]}\". {outcome}]")
            else:
                parts.append(f"[Card shown, no choice made yet, nothing applied: {' | '.join(labels)}]")
        elif kind == "disagreement" and b.get("chosen"):
            parts.append(f"[Board: {b.get('title', '')} The person chose {b['chosen']}. {b.get('outcome', '')}]")
        elif kind == "edit-note":
            parts.append(f"[Applied that turn: {b.get('text', '')}]")
    return " ".join(p for p in parts if p)


def apply(kernel: ScenePlanKernel, st: TurnState, result: ApplyResult) -> None:
    st.applied += result.applied
    st.rejected += result.rejected
    st.changed.update(h for c in result.changes for h in c.handles)


def line_change(op: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """One line a translation changes, as the card shows it: before and after."""
    item = items[int(op["block"])]
    return {"line_id": item.get("line_id"), "shot": int(op.get("shot") or 0), "speaker": str(item.get("speaker") or ""),
            "was": str(op.get("was") or ""), "now": str(op["value"])}


def diff(op: dict[str, Any]) -> str:
    """"S01: “was” → “now”" for a change to a block."""
    s = f"S{int(op.get('shot') or 0):02d}"
    if op["op"] == "block.set":
        return f"{s}: “{op.get('was', '')}” → “{op['value']}”"
    return describe_op(op)


def describe(op: dict[str, Any]) -> str:
    try:
        return describe_op(op)
    except (KeyError, TypeError, ValueError):
        return str(op.get("op", ""))


def pin(op: dict[str, Any], handles: list[str], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A stored operation names its shot by id, not number: numbers move as the scene changes.
    A shot made this turn has no id yet (its handle is `new…`); its operation cannot be chosen
    later and is stored without a pin. A script operation names its block by what is in it (a
    line by its id, an insert by the block before it) for the same reason, and carries what the
    block said (`was`) so a choice made after someone else changed it is refused."""
    out = {k: v for k, v in op.items() if k not in ("shot", "after_shot", "by")}
    for key in ("shot", "after_shot"):
        if op.get(key) is None:
            continue
        try:
            handle = handles[int(op[key]) - 1]
        except (TypeError, ValueError, IndexError):
            return {}
        if handle.startswith("new"):
            return {}
        out[f"{key}_id"] = handle
    if op.get("op") in SCRIPT_OPS:
        try:
            b = int(op["block"])
            if op["op"] == "block.insert":
                out.pop("block")
                if b == 0:
                    out["at_start"] = True
                elif b > len(items or []) or not items:
                    return {}
                else:
                    before = items[b - 1]
                    out |= ({"after_line_id": before["line_id"]} if before["kind"] == "dialogue"
                            else {"after_kind": before["kind"], "after_text": before.get("text", "")})
            else:
                item = (items or [])[b]
                out.pop("block")
                out |= ({"line_id": item["line_id"]} if item["kind"] == "dialogue"
                        else {"block_kind": item["kind"], "block_was": item.get("text", "")})
        except (KeyError, TypeError, ValueError, IndexError):
            return {}
    return out


def find(items: list[dict[str, Any]], *, line_id: str | None = None, kind: str = "", text: str = "") -> int | None:
    for i, item in enumerate(items):
        if line_id is not None and item.get("line_id") == line_id:
            return i
        if line_id is None and item["kind"] == kind and item.get("text", "") == text:
            return i
    return None


def unpin(op: dict[str, Any], handles: list[str], items: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """A stored operation, addressed to the scene as it is now; None when its shot or block is
    gone (or the block no longer says what it said when the operation was stored)."""
    out = {k: v for k, v in op.items() if k not in ("shot_id", "after_shot_id", "was", *BLOCK_PINS)}
    for key in ("shot", "after_shot"):
        handle = op.get(f"{key}_id")
        if handle is None:
            continue
        if handle not in handles:
            return None
        out[key] = handles.index(handle) + 1
    if any(k in op for k in BLOCK_PINS) or op.get("op") in SCRIPT_OPS:
        pool = items or []
        if op.get("op") == "block.insert":
            if op.get("at_start"):
                out["block"] = 0
            else:
                at = find(pool, line_id=op["after_line_id"]) if "after_line_id" in op else \
                    find(pool, kind=str(op.get("after_kind")), text=str(op.get("after_text")))
                if at is None:
                    return None
                out["block"] = at + 1
        else:
            at = find(pool, line_id=op["line_id"]) if "line_id" in op else \
                find(pool, kind=str(op.get("block_kind")), text=str(op.get("block_was")))
            if at is None:
                return None
            if op.get("op") == "block.set" and "was" in op and str(pool[at].get(op.get("field") or "text") or "") \
                    != op["was"]:
                return None  # someone changed it since
            out["block"] = at
    return out


class ScriptConflict(Exception):
    """The script changed (someone saved it) while this turn worked on the version it read."""


def persist(store: StoreLike, kernel: ScenePlanKernel, scene: dict[str, Any], shot_rows: list[dict[str, Any]],
            lines: list[dict[str, Any]], *, production_id: UUID, actor_user_id: UUID, action: str,
            applied: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], FitResult]:
    """Save the kernel's plan (shot ids kept, lines re-bound) and audit it → (shots, fit). When the
    script itself changed, its blocks, its lines and its version are saved with it (and a script
    someone else saved meanwhile is a `ScriptConflict`, never overwritten)."""
    after = kernel.fit()
    fields: dict[str, Any] = {"envelope_s": kernel.envelope_s, "status": "split",
                              "fit_report": sceneplan.fit_report(after, "director")}
    line_rows, removed_lines = lines, []
    if kernel.script_changed:
        version = int(scene.get("script_version") or 1)
        fresh = store.scene(production_id, UUID(str(scene["id"])))
        if fresh is None or int(fresh.get("script_version") or 1) != version:
            raise ScriptConflict
        line_rows = sceneplan.lines_from_items(scene, kernel.items)
        kept = {r["id"] for r in line_rows}
        removed_lines = [str(ln["id"]) for ln in lines if str(ln["id"]) not in kept]
        fields |= {"script": sceneplan.script_rows(kernel.items), "script_version": version + 1}
    shots_out, lines_out, removed = rows(kernel, scene, after, shot_rows, line_rows)
    store.save_plan(UUID(str(scene["id"])), shots_out, removed, lines_out, fields, removed_lines)
    store.audit({"production_id": str(production_id), "actor_user_id": str(actor_user_id),
                 "actor_agent": "director_chat", "action": action, "entity": "scene", "entity_id": str(scene["id"]),
                 "diff": {"ops": applied}})
    return shots_out, after


def with_overrun_task(kernel: ScenePlanKernel, tasks: list[dict[str, Any]], before: FitResult,
                       asked: set[str]) -> list[dict[str, Any]]:
    old = {i.message for i in before.issues} | asked
    fresh = [i for i in kernel.fit().issues if i.code == "line_overrun" and i.message not in old and i.shot_number]
    asked.update(i.message for i in fresh)
    if fresh and not any(t["agent"] == "timing" for t in tasks):
        tasks = [*tasks, {"agent": "timing", "shots": sorted({int(i.shot_number or 0) for i in fresh}),
                          "instruction": "These shots now cut a line off: " + " ".join(i.message for i in fresh)}]
    return tasks
