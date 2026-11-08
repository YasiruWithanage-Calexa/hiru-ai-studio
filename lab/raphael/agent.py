"""Raphael (plan/2026-11-08e §3): ONE model in a tool-calling loop, code tools only, no other model.

    Raphael(reading, backend, meter, folder).run()  ->  Outcome

Tools: `write_edit_plan`, `put_clips` (add or replace any number of complete clips: plan + Veo design), `remove_clips`
(refuses a removal that opens a coverage hole), `read_bin`, `finish` (refuses until no blocking fault remains). There is no
`check` tool: every write returns the check report of the whole bin, blocking faults first, each marked when it survived the
last change, with the seconds against the target (the given length) and the cap (given length x 1.5).

The checks, the bin, the edit plan's shape and the money rules are DaVinci's (R2: imported, so both labs are judged the same).
Fault owners shrink to two: `code` (a report: told, nothing to do) and Raphael (everything else, which it must fix).

Money: every model call goes through `Meter.guard` before it is sent and `Meter.charge` after. No budget is shown to the model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cinematic import pack
from davinci import checks
from davinci.brain import Backend, Reply
from davinci.money import CapReached, LabError, Meter
from davinci.state import Bin, compact
from hiru_ai.core.tokens import tokens_of

from . import schema

PROMPTS = Path(__file__).resolve().parent / "prompts"
MAX_ROWS = 30  # a report names at most this many blocking faults; the rest are counted
TOOLS = ("write_edit_plan", "put_clips", "remove_clips", "read_bin", "finish")


@dataclass(frozen=True)
class Config:
    """The lab's choices (D7: the model is the person's; the lab's first run is gpt-5 high, to compare with DaVinci)."""

    model: tuple[str, str] = ("gpt-5", "high")  # (model, effort)
    max_output: int = 48_000  # reasoning included; a sequence of complete clips per call. It bounds a turn's worst case
    max_turns: int = 20  # R1 (stage 2: 12, S4)
    prompt: str = "raphael"  # runs 1-3: "raphael"; S1 (must clips only, not yet paid for): "raphael_must"
    scene: str = "1"  # the slate's scene number (D8)
    allowed: tuple[str, ...] = schema.TECHNIQUES  # the production's visual language (D3): every technique until it is set


@dataclass
class Outcome:
    stopped: str  # finished | cap | budget | turns | idle | error
    turns: int = 0
    faults: list[checks.Fault] = field(default_factory=list)
    editor_notes: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def finished(self) -> bool:
        return self.stopped == "finished"


DROPPED = ("screen text",)  # the person (2026-11-08): phone close-ups are fine, so the shared screen-text report is dropped


def lab_checks(reading: pack.Reading, work: Bin, allowed: tuple[str, ...] = schema.TECHNIQUES) -> list[checks.Fault]:
    """DaVinci's checks (R2), minus the reports the person struck for Raphael. The shared check in `contracts.david` is
    unchanged, so every other planner is judged as before."""
    return [f for f in checks.check_all(reading, work, allowed)
            if not (f.code == "feasibility" and any(f.key.endswith(f":{d}") for d in DROPPED))]


def prompt(name: str = "raphael") -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").rstrip()


def _params(sch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in sch.items() if k != "title"}


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def tool_specs() -> list[dict[str, Any]]:
    ids = {"type": "array", "items": {"type": "string"}}
    texts = {"type": "array", "items": {"type": "string"}}
    return [
        {"type": "function", "name": "write_edit_plan", "strict": True, "parameters": _params(schema.edit_schema()),
         "description": "Write the intended cut: treatment, sequences, moments (every script block in exactly one moment). "
                        "Call it again to replace it. Write it first. Returns the check report."},
        {"type": "function", "name": "put_clips", "strict": True, "parameters": _params(schema.put_schema()),
         "description": "Add or replace clips, any number in one call, each COMPLETE: its plan and its Veo design (ir, "
                        "sound). id \"\" adds a new clip (code gives the id and slate); the id of a clip in the bin replaces "
                        "it (it keeps its id and slate, and a must clip stays must). Send a sequence at a time, and every "
                        "repair the report asks for in one call. Returns the check report of the whole bin."},
        {"type": "function", "name": "remove_clips", "strict": True, "parameters": _obj(clip_ids=ids),
         "description": "Take clips out of the bin. REFUSED for a clip whose removal would leave a block, a moment or a line "
                        "without its must clip or its performer: replace it with put_clips instead. Returns the check report."},
        {"type": "function", "name": "read_bin", "strict": True, "parameters": _obj(moment={"type": "integer"}),
         "description": "The clips in the bin, one row each (plan only, not the designs). moment 0 = every moment."},
        {"type": "function", "name": "finish", "strict": True, "parameters": _obj(editor_notes=texts),
         "description": "Write the result: the intended cut, the shoot bin and your editor notes. REFUSES until no blocking "
                        "fault remains. It is the last call."}]


