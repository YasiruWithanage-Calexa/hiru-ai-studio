"""The staged runner (plan/2026-11-08d PLAN-B.md): the director decides every creative thing, code decides the order.

    Stages(reading, backend, meter, folder, cfg).run()  ->  StagedOutcome

    1. PLAN        the director, ONE structured call: the intended cut, the whole coverage menu, the look sheet.
                   Code checks it (`checks.plan_checks`) and mends what needs no judgement (`checks.mend`).
    2. REPAIR      only with blocking faults: the director again, ONE call with ALL the faults, returning the whole corrected
                   plan; kept only if it leaves fewer blocking faults; at most `repair_rounds` rounds.
    3. DESIGN      the clip writers, ALL clips at once in parallel (2-3 clips a call, grouped by sequence). Code then writes the
                   look sheet into every design (`checks.apply_looks`), so the angles of a moment cannot differ.
    4. RE-DESIGN   only the clips with a design fault, each with its own fault, in one parallel group; a design is replaced
                   only if the new one leaves fewer faults; at most `redesign_rounds` rounds.
    5. FINISH      code writes the result: the bin, or the best bin with its faults, marked incomplete (D1).

No loop, no turn limit, no tool calls: at most 1 + `repair_rounds` director calls and 1 + `redesign_rounds` groups of clip-writer
calls. Every model call goes through `Meter.guard` before it is sent and `Meter.charge` after (money.py); a parallel group is
reserved before any of it is sent. No model is shown a budget. Each stage's start, end, calls and dollars go to `trace.jsonl`
and `outcome.json`, so where the time went is measured and not inferred.

The orchestrator (orchestrator.py) is kept beside this, unchanged, as the record of runs 1 and 2.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cinematic import pack
from hiru_ai.core.tokens import tokens_of

from . import checks, schema
from .brain import Backend, Reply
from .money import CapReached, LabError, Meter
from .orchestrator import Outcome, prompt
from .state import Bin


@dataclass(frozen=True)
class Config:
    """The lab's choices (D7: the models are the person's; these are the lab's defaults, both listed in PRICES)."""

    director: tuple[str, str] = ("gpt-5", "medium")  # (model, effort)
    worker: tuple[str, str] = ("gpt-5-mini", "medium")
    director_max_output: int = 32_000  # a whole plan + menu with its reasoning
    worker_max_output: int = 20_000
    batch: int = 3  # clips a clip writer designs in one call
    threads: int = 8
    repair_rounds: int = 2
    redesign_rounds: int = 2
    scene: str = "1"  # the slate's scene number (D8)
    allowed: tuple[str, ...] = schema.TECHNIQUES  # the production's visual language (D3): every technique until it is set


@dataclass
class StagedOutcome(Outcome):
    stages: list[dict[str, Any]] = field(default_factory=list)  # per stage: start, end, seconds, calls, dollars, detail


class StageError(Exception):
    """A stage could not go on (a model's answer did not fit its schema, a call failed): the run ends and says why."""


def length_note(reading: pack.Reading) -> str:
    """The length rule in words (the model is told seconds, never money)."""
    limit = checks.limit_s(reading)
    if not limit:
        return ""
    return (f"<length>\nThe scene is {reading.guide_s:g} s long: that is the target. The whole bin may hold at most {limit:g} s of "
            f"takes (that length + {checks.LENGTH_MARGIN:.0%}); the extra is headroom and a hard cap, never a goal to fill. "
            "Plan the must clips first, one per beat; a moment needs more than its must clip only where the story turns or a "
            "spoken line needs a second angle.\n</length>")


def groups_of(clips: list[schema.Clip], plan: Bin, size: int) -> list[list[schema.Clip]]:
    """Batches for the clip writers: never across two sequences, never more than `size`, as even as it can be (7 clips with
    size 3 are 3 + 2 + 2, not 3 + 3 + 1)."""
    if plan.edit is None:
        return [[c] for c in clips]
    seq_of = {m.n: m.sequence for m in plan.edit.moments}
    order = {s.id: i for i, s in enumerate(plan.edit.sequences)}
    by_seq: dict[str, list[schema.Clip]] = {}
    for c in sorted(clips, key=lambda c: (order.get(seq_of.get(c.moment, ""), 99), c.moment, c.id)):
        by_seq.setdefault(seq_of.get(c.moment, ""), []).append(c)
    out: list[list[schema.Clip]] = []
    for mine in by_seq.values():
        parts = math.ceil(len(mine) / size)
        base, extra = divmod(len(mine), parts)
        start = 0
        for i in range(parts):
            end = start + base + (1 if i < extra else 0)
            out.append(mine[start:end])
            start = end
    return out


