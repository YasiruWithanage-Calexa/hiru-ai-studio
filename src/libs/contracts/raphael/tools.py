"""Raphael's code tools (plan/2026-11-08e §3.2, §3.5): what the model's tool calls DO. No model, no network.

    Stage1Session(brief, bin, max_turns).call(name, raw_json) -> str     write_edit_plan, put_clips, remove_clips,
    read_bin, finish
    Stage2Session(...).call(name, raw_json)                              put_extras, remove_extras, read_bin, finish

Every write returns the check report of the whole bin, blocking faults first, each marked STILL FAILING when the last
write
replaced one of its clips and it survived. There is no separate `check` tool. The sessions hold the bin and the work log
(the memory of the run); the conversation is the rest. The loop that talks to the model is in the agents.

Stage 2's tools refuse every must clip id, so stage 1's clips leave stage 2 exactly as they came in
(`Stage2Session.changed_must` proves it).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import ValidationError

from contracts.raphael import checks
from contracts.raphael import state as ledger_state
from contracts.raphael.bin import Bin, compact
from contracts.raphael.scene import Brief
from contracts.raphael.wire import (
    DEFAULT_CAP,
    STAGE1_CAP,
    TECHNIQUES,
    BreakdownW,
    EditPlanW,
    ExtrasW,
    PutW,
    ReviewRow,
)

STAGE1_TOOLS = ("write_edit_plan", "put_clips", "remove_clips", "read_bin", "finish")
STAGE2_TOOLS = ("put_extras", "remove_extras", "read_bin", "finish")
# Turn caps (plan/2026-11-08f §4): the lab finished stage 1 in 4-7 turns and stage 2 in 4-6. They were 20 and 12; a
# scene that needs more is stuck, and every turn re-reads the whole conversation.
STAGE1_TURNS = 10
STAGE2_TURNS = 8
# A scene is stuck (plan/2026-11-08f §4) when this many reports in a row have not cut its blocking faults below the
# fewest it has had: the run stops and keeps what it wrote, instead of paying for every turn left.
STUCK_AFTER = 4


class Stage1Session:
    """Stage 1: the intended cut and the must bin."""

    TOOLS: tuple[str, ...] = STAGE1_TOOLS

    def __init__(
        self,
        brief: Brief,
        work: Bin | None = None,
        *,
        allowed: tuple[str, ...] = TECHNIQUES,
        max_turns: int = STAGE1_TURNS,
        scene_no: str = "1",
        breakdown: BreakdownW | None = None,
    ) -> None:
        self.brief, self.allowed, self.max_turns = brief, allowed, max_turns
        self.breakdown = breakdown  # plan/2026-11-10: the director's breakdown, when there is one
        self.work = work if work is not None else Bin(scene=scene_no)
        self.editor_notes: list[str] = []
        self.done = False
        self.turn = 0  # set by the loop before each model turn
        self.last_faults: set[str] = set()
        self.touched: set[str] = set()  # the clips the current write replaced: a fault on them that survives was tried
        self.fewest: int | None = None  # the fewest blocking faults any report has had
        self.flat = 0  # reports in a row with no fewer blocking faults than that
        self.blocked = 0  # the blocking faults of the last report

    # ── progress (plan/2026-11-08f §4) ───────────────────────────────────────────────────────────

    def progress(self, block: list[checks.Fault]) -> None:
        """Count a report: a new low resets the count, anything else adds to it. While the bin is still being built
        (no edit plan, or a block without its must clip) nothing is counted: a scene written a sequence at a time adds
        faults as it adds clips."""
        blocking = self.blocked = len(block)
        if any(f.key.startswith(("edit:none", "coverage:must:")) for f in block):
            self.fewest, self.flat = None, 0
            return
        if self.fewest is None or blocking < self.fewest:
            self.fewest, self.flat = blocking, 0
        else:
            self.flat += 1

    @property
    def stuck(self) -> bool:
        """Blocking faults remain and the last `STUCK_AFTER` reports have not cut them: more turns would not help."""
        return self.blocked > 0 and self.flat >= STUCK_AFTER

    # ── the checks this stage reads ──────────────────────────────────────────────────────────────

    def found(self) -> list[checks.Fault]:
        return checks.check_stage1(self.brief, self.work, self.allowed, self.breakdown)

    def faults(self) -> list[checks.Fault]:
        """What is left now: a stopped run saves this beside its bin."""
        return self.found()

    # ── the report every write returns ───────────────────────────────────────────────────────────

    def advice(self, f: checks.Fault) -> str:
        """The check's sentence, except an overrun, which names the clip's blocks and the cure: another angle over the
        SAME
        blocks overruns the same way."""
        clip = self.work.by_id(f.clips[0]) if f.key.startswith("clock:overrun:") and f.clips else None
        if clip is None or len(clip.blocks) < 2:
            return f.sentence
        need = f.sentence.split(" needs ", 1)[1].split(" s ", 1)[0] if " needs " in f.sentence else "more"
        blocks = ", ".join(f"b{b}" for b in clip.blocks)
        return (
            f"{clip.id} carries blocks {blocks}, which need {need} s; its take is {clip.take_s} s and no take is "
            f"longer "
            "than 8 s. Split those blocks across clips that follow each other (each clip fewer blocks, neighbours may "
            "share one block), each the must clip of its blocks. Another angle over the SAME blocks overruns the same "
            "way."
        )

    def seconds_line(self) -> str:
        n = self.work.counts()
        cap = checks.limit_s(self.brief, STAGE1_CAP)
        if cap:
            return (
                f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must); target {self.brief.guide_s:g} s, "
                f"cap {cap:g} s."
            )
        return f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must)."

    def report(self) -> str:
        """The whole bin's checks. A fault is marked STILL FAILING when it was in the last report and this write
        replaced
        one of its clips: the fix was tried and did not work. A hole that is simply not built yet is never marked."""
        found = self.found()
        again = {f.key for f in found if f.key in self.last_faults and set(f.clips) & self.touched}
        self.last_faults, self.touched = {f.key for f in found}, set()
        block, told = checks.blocking(found), [f for f in found if f.fix == "report"]
        self.progress(block)
        n = self.work.counts()

        def row(f: checks.Fault, text: str) -> str:
            return f"- {f.code}{' [' + ', '.join(f.clips) + ']' if f.clips else ''}: {text}"

        rows = [
            row(f, f.sentence)
            + ("  [STILL FAILING after your last change: change the approach]" if f.key in again else "")
            for f in block
        ]
        yours = [row(f, self.advice(f)) for f in told if f.owner != "code"]
        codes = [row(f, self.advice(f)) for f in told if f.owner == "code"]
        left = self.max_turns - self.turn
        head = (
            f"Report: {len(block)} blocking fault(s), {len(told)} report(s). Bin: {n['clips']} clips ({n['must']} "
            f"must, "
            f"{n['should']} should, {n['nice']} nice). {self.seconds_line()} Turns left after this one: {left}."
        )
        body = (
            ("\nFix (blocking):\n" + "\n".join(rows))
            if rows
            else (
                "\nNothing blocks."
                + (
                    " Fix the reports below first where you can, then call finish."
                    if yours
                    else " You may call finish."
                )
            )
        )
        if yours:
            body += (
                "\nYours to fix (they do not block finish, but the editor gets them as they are; a line too long for "
                "its take is fixed by overlapping clips, never by trimming):\n" + "\n".join(yours)
            )
        if codes:
            body += "\nReported by code (nothing to do):\n" + "\n".join(codes)
        return head + body

    # ── dispatch ─────────────────────────────────────────────────────────────────────────────────

    def call(self, name: str, raw: str) -> str:
        fn = getattr(self, f"tool_{name}", None) if name in self.TOOLS else None
        if fn is None:
            return f"There is no tool {name}. Tools: {', '.join(self.TOOLS)}."
        try:
            args = json.loads(raw or "{}")
        except ValueError:
            return "The arguments are not valid JSON: send the arguments the tool's schema asks for."
        if not isinstance(args, dict):
            return "The arguments must be a JSON object: send the arguments the tool's schema asks for."
        try:
            result = str(fn(args))
        except ValidationError as exc:
            err = exc.errors()[0]
            result = f"The arguments do not fit the tool's schema: {err['msg']} at {err['loc']}. Nothing was changed."
        self.work.note(tool=name, args=raw[:300], result=result[:300])
        return result

    # ── stage 1's tools ──────────────────────────────────────────────────────────────────────────

    def tool_write_edit_plan(self, args: dict[str, Any]) -> str:
        self.work.edit = EditPlanW.model_validate(args)
        return (
            f"The edit plan is saved: {len(self.work.edit.moments)} moments in {len(self.work.edit.sequences)} "
            f"sequences.\n{self.report()}"
        )

    def _summary(self, added: list, replaced: list, refused: list[str]) -> str:
        parts = []
        if added:
            parts.append("Added " + ", ".join(f"{c.id} [{c.slate}]" for c in added) + ".")
        if replaced:
            parts.append("Replaced " + ", ".join(f"{c.id} [{c.slate}]" for c in replaced) + ".")
        if refused:
            parts.append("Not done: " + "; ".join(refused) + ".")
        return " ".join(parts or ["No clips were sent."])

    def tool_put_clips(self, args: dict[str, Any]) -> str:
        if self.work.edit is None:
            return "Write the edit plan first (write_edit_plan): the clips serve it. Nothing was changed."
        entries = PutW.model_validate(args).clips  # all or nothing: a call that does not fit changes nothing
        added, replaced, refused = [], [], []
        for e in entries:
            clip_id = e.id.strip()
            if clip_id:
                clip = self.work.replace(clip_id, e.menu())
                if clip is None:
                    refused.append(f'{clip_id} is not in the bin (use "" for a new clip, or read_bin)')
                    continue
                replaced.append(clip)
                self.touched.add(clip.id)
            else:
                clip = self.work.add(e.menu())
                added.append(clip)
            clip.ir, clip.sound = e.ir, e.sound
        return self._summary(added, replaced, refused) + "\n" + self.report()

    def tool_remove_clips(self, args: dict[str, Any]) -> str:
        """Remove clips one at a time; a removal that would open a coverage hole is refused and the bin is left as it
        was."""
        scene, gone, refused = self.brief.scene, [], []
        for raw in args.get("clip_ids") or []:
            clip_id = str(raw)
            before = {f.key for f in checks.coverage(scene, self.work)}
            snapshot = list(self.work.clips)
            if not self.work.remove(clip_id):
                refused.append(f"{clip_id} is not in the bin.")
                continue
            opened = [f for f in checks.coverage(scene, self.work) if f.key not in before]
            if opened:
                self.work.clips = snapshot
                self.work.reslate()
                refused.append(
                    f"{clip_id} was not removed: it would leave "
                    + "; ".join(f.sentence for f in opened[:3])
                    + ". Replace it with put_clips instead."
                )
            else:
                gone.append(clip_id)
        return (
            f"Removed {', '.join(gone) or 'nothing'}."
            + ("\n" + "\n".join(refused) if refused else "")
            + "\n"
            + self.report()
        )

    def states(self, clip: Any, moment: int) -> str:
        """A clip's opening and closing state (plan/2026-11-09 phase 5), only when one moment is asked for: the state
        Raphael must meet, without it costing every turn. "" with no ledger."""
        if not moment:
            return ""
        opens, ends = ledger_state.opens_ends(self.brief.scene, clip, self.work)
        return f"\n  opens: {opens}\n  ends: {ends}" if opens or ends else ""

    def tool_read_bin(self, args: dict[str, Any]) -> str:
        moment = int(args.get("moment") or 0)
        rows = [compact(c) + self.states(c, moment) for c in self.work.clips if not moment or c.moment == moment]
        return f"{len(self.work.clips)} clips. " + ("\n" + "\n".join(rows) if rows else "The bin is empty.")

    def tool_finish(self, args: dict[str, Any]) -> str:
        if checks.blocking(self.found()):
            return "Refused: blocking faults remain.\n" + self.report()
        self.editor_notes = [str(n) for n in args.get("editor_notes") or []]
        self.done = True
        return "Finished. The intended cut, the shoot bin and your notes are written."


class Stage2Session(Stage1Session):
    """Stage 2: the cinematic pass over a finished, locked must bin."""

    TOOLS: tuple[str, ...] = STAGE2_TOOLS

    def __init__(
        self,
        brief: Brief,
        work: Bin,
        *,
        cap: float = DEFAULT_CAP,
        allowed: tuple[str, ...] = TECHNIQUES,
        max_turns: int = STAGE2_TURNS,
    ) -> None:
        super().__init__(brief, work, allowed=allowed, max_turns=max_turns)
        self.cap = cap
        self.blend_notes: list[str] = []
        self.review: list[ReviewRow] = []
        self.locked = {c.id: c.model_dump_json() for c in work.musts()}

    def found(self) -> list[checks.Fault]:
        return checks.check_stage2(self.brief, self.work, self.allowed, self.cap)

    def changed_must(self) -> list[str]:
        """The must clips that differ from what stage 1 handed over (a test, and the page, prove this is empty)."""
        now = {c.id: c.model_dump_json() for c in self.work.musts()}
        return sorted(i for i in self.locked if now.get(i) != self.locked[i]) + sorted(set(now) - set(self.locked))

    def seconds_line(self) -> str:
        n = self.work.counts()
        cap = checks.limit_s(self.brief, self.cap)
        if cap:
            return (
                f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must, {n['extra_take_s']} s cinematic); cap "
                f"{cap:g} s, {max(cap - n['take_s'], 0):g} s left."
            )
        return f"Seconds: {n['take_s']} s of takes."

    # ── the report ───────────────────────────────────────────────────────────────────────────────

    def report(self) -> str:
        found = self.found()
        mine = {e.id for e in self.work.extras()}
        again = {f.key for f in found if f.key in self.last_faults and set(f.clips) & self.touched}
        self.last_faults, self.touched = {f.key for f in found}, set()
        block = checks.blocking(found)
        self.progress(block)
        told = [f for f in found if f.fix == "report"]
        yours = [f for f in told if not f.clips or set(f.clips) & mine]
        locked = [f for f in told if f not in yours]

        def row(f: checks.Fault) -> str:
            return f"- {f.code}{' [' + ', '.join(f.clips) + ']' if f.clips else ''}: {f.sentence}"

        per = Counter(e.moment for e in self.work.extras())
        spread = ", ".join(f"moment {m}: {k}" for m, k in sorted(per.items())) or "none yet"
        head = (
            f"Report: {len(block)} blocking fault(s), {len(told)} report(s). Cinematic clips: {len(mine)} (at most "
            f"{checks.PER_MOMENT_MAX} a moment; {spread}). {self.seconds_line()} Turns left after this one: "
            f"{self.max_turns - self.turn}."
        )
        rows = [
            row(f) + ("  [STILL FAILING after your last change: change the approach]" if f.key in again else "")
            for f in block
        ]
        body = ("\nFix (blocking):\n" + "\n".join(rows)) if rows else "\nNothing blocks. You may call finish."
        if yours:
            body += "\nYours to fix where you can (they do not block finish):\n" + "\n".join(row(f) for f in yours)
        if locked:  # counted, not listed: the must clips are locked, so their reports are never this stage's to act on
            body += f"\nOn the locked must clips: {len(locked)} report(s), nothing to do."
        return head + body

    # ── stage 2's tools ──────────────────────────────────────────────────────────────────────────

    def tool_put_extras(self, args: dict[str, Any]) -> str:
        entries = ExtrasW.model_validate(args).clips  # all or nothing: a call that does not fit changes nothing
        added, replaced, refused = [], [], []
        for e in entries:
            clip_id = e.id.strip()
            if clip_id in self.locked:
                refused.append(
                    f'{clip_id} is a must clip of stage 1 and is locked (use "" to add a new cinematic clip)'
                )
                continue
            old = self.work.by_id(clip_id) if clip_id else None
            if clip_id and old is None:
                refused.append(f'{clip_id} is not in the bin (use "" for a new clip, or read_bin)')
                continue
            if old is not None:
                clip = self.work.replace(old.id, e.menu(), anchor=list(e.anchor), blend=e.blend)
                assert clip is not None
                replaced.append(clip)
                self.touched.add(clip.id)
            else:
                clip = self.work.add(e.menu(), stage=2, anchor=list(e.anchor), blend=e.blend)
                added.append(clip)
            clip.ir, clip.sound = e.ir, e.sound
        return self._summary(added, replaced, refused) + "\n" + self.report()

    def tool_remove_extras(self, args: dict[str, Any]) -> str:
        gone, refused = [], []
        for raw in args.get("clip_ids") or []:
            clip_id = str(raw)
            if clip_id in self.locked:
                refused.append(f"{clip_id} is a must clip of stage 1 and is locked.")
            elif self.work.remove(clip_id):
                gone.append(clip_id)
            else:
                refused.append(f"{clip_id} is not in the bin.")
        return (
            f"Removed {', '.join(gone) or 'nothing'}."
            + ("\n" + "\n".join(refused) if refused else "")
            + "\n"
            + self.report()
        )

    def tool_read_bin(self, args: dict[str, Any]) -> str:
        moment = int(args.get("moment") or 0)
        rows = []
        for c in self.work.clips:
            if moment and c.moment != moment:
                continue
            tag = f" CINEMATIC anchor {','.join(c.anchor)} blend {c.blend}" if c.is_extra else " LOCKED"
            rows.append(compact(c) + tag + self.states(c, moment))
        return f"{len(self.work.clips)} clips. " + ("\n" + "\n".join(rows) if rows else "The bin is empty.")

    def tool_finish(self, args: dict[str, Any]) -> str:
        if checks.blocking(self.found()):
            return "Refused: blocking faults remain.\n" + self.report()
        notes = [str(n).strip() for n in args.get("blend_notes") or [] if str(n).strip()]
        review = [ReviewRow.model_validate(r) for r in args.get("moment_review") or []]
        wrong = checks.review_faults(self.work, review)
        if wrong:
            return "Refused: the moment review does not match the bin.\n" + "\n".join(f"- {w}" for w in wrong)
        missing = checks.missing_blend_notes(self.work, notes)
        if missing:
            return (
                f"Refused: no blend note names {', '.join(missing)}. Give each cinematic clip one note that starts "
                f"with its "
                "id: where it goes in the intended cut and over whose audio."
            )
        self.blend_notes, self.review = notes, review
        self.done = True
        return "Finished. The cinematic clips and your blend notes are written."