def voice_only(reading: pack.Reading) -> str:
    """The people who are only heard, listed by code from the script, so the rule cannot be missed."""
    names = checks.heard_names(reading.scene)
    if not names:
        return ""
    return ("<voice_only>\n" + ", ".join(names) + ": heard and never seen. Never in subjects or first_frame, and never named in "
            "any clip's picture text, not even as the person someone listens to.\n</voice_only>")


def length_block(reading: pack.Reading) -> str:
    """The length rule in seconds (never money): the target is the given length, the cap is 1.5x and is hard."""
    cap = checks.limit_s(reading)
    if not cap:
        return ""
    return (f"<length>\nThe scene is {reading.guide_s:g} s long. TARGET: a bin of about {reading.guide_s:g} s of takes. "
            f"CAP: {cap:g} s of takes (the given length x {1 + checks.LENGTH_MARGIN:g}); `finish` refuses a bin over it. The room "
            "between the target and the cap is allowed, not expected.\n</length>")


class Raphael:
    SLOT = "raphael"  # the ledger's slot and the name in the trace
    TOOLS: tuple[str, ...] = TOOLS

    def __init__(self, reading: pack.Reading, backend: Backend, meter: Meter, folder: Path, cfg: Config | None = None) -> None:
        self.reading, self.backend, self.meter, self.folder = reading, backend, meter, folder
        self.cfg = cfg or Config()
        self.work = Bin(scene=self.cfg.scene)
        self.editor_notes: list[str] = []
        self.done = False
        self.turn = 0
        self.last_faults: set[str] = set()
        self.touched: set[str] = set()  # the clips the current write replaced: a fault on them that survives was tried before
        self.ctx = 0  # an estimate (high) of the conversation in tokens
        self.trace = folder / "trace.jsonl"
        self.system = prompt(self.cfg.prompt)
        self.opening = "\n\n".join(p for p in (pack.message(reading), voice_only(reading), length_block(reading),
                                               "Plan this scene. Start with the intended cut.") if p)

    def record(self, entry: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.trace.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── the loop ─────────────────────────────────────────────────────────────────────────────────

    def run(self) -> Outcome:
        model, effort = self.cfg.model
        specs = self.specs()
        self.ctx = tokens_of(self.system + self.opening + json.dumps(specs))
        items: list[dict[str, Any]] = [{"role": "user", "content": self.opening}]
        previous: str | None = None
        idle = 0
        for turn in range(1, self.cfg.max_turns + 1):
            self.turn = turn
            try:
                worst = self.meter.guard(model, self.ctx, self.cfg.max_output)
            except CapReached as exc:
                return self.end("cap", str(exc))
            except LabError as exc:
                return self.end("budget", str(exc))
            try:
                reply = self.backend.step(system=self.system, items=items, previous_id=previous, tools=specs, model=model,
                                          effort=effort, max_output=self.cfg.max_output)
            except Exception as exc:  # the call may still have been billed: entered at its worst case
                self.meter.fail(self.SLOT, model, effort, worst, type(exc).__name__)
                return self.end("error", f"The model call failed ({type(exc).__name__}: {exc}).")
            self.charge(model, effort, reply, worst, turn)
            self.ctx += reply.usage.output_tokens if reply.usage and reply.usage.reported else self.cfg.max_output
            previous = reply.id
            if not reply.calls:
                idle += 1
                if idle > 2:
                    return self.end("idle", f"{self.SLOT} stopped calling tools before `finish`.")
                items = [{"role": "user", "content": "Continue with a tool call. When no blocking fault remains, call `finish`."}]
                continue
            outputs = []
            for call in reply.calls:
                result = self.tool(call.name, call.args)
                self.record({"turn": turn, "tool": call.name, "args": call.args[:600], "result": result[:2000]})
                outputs.append({"type": "function_call_output", "call_id": call.id, "output": result})
                self.ctx += tokens_of(result)
                if self.done:
                    break
            if self.done:
                return self.end("finished", "")
            items = outputs
        return self.end("turns", f"{self.SLOT} used all {self.cfg.max_turns} turns.")

    def specs(self) -> list[dict[str, Any]]:
        return tool_specs()

    def charge(self, model: str, effort: str, reply: Reply, worst: float, turn: int) -> None:
        spent = self.meter.charge(self.SLOT, model, effort, reply.usage, worst)
        self.record({"slot": self.SLOT, "model": model, "turn": turn, "dollars": round(spent, 4),
                     "usage": reply.usage.__dict__ if reply.usage else None, "calls": [c.name for c in reply.calls]})

    def end(self, stopped: str, detail: str) -> Outcome:
        found = lab_checks(self.reading, self.work, self.cfg.allowed)
        return Outcome(stopped=stopped, turns=self.turn, faults=found, editor_notes=self.editor_notes, detail=detail)

    # ── the report every write returns ───────────────────────────────────────────────────────────

    def advice(self, f: checks.Fault) -> str:
        """DaVinci's sentence, except an overrun, which names the clip's blocks and the cure (run 2 added alternate angles over
        the same blocks, which overrun the same way). The check itself is DaVinci's and unchanged."""
        clip = self.work.by_id(f.clips[0]) if f.key.startswith("clock:overrun:") and f.clips else None
        if clip is None or len(clip.blocks) < 2:
            return f.sentence
        need = f.sentence.split(" needs ", 1)[1].split(" s ", 1)[0] if " needs " in f.sentence else "more"
        blocks = ", ".join(f"b{b}" for b in clip.blocks)
        return (f"{clip.id} carries blocks {blocks}, which need {need} s; its take is {clip.take_s} s and no take is longer than "
                "8 s. Split those blocks across clips that follow each other (each clip fewer blocks, neighbours may share "
                "one block), each the must clip of its blocks. Another angle over the SAME blocks overruns the same way.")

    def report(self) -> str:
        """The whole bin's checks. A fault is marked STILL FAILING when it was in the last report and this write replaced
        one of its clips: the fix was tried and did not work. A hole that is simply not built yet is never marked."""
        found = lab_checks(self.reading, self.work, self.cfg.allowed)
        again = {f.key for f in found if f.key in self.last_faults and set(f.clips) & self.touched}
        self.last_faults, self.touched = {f.key for f in found}, set()
        block, told = checks.blocking(found), [f for f in found if f.fix == "report"]
        n = self.work.counts()
        cap = checks.limit_s(self.reading)
        seconds = (f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must); target {self.reading.guide_s:g} s, cap {cap:g} s."
                   if cap else f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must).")
        rows = [f"- {f.code}{' [' + ', '.join(f.clips) + ']' if f.clips else ''}: {f.sentence}"
                + ("  [STILL FAILING after your last change: change the approach]" if f.key in again else "") for f in block]
        def row(f: checks.Fault) -> str:
            return f"- {f.code}{' [' + ', '.join(f.clips) + ']' if f.clips else ''}: {self.advice(f)}"

        # §3.2: two owners. `code` reports are told and need nothing; every other report is Raphael's to fix where it can.
        yours = [row(f) for f in told if f.owner != "code"]
        codes = [row(f) for f in told if f.owner == "code"]
        left = self.cfg.max_turns - self.turn
        head = (f"Report: {len(block)} blocking fault(s), {len(told)} report(s). Bin: {n['clips']} clips ({n['must']} must, "
                f"{n['should']} should, {n['nice']} nice). {seconds} Turns left after this one: {left}.")
        body = ("\nFix (blocking):\n" + "\n".join(rows)) if rows else (
            "\nNothing blocks." + (" Fix the reports below first where you can, then call finish." if yours else
                                   " You may call finish."))
        if yours:
            body += ("\nYours to fix (they do not block finish, but the editor gets them as they are; a line too long for "
                     "its take is fixed by overlapping clips, never by trimming):\n" + "\n".join(yours))
        if codes:
            body += "\nReported by code (nothing to do):\n" + "\n".join(codes)
        return head + body

    # ── tools ────────────────────────────────────────────────────────────────────────────────────

    def tool(self, name: str, raw: str) -> str:
        fn = getattr(self, f"tool_{name}", None) if name in self.TOOLS else None
        if fn is None:
            return f"There is no tool {name}. Tools: {', '.join(self.TOOLS)}."
        try:
            args = json.loads(raw or "{}")
        except ValueError:
            return "The arguments are not valid JSON: send the arguments the tool's schema asks for."
        try:
            result = str(fn(args))
        except ValidationError as exc:
            err = exc.errors()[0]
            result = f"The arguments do not fit the tool's schema: {err['msg']} at {err['loc']}. Nothing was changed."
        self.work.note(tool=name, args=raw[:300], result=result[:300])
        return result

    def tool_write_edit_plan(self, args: dict[str, Any]) -> str:
        self.work.edit = schema.EditPlanW.model_validate(args)
        return (f"The edit plan is saved: {len(self.work.edit.moments)} moments in {len(self.work.edit.sequences)} "
                f"sequences.\n{self.report()}")

    def tool_put_clips(self, args: dict[str, Any]) -> str:
        if self.work.edit is None:
            return "Write the edit plan first (write_edit_plan): the clips serve it. Nothing was changed."
        entries = schema.PutW.model_validate(args).clips  # all or nothing: a call that does not fit changes nothing
        added, replaced, refused = [], [], []
        for e in entries:
            menu = e.menu()
            letter = (menu.setup.strip()[:1] or "A").upper()
            menu = menu.model_copy(update={"setup": letter if letter.isalpha() else "A"})
            clip_id = e.id.strip()
            if clip_id:
                clip = self.work.replace(clip_id, menu)
                if clip is None:
                    refused.append(f"{clip_id} is not in the bin (use \"\" for a new clip, or read_bin)")
                    continue
                replaced.append(clip)
                self.touched.add(clip.id)
            else:
                clip = self.work.add(menu)
                added.append(clip)
            clip.ir, clip.sound = e.ir, e.sound
        parts = []
        if added:
            parts.append("Added " + ", ".join(f"{c.id} [{c.slate}]" for c in added) + ".")
        if replaced:
            parts.append("Replaced " + ", ".join(f"{c.id} [{c.slate}]" for c in replaced) + ".")
        if refused:
            parts.append("Not done: " + "; ".join(refused) + ".")
        return " ".join(parts or ["No clips were sent."]) + "\n" + self.report()

    def tool_remove_clips(self, args: dict[str, Any]) -> str:
        """Remove clips one at a time; a removal that would open a coverage hole is refused and the bin is left as it was."""
        scene, gone, refused = self.reading.scene, [], []
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
                refused.append(f"{clip_id} was not removed: it would leave " + "; ".join(f.sentence for f in opened[:3])
                               + ". Replace it with put_clips instead.")
            else:
                gone.append(clip_id)
        return (f"Removed {', '.join(gone) or 'nothing'}." + ("\n" + "\n".join(refused) if refused else "")
                + "\n" + self.report())

    def tool_read_bin(self, args: dict[str, Any]) -> str:
        moment = int(args.get("moment") or 0)
        rows = [compact(c) for c in self.work.clips if not moment or c.moment == moment]
        return f"{len(self.work.clips)} clips. " + ("\n" + "\n".join(rows) if rows else "The bin is empty.")

    def tool_finish(self, args: dict[str, Any]) -> str:
        found = lab_checks(self.reading, self.work, self.cfg.allowed)
        if checks.blocking(found):
            return "Refused: blocking faults remain.\n" + self.report()
        self.editor_notes = [str(n) for n in args.get("editor_notes") or []]
        self.done = True
        return "Finished. The intended cut, the shoot bin and your notes are written."