class Stages:
    def __init__(self, reading: pack.Reading, backend: Backend, meter: Meter, folder: Path, cfg: Config | None = None) -> None:
        self.reading, self.backend, self.meter, self.folder = reading, backend, meter, folder
        self.cfg = cfg or Config()
        self.work = Bin(scene=self.cfg.scene)
        self.base = pack.message(reading)
        self.stages: list[dict[str, Any]] = []
        self.detail = ""  # what the running stage did, in words (stored with its record)
        self.trace = folder / "trace.jsonl"
        self._trace_lock = threading.Lock()

    # ── tracing ──────────────────────────────────────────────────────────────────────────────────

    def record(self, entry: dict[str, Any]) -> None:
        with self._trace_lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with self.trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def timed(self, name: str, fn: Callable[[], None]) -> None:
        """Run one stage and record when it started and ended, how many calls it made and what they cost."""
        start, calls0, spent0 = time.time(), self.meter.calls, self.meter.spent
        self.detail = ""
        try:
            fn()
        finally:
            end = time.time()
            rec = {"stage": name, "start": time.strftime("%H:%M:%S", time.localtime(start)),
                   "end": time.strftime("%H:%M:%S", time.localtime(end)), "seconds": round(end - start, 1),
                   "calls": self.meter.calls - calls0, "dollars": round(self.meter.spent - spent0, 4), "detail": self.detail}
            self.stages.append(rec)
            self.record({"stage_done": rec})

    # ── the run ──────────────────────────────────────────────────────────────────────────────────

    def run(self) -> StagedOutcome:
        try:
            self.timed("plan", self.plan_stage)
            self.timed("repair", self.repair_stage)
            self.timed("design", self.design_stage)
            self.timed("redesign", self.redesign_stage)
        except CapReached as exc:
            return self.end("cap", str(exc))
        except LabError as exc:
            return self.end("budget", str(exc))
        except StageError as exc:
            return self.end("error", str(exc))
        except Exception as exc:  # the call itself failed: it is already entered at its worst case
            return self.end("error", f"A model call failed ({type(exc).__name__}: {exc}).")
        return self.end("", "")

    def end(self, stopped: str, detail: str) -> StagedOutcome:
        """Stage 5: the faults that remain decide what the result is called (D1: an incomplete bin is saved and marked)."""
        found = checks.check_all(self.reading, self.work, self.cfg.allowed)
        left = checks.blocking(found)
        if not stopped:
            stopped = "incomplete" if left else "finished"
            detail = (f"{len(left)} blocking fault(s) remain: the bin is saved and marked incomplete (D1)." if left else "")
        notes = list(self.work.edit.editor_notes) if self.work.edit else []
        self.record({"end": stopped, "detail": detail})
        return StagedOutcome(stopped=stopped, faults=found, editor_notes=notes, detail=detail, stages=self.stages)

    # ── model calls ──────────────────────────────────────────────────────────────────────────────

    def call(self, slot: str, who: tuple[str, str], system: str, user: str, sch: dict[str, Any], max_output: int,
             worst: float | None = None) -> Reply:
        """One structured call. The guard reserves its worst case first (unless the caller reserved a whole group); this
        releases the reservation by charging the call, or by entering it at its worst case when it failed."""
        model, effort = who
        if worst is None:
            worst = self.meter.guard(model, tokens_of(system + user + json.dumps(sch)), max_output)
        try:
            reply = self.backend.structured(system=system, user=user, schema=sch, model=model, effort=effort, max_output=max_output)
        except Exception as exc:
            self.meter.fail(slot, model, effort, worst, type(exc).__name__)
            self.record({"slot": slot, "model": model, "failed": type(exc).__name__})
            raise
        spent = self.meter.charge(slot, model, effort, reply.usage, worst)
        self.record({"slot": slot, "model": model, "dollars": round(spent, 4),
                     "usage": reply.usage.__dict__ if reply.usage else None})
        return reply

    def parallel(self, system: str, users: list[str], sch: dict[str, Any]) -> list[Reply | Exception]:
        """Clip-writer calls in parallel. Every call's worst case is reserved BEFORE any is sent, so the group cannot pass the
        lab's budget; a call that fails is returned, not raised, so the others are kept."""
        model, _ = self.cfg.worker
        reserved: list[float] = []
        try:
            for u in users:
                reserved.append(self.meter.guard(model, tokens_of(system + u + json.dumps(sch)), self.cfg.worker_max_output))
        except (CapReached, LabError):
            for r in reserved:
                self.meter.release(r)
            raise

        def one(user: str, worst: float) -> Reply | Exception:
            try:
                return self.call("clip_writer", self.cfg.worker, system, user, sch, self.cfg.worker_max_output, worst)
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=max(self.cfg.threads, 1)) as pool:
            return list(pool.map(one, users, reserved))

    # ── stage 1: plan ────────────────────────────────────────────────────────────────────────────

    def opening(self) -> str:
        note = length_note(self.reading)
        return (f"{self.base}\n\n" + (f"{note}\n\n" if note else "")
                + "Plan this scene in one answer: the intended cut, the whole coverage menu and the look sheet.")

    @staticmethod
    def parse(text: str) -> schema.PlanW:
        try:
            return schema.PlanW.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            raise StageError(f"The director's answer did not fit its schema ({str(exc)[:240]}).") from exc

    def plan_stage(self) -> None:
        reply = self.call("director", self.cfg.director, prompt("director_plan"), self.opening(), schema.plan_schema(),
                          self.cfg.director_max_output)
        self.work.load(self.parse(reply.text))
        notes = checks.mend(self.reading, self.work)
        bad = checks.blocking(checks.plan_checks(self.reading, self.work, self.cfg.allowed))
        self.detail = (f"{len(self.work.clips)} clips, {sum(c.take_s for c in self.work.clips)} s; {len(bad)} blocking fault(s); "
                       f"mend: {len(notes)} fix(es)")
        self.record({"mend": notes, "faults": [f.line() for f in bad]})

    # ── stage 2: repair ──────────────────────────────────────────────────────────────────────────

    def answer_text(self) -> str:
        """The director's own plan as it now stands, with code's ids on the clips so a fault can name its clip."""
        assert self.work.edit is not None
        fields = set(schema.MenuW.model_fields)
        body = {"edit_plan": self.work.edit.model_dump(),
                "clips": [{"id": c.id, **c.model_dump(include=fields)} for c in self.work.clips],
                "looks": [m.model_dump() for m in self.work.looks]}
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def repair_message(self, found: list[checks.Fault]) -> str:
        rows = "\n".join(f"- {f.line()}" for f in checks.blocking(found))
        return (f"{self.opening()}\n\n<your_answer>\n{self.answer_text()}\n</your_answer>\n\n<faults>\n{rows}\n</faults>\n\n"
                f"{prompt('director_repair')}")

    def repair_stage(self) -> None:
        notes: list[str] = []
        for number in range(1, self.cfg.repair_rounds + 1):
            found = checks.plan_checks(self.reading, self.work, self.cfg.allowed)
            if not checks.blocking(found):
                break
            reply = self.call("director", self.cfg.director, prompt("director_plan"), self.repair_message(found),
                              schema.plan_schema(), self.cfg.director_max_output)
            try:
                plan = self.parse(reply.text)
            except StageError as exc:
                notes.append(f"round {number}: {exc} The earlier plan stays.")
                break
            trial = Bin(scene=self.cfg.scene, log=self.work.log)
            trial.load(plan)
            fixed = checks.mend(self.reading, trial)
            after = checks.plan_checks(self.reading, trial, self.cfg.allowed)
            kept = checks.better(after, found)
            notes.append(f"round {number}: {len(checks.blocking(found))} -> {len(checks.blocking(after))} blocking fault(s), "
                         + ("kept" if kept else "NOT kept (not fewer faults)"))
            self.record({"repair_round": number, "kept": kept, "mend": fixed, "faults": [f.line() for f in checks.blocking(after)]})
            if kept:
                self.work = trial
        self.detail = "; ".join(notes) or "no blocking fault: nothing to repair"

    # ── stage 3: design ──────────────────────────────────────────────────────────────────────────

    def voice_only(self) -> str:
        """The people who are only heard, listed by code from the script, so a writer cannot miss the rule."""
        names = checks.heard_names(self.reading.scene)
        if not names:
            return ""
        return ("<voice_only>\n" + ", ".join(names) + ": heard and never seen. Do not put them in subjects or first_frame, and do "
                "not name them anywhere in a clip's picture text, not even as the person someone listens to.\n</voice_only>\n\n")

    def edit_context(self) -> str:
        assert self.work.edit is not None
        plan = self.work.edit
        body = {"treatment": plan.treatment.model_dump(), "sequences": [s.model_dump() for s in plan.sequences],
                "moments": [m.model_dump() for m in plan.moments]}
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def writer_message(self, group: list[schema.Clip], faults: dict[str, list[str]] | None = None) -> str:
        moments = {c.moment for c in group}
        rows = [c.model_dump(exclude={"ir", "sound", "slate", "editor_note"}) for c in group]
        sheet = [m.model_dump() for m in self.work.looks if m.moment in moments]
        text = (f"{self.base}\n\n<edit_plan>\n{self.edit_context()}\n</edit_plan>\n\n<looks>\n"
                f"{json.dumps(sheet, ensure_ascii=False, separators=(',', ':'))}\n</looks>\n\n<clips>\n"
                f"{json.dumps(rows, ensure_ascii=False, separators=(',', ':'))}\n</clips>\n\n{self.voice_only()}")
        if faults:
            text += "<faults>\n" + "\n".join(f"{c.id}: " + " ".join(faults[c.id]) for c in group if c.id in faults) + "\n</faults>"
        return text.rstrip()

    def design_faults(self) -> int:
        return len(checks.blocking(checks.design_checks(self.reading, self.work, self.cfg.allowed)))

    def design_group(self, groups: list[list[schema.Clip]], faults: dict[str, list[str]] | None = None,
                     *, replace_if_better: bool = False) -> list[str]:
        """Send each group of clips to a clip writer (all groups in parallel), put the designs in, write the look sheet over
        them. Returns the problems met (a failed call, an answer that did not fit, a clip with no design back)."""
        system = prompt("clip_writer_staged")
        users = [self.writer_message(g, faults) for g in groups]
        replies = self.parallel(system, users, schema.ir_list_schema())
        problems: list[str] = []
        for group, reply in zip(groups, replies, strict=True):
            names = ", ".join(c.id for c in group)
            if isinstance(reply, Exception):
                problems.append(f"{names}: the call failed ({type(reply).__name__})")
                continue
            try:
                designs = schema.IrListW.model_validate_json(reply.text).designs
            except (ValidationError, ValueError) as exc:
                problems.append(f"{names}: the answer did not fit its schema ({str(exc)[:120]})")
                continue
            mine = {c.id: c for c in group}
            for d in designs:
                clip = mine.get(d.id)
                if clip is None:
                    continue
                old = (clip.ir, clip.sound)
                keep_old = replace_if_better and old[0] is not None  # a clip with no design takes any design
                before = self.design_faults() if keep_old else 0
                clip.ir, clip.sound = d.ir, d.sound
                checks.apply_looks(self.work)
                if keep_old and self.design_faults() >= before:  # not fewer faults: the old design stays
                    clip.ir, clip.sound = old
            problems += [f"{i}: no design came back" for i in mine if mine[i].ir is None and i not in {d.id for d in designs}]
        checks.apply_looks(self.work)
        return problems

    def design_stage(self) -> None:
        groups = groups_of(list(self.work.clips), self.work, self.cfg.batch)
        problems = self.design_group(groups)
        self.detail = (f"{len(self.work.clips)} clips in {len(groups)} parallel call(s); {self.design_faults()} design fault(s)"
                       + (f"; problems: {'; '.join(problems)}" if problems else ""))

    # ── stage 4: re-design ───────────────────────────────────────────────────────────────────────

    def failing(self) -> dict[str, list[str]]:
        """The clips a clip writer can still cure, each with the sentences of its own faults."""
        out: dict[str, list[str]] = {}
        for f in checks.blocking(checks.design_checks(self.reading, self.work, self.cfg.allowed)):
            if f.owner == "clip_writer":
                for i in f.clips:
                    out.setdefault(i, []).append(f.sentence)
        return out

    def redesign_stage(self) -> None:
        notes: list[str] = []
        for number in range(1, self.cfg.redesign_rounds + 1):
            faults = self.failing()
            if not faults:
                break
            clips = [c for c in self.work.clips if c.id in faults]
            problems = self.design_group(groups_of(clips, self.work, self.cfg.batch), faults, replace_if_better=True)
            left = len(self.failing())
            notes.append(f"round {number}: {len(clips)} clip(s) sent ({', '.join(c.id for c in clips)}), {left} still failing"
                         + (f"; problems: {'; '.join(problems)}" if problems else ""))
        self.detail = "; ".join(notes) or "no design fault: nothing to redo"


