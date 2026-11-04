"""Try operations on a copy of a scene with the kernel's own rules (plan/2026-11-04 `plan_try`, `change_propose`).

Both tools need the same trial, and a tool never imports another tool, so the trial lives here, over the scene store and
the steps found by id. Nothing is saved: the kernel works on a copy loaded from rows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext

BY = "conductor"  # tried as the conductor's: what only a person may make (the script, the cast, checks) is refused


@dataclass
class Trial:
    scene: dict[str, Any]
    payload: dict[str, Any]  # what the steps are given: the scene, its lines, shots and the canon
    kernel: Any  # the kernel after the operations
    applied: list[dict[str, Any]]  # the operations that landed, as the kernel normalised them (no author)
    rejected: list[dict[str, Any]]
    before: Any  # the fit before
    rows: list[dict[str, Any]]  # one `{op, applied, why?}` per operation sent, in the order sent

    @property
    def after(self) -> Any:
        return self.kernel.fit()

    def new_problems(self) -> list[str]:
        known = {i.message for i in self.before.issues}
        out = [i.message for i in self.after.issues if i.message not in known]
        return out + [n for n in self.kernel.notes if n not in out]

    def timing(self, *, detailed: bool = False) -> dict[str, Any]:
        after = self.after
        out: dict[str, Any] = {"total_s": after.total_s, "envelope_s": after.envelope_s,
                               "over_envelope_s": after.over_envelope_s, "shots": len(after.shots),
                               "new_problems": self.new_problems()}
        if detailed:
            out["plan"] = [{"shot": tooling.shot_code(s.number), "start_s": s.start_s, "length_s": s.duration_s,
                            "words": s.words, "word_target": s.word_target} for s in after.shots]
        return out

    def ripple(self, *, detailed: bool = False) -> dict[str, Any]:
        """Which shots the landed operations touch and which are in doubt (the `ripple` step)."""
        out: dict[str, Any] = {"touched": [], "in_doubt": [], "checked": ""}
        if not self.applied:
            return out
        review = parts.module("step", "ripple", "step").run({**self.payload, "ops": self.applied, "by": "you",
                                                             "summary": ""})
        out = {"touched": [tooling.shot_code(n) for n in review["impact"]],
               "in_doubt": [n["text"] for n in review["notes"] if n["check"]], "checked": review["checked"]}
        if detailed:
            out["for_information"] = [n["text"] for n in review["notes"] if not n["check"]]
            out["words"] = review["words"]
        return out


def describe(op: dict[str, Any]) -> str:
    try:
        return str(parts.module("step", "scene_kernel", "turn_logic").describe_op(op))
    except (KeyError, TypeError, ValueError):
        return str(op.get("op"))


def run(ctx: RunContext, scene_ref: str | None, ops: list[views.ToolOp]) -> Trial:
    store, scene = tooling.scene_in_scope(ctx, scene_ref)
    payload = {"scene": scene, "lines": store.lines(str(scene["id"])), "shots": store.shots(str(scene["id"])),
               "canon": store.canon(tooling.production_of(ctx))}
    kernel_step = parts.module("step", "scene_kernel", "step")
    before = kernel_step.from_payload(payload).fit()
    kernel = kernel_step.from_payload(payload)
    raw = views.op_dicts(ops)
    result = kernel.apply(raw, by=BY, respect_locks=True)
    refused, landed = iter(result.rejected), iter(result.applied)
    waiting = next(refused, None)
    rows: list[dict[str, Any]] = []
    for op in raw:
        if waiting is not None and waiting["op"] is op:  # the kernel records the very object it was handed
            rows.append({"op": describe(op), "applied": False, "why": waiting["reason"]})
            waiting = next(refused, None)
        else:
            rows.append({"op": describe(next(landed, op)), "applied": True})
    applied = [{k: v for k, v in op.items() if k != "by"} for op in result.applied]
    return Trial(scene, payload, kernel, applied, list(result.rejected), before, rows)
