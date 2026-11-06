"""david_repair hooks (plan/2026-11-05e §4.2).

The repairer sees the plan's notes, every shot in one line, and in full the shots the problems involve with two shots
either side: enough to mend a join, not enough to rewrite the scene. Its answer is a patch. Code applies it
(`DavidWire.patched`), checks the whole plan again and refuses a patch that creates a new failure; the cleaning here
only
drops a reference to a block or a line the scene lacks, as the author's does.
"""
from __future__ import annotations

import json
from typing import Any

from contracts.david.scene import listing
from contracts.david.wire import DavidWire, PatchWire, ReplaceW
from hiru_ai.agents.david.david_repair.schema import Input, Output
from hiru_ai.agents.david.wire_schema import wire_schema

SCHEMA_NAME = "david_patch"


def output_schema() -> dict[str, Any]:
    """The patch's schema with the clip schema's camera design in every replacement shot (see `wire_schema`)."""
    return wire_schema(PatchWire, SCHEMA_NAME)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def involved(inp: Input) -> list[int]:
    """The shots to show in full: those the problems name, and two either side."""
    named = {n for p in inp.problems for n in p.shots}
    last = max((s.n for s in inp.plan.shots), default=0)
    return sorted({k for n in named for k in range(max(1, n - 2), min(last, n + 2) + 1)})


def glance(plan: DavidWire, n: int) -> str:
    s = plan.shot(n)
    assert s is not None
    return f"S{s.n:02d} blocks {s.blocks} lines {s.lines} {s.take_s} s {s.size}: {s.why}"


def user_message(inp: Input) -> str:
    plan, full = inp.plan, involved(inp)
    shots = [_json(s.model_dump(mode="json")) for s in plan.shots if s.n in full]
    others = [glance(plan, s.n) for s in plan.shots if s.n not in full]
    problems = "\n".join(f"- {p.sentence}" for p in inp.problems)
    parts = [f"<script>\n{listing(inp.scene)}\n</script>",
             f"<plan>\nNotes: {plan.notes}\nThe other shots:\n" + "\n".join(others) + "\n</plan>",
             "<shots>\n" + "\n".join(shots) + "\n</shots>",
             f"<staging>\n{_json(plan.staging.model_dump(mode='json'))}\n</staging>",
             f"<end_state>\n{_json(plan.end_state.model_dump(mode='json'))}\n</end_state>",
             f"<problems>\n{problems}\n</problems>"]
    if inp.tried:
        parts.append("<tried>\n" + "\n".join(f"- {t}" for t in inp.tried) + "\n</tried>")
    if inp.note:
        parts.append(f"<note>\n{inp.note}\n</note>")
    return "\n\n".join(parts)


def finish(inp: Input, out: Output) -> Output:
    blocks = {b.index for b in inp.scene.blocks}
    lines = {b.line_id for b in inp.scene.lines}
    replaces = []
    for r in out.replaces:
        shots = [s.model_copy(update={"blocks": [b for b in s.blocks if b in blocks],
                                      "lines": [ln for ln in s.lines if ln in lines]}) for s in r.shots]
        replaces.append(ReplaceW(replace_from=r.replace_from, replace_to=r.replace_to, shots=shots, added=r.added))
    return Output(replaces=replaces, staging=out.staging, end_state=out.end_state)