def worst_case_run(reading: pack.Reading, cfg: Config, price: Callable[[str, int, int], float]) -> list[tuple[str, float]]:
    """The most the whole staged run could cost, stage by stage, if every call spent every output token (`dry` prints it).
    `price(model, input_tokens, max_output)` is `money.worst_case`. The clip count is the most the length limit allows (4 s a
    clip) and every clip is assumed to fail its design once."""
    system = prompt("director_plan")
    opening = f"{pack.message(reading)}\n\n{length_note(reading)}\n\nPlan this scene in one answer."
    first = tokens_of(system + opening + json.dumps(schema.plan_schema()))
    d_model, w_model = cfg.director[0], cfg.worker[0]
    plan = price(d_model, first, cfg.director_max_output)
    repair = price(d_model, first + cfg.director_max_output + 3_000, cfg.director_max_output) * cfg.repair_rounds
    clips = max(int(checks.limit_s(reading) // 4), 1)
    calls = math.ceil(clips / cfg.batch) + 1  # the most calls one group needs, plus one for a sequence that splits unevenly
    writer = price(w_model, tokens_of(pack.message(reading)) + 9_000, cfg.worker_max_output)
    return [("plan", plan), ("repair", repair), ("design", calls * writer), ("redesign", calls * writer * cfg.redesign_rounds)]
