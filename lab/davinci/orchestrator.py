"""The orchestrator (plan/2026-11-08d §4): a director model in a tool-calling loop, two kinds of worker called like tools,
code tools that judge, and `finish`, which refuses until the checks pass.

    Orchestrator(reading, backend, meter, folder).run()  ->  Outcome

The director decides what to do next. Workers: `coverage_planner` (cheap; a sequence's moments -> menu entries) and
`clip_writer` (cheap, parallel; menu entries -> Veo designs). Code tools: `read_bin`, `check` (coverage, clock,
feasibility, designs, consistency), `finish`. Memory ownership (§4.4): only the director changes the edit plan; a worker
writes only its own clips; only code assigns ids and slates; the work log records every call and fault.

Money: every model call goes through `Meter.guard` before it is sent and `Meter.charge` after (money.py). No budget is
shown to a model. The continuity critic of the plan (§4.2) is not in the lab: phase 0 needs the post team's cut to say
whether it earns its cost, and code checks the match rules it can (`checks.consistency`).
"""
from __future__ import annotations

import json
import threading
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
from .state import Bin, compact

PROMPTS = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Config:
    """The lab's choices (D7: the models are the person's; these are the lab's defaults, both listed in PRICES)."""

    director: tuple[str, str] = ("gpt-5", "medium")  # (model, effort)
    worker: tuple[str, str] = ("gpt-5-mini", "medium")
    director_max_output: int = 16_000  # reasoning included; it bounds the worst case of a turn
    worker_max_output: int = 20_000
    max_turns: int = 40
    batch: int = 6  # clips a clip writer designs in one call
    threads: int = 4
    scene: str = "1"  # the slate's scene number (D8)
    allowed: tuple[str, ...] = schema.TECHNIQUES  # the production's visual language (D3): every technique until it is set


@dataclass
class Outcome:
    stopped: str  # finished | cap | budget | turns | idle | error
    faults: list[checks.Fault] = field(default_factory=list)
    editor_notes: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def finished(self) -> bool:
        return self.stopped == "finished"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").rstrip()


def _params(sch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in sch.items() if k != "title"}


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def tool_specs() -> list[dict[str, Any]]:
    ids = {"type": "array", "items": {"type": "string"}}
    ints = {"type": "array", "items": {"type": "integer"}}
    texts = {"type": "array", "items": {"type": "string"}}
    return [
        {"type": "function", "name": "write_edit_plan", "strict": True, "parameters": _params(schema.edit_schema()),
         "description": "Write the intended cut: treatment, sequences, moments (every script block in exactly one moment). "
                        "Only you change it; call it again to replace it. Write it before the coverage."},
        {"type": "function", "name": "plan_coverage", "strict": True,
         "parameters": _obj(moments=ints, brief={"type": "string"}),
         "description": "Hand moments to the coverage planner (cheap; sees the whole sequence). Give a brief: the cut's "
                        "intent, what you want, what to avoid. Adds menu entries to the bin and returns them."},
        {"type": "function", "name": "add_clips", "strict": True, "parameters": _params(schema.menu_schema()),
         "description": "Add clips you plan yourself (a hard moment, or the replacement of a clip you removed)."},
        {"type": "function", "name": "write_clips", "strict": True, "parameters": _obj(clip_ids=ids, note={"type": "string"}),
         "description": "Send clips to the clip writers (cheap, parallel) to write each clip's Veo design. Send a whole "
                        "sequence in one call so the clips match. `note` names a fault to fix, or is empty."},
        {"type": "function", "name": "replace_clip", "strict": True,
         "parameters": _obj(clip_id={"type": "string"}, clip=_params(schema.menu_schema())["properties"]["clips"]["items"]),
         "description": "Put a new plan in place of a clip that is wrong. It keeps the clip's id and, for a must clip, its must "
                        "status; its design is cleared, so send it to write_clips. Prefer this to remove_clips."},
        {"type": "function", "name": "remove_clips", "strict": True, "parameters": _obj(clip_ids=ids),
         "description": "Take clips out of the bin. REFUSED for a clip whose removal would leave a block, a moment or a line "
                        "without its must clip or its performer: replace_clip it, or add its replacement first. A design "
                        "fault is cured by write_clips, not by removing the clip."},
        {"type": "function", "name": "read_bin", "strict": True, "parameters": _obj(moment={"type": "integer"}),
         "description": "The clips in the bin, one row each. moment 0 = every moment."},
        {"type": "function", "name": "check", "strict": True, "parameters": _obj(),
         "description": "Run the code checks (coverage, clock, feasibility, designs, consistency). Every fault names its owner "
                        "and whether it blocks `finish`. Returns the work log's last entries too."},
        {"type": "function", "name": "finish", "strict": True, "parameters": _obj(editor_notes=texts),
         "description": "Write the result: the intended cut, the shoot bin and your editor notes. REFUSES until the checks "
                        "pass. It is the last call."}]


class Orchestrator:
    def __init__(self, reading: pack.Reading, backend: Backend, meter: Meter, folder: Path, cfg: Config | None = None) -> None:
        self.reading, self.backend, self.meter, self.folder = reading, backend, meter, folder
        self.cfg = cfg or Config()
        self.work = Bin(scene=self.cfg.scene)
        self.editor_notes: list[str] = []
        self.done = False
        self.stop = ""  # set by a tool when the run must end: cap | budget
        self.detail = ""
        self.last_faults: set[str] = set()
        self.ctx = 0  # an estimate (high) of the director's context in tokens
        self.trace = folder / "trace.jsonl"
        self._trace_lock = threading.Lock()
        self.system = prompt("director")
        self.base = pack.message(reading)

    # ── tracing ──────────────────────────────────────────────────────────────────────────────────

    def record(self, entry: dict[str, Any]) -> None:
        with self._trace_lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with self.trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── the loop ─────────────────────────────────────────────────────────────────────────────────

    def run(self) -> Outcome:
        model, effort = self.cfg.director
        note = self.length_note()
        opening = f"{self.base}\n\n" + (f"{note}\n\n" if note else "") + "Plan this scene. Start with the intended cut."
        specs = tool_specs()
        self.ctx = tokens_of(self.system + opening + json.dumps(specs))
        items: list[dict[str, Any]] = [{"role": "user", "content": opening}]
        previous: str | None = None
        idle = 0
        for turn in range(1, self.cfg.max_turns + 1):
            try:
                worst = self.meter.guard(model, self.ctx, self.cfg.director_max_output)
            except CapReached as exc:
                return self.end("cap", str(exc))
            except LabError as exc:
                return self.end("budget", str(exc))
            try:
                reply = self.backend.step(system=self.system, items=items, previous_id=previous, tools=specs, model=model,
                                          effort=effort, max_output=self.cfg.director_max_output)
            except Exception as exc:  # the call may still have been billed: entered at its worst case
                self.meter.fail("director", model, effort, worst, type(exc).__name__)
                return self.end("error", f"The director's call failed ({type(exc).__name__}: {exc}).")
            self.charge("director", model, effort, reply, worst, turn)
            self.ctx += (reply.usage.output_tokens if reply.usage and reply.usage.reported else self.cfg.director_max_output)
            previous = reply.id
            if not reply.calls:
                idle += 1
                if idle > 2:
                    return self.end("idle", "The director stopped calling tools before `finish`.")
                items = [{"role": "user", "content": "Continue with a tool call. When the bin is complete and `check` passes, "
                                                     "call `finish`."}]
                continue
            outputs = []
            for call in reply.calls:
                result = self.tool(call.name, call.args)
                self.record({"turn": turn, "tool": call.name, "args": call.args[:600], "result": result[:600]})
                outputs.append({"type": "function_call_output", "call_id": call.id, "output": result})
                self.ctx += tokens_of(result)
            if self.stop:
                return self.end(self.stop, self.detail)
            if self.done:
                return self.end("finished", "")
            items = outputs
        return self.end("turns", f"The director used all {self.cfg.max_turns} turns.")

    def length_note(self) -> str:
        """The length rule in words, with what is left (the model is told seconds, never money)."""
        limit = checks.limit_s(self.reading)
        if not limit:
            return ""
        used = sum(c.take_s for c in self.work.clips)
        return (f"<length>\nThe scene is {self.reading.guide_s:g} s long. The whole bin may hold at most {limit:g} s of takes "
                f"(that length + {checks.LENGTH_MARGIN:.0%}); it holds {used} s now, so {max(limit - used, 0):g} s are left. "
                "Spend them on the must clips first; a moment needs more than its must clip only where the story turns or a "
                "spoken line needs a second angle.\n</length>")

    def charge(self, slot: str, model: str, effort: str, reply: Reply, worst: float, turn: int = 0) -> None:
        spent = self.meter.charge(slot, model, effort, reply.usage, worst)
        self.record({"slot": slot, "model": model, "turn": turn, "dollars": round(spent, 4),
                     "usage": reply.usage.__dict__ if reply.usage else None, "calls": [c.name for c in reply.calls]})

    def end(self, stopped: str, detail: str) -> Outcome:
        found = checks.check_all(self.reading, self.work, self.cfg.allowed)
        return Outcome(stopped=stopped, faults=found, editor_notes=self.editor_notes, detail=detail)

    # ── tools ────────────────────────────────────────────────────────────────────────────────────

    def tool(self, name: str, raw: str) -> str:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return f"There is no tool {name}. Tools: {', '.join(s['name'] for s in tool_specs())}."
        try:
            args = json.loads(raw or "{}")
        except ValueError:
            return "The arguments are not valid JSON: send the arguments the tool's schema asks for."
        try:
            result = str(fn(args))
        except CapReached as exc:
            self.stop, self.detail = "cap", str(exc)
            result = "The run has ended."
        except LabError as exc:
            self.stop, self.detail = "budget", str(exc)
            result = "The run has ended."
        except ValidationError as exc:
            result = f"The arguments do not fit the tool's schema: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}."
        except Exception as exc:
            result = f"A worker call failed ({type(exc).__name__}). Try again or do it yourself."
        self.work.note(tool=name, args=raw[:300], result=result[:300])
        return result

    def tool_write_edit_plan(self, args: dict[str, Any]) -> str:
        self.work.edit = schema.EditPlanW.model_validate(args)
        found = checks.edit_plan(self.reading.scene, self.work)
        rows = "\n".join(f"- {f.sentence}" for f in found)
        return (f"The edit plan is saved: {len(self.work.edit.moments)} moments in {len(self.work.edit.sequences)} sequences."
                + (f"\nFix these (write_edit_plan again):\n{rows}" if rows else ""))

    def tool_read_bin(self, args: dict[str, Any]) -> str:
        moment = int(args.get("moment") or 0)
        rows = [compact(c) for c in self.work.clips if not moment or c.moment == moment]
        counts = self.work.counts()
        return f"{counts['clips']} clips ({counts['written']} designed). " + ("\n" + "\n".join(rows) if rows else "The bin is empty.")

    def tool_remove_clips(self, args: dict[str, Any]) -> str:
        """Remove clips one at a time; a removal that would open a coverage hole is refused and the bin is left as it was."""
        scene, gone, refused = self.reading.scene, [], []
        for raw in args.get("clip_ids") or []:
            clip_id = str(raw)
            before = {f.key for f in checks.coverage(scene, self.work)}
            snapshot = list(self.work.clips)
            if not self.work.remove(clip_id):
                continue
            opened = [f for f in checks.coverage(scene, self.work) if f.key not in before]
            if opened:
                self.work.clips = snapshot
                self.work.reslate()
                refused.append(f"{clip_id} was not removed: it would leave " + "; ".join(f.sentence for f in opened[:3])
                               + ". Use replace_clip to change it, or add its replacement first.")
            else:
                gone.append(clip_id)
        return f"Removed {', '.join(gone) or 'nothing'}." + ("\n" + "\n".join(refused) if refused else "")

    def tool_replace_clip(self, args: dict[str, Any]) -> str:
        clip_id = str(args.get("clip_id") or "")
        entry = schema.MenuW.model_validate(args.get("clip") or {})
        setup = (entry.setup.strip()[:1] or "A").upper()
        new = self.work.replace(clip_id, entry.model_copy(update={"setup": setup if setup.isalpha() else "A"}))
        if new is None:
            return f"There is no clip {clip_id}. Use read_bin."
        return f"{clip_id} now reads:\n{compact(new)}\nIt has no design yet: send it to write_clips."

    def tool_add_clips(self, args: dict[str, Any]) -> str:
        entries = schema.MenuListW.model_validate(args).clips
        added = [self.add(e) for e in entries]
        return f"Added {len(added)} clips:\n" + "\n".join(compact(c) for c in added)

    def add(self, entry: schema.MenuW) -> schema.Clip:
        setup = (entry.setup.strip()[:1] or "A").upper()
        return self.work.add(entry.model_copy(update={"setup": setup if setup.isalpha() else "A"}))

    # the coverage planner ------------------------------------------------------------------------

    def edit_context(self, hot: set[int]) -> str:
        plan = self.work.edit
        assert plan is not None
        body = {"treatment": plan.treatment.model_dump(), "sequences": [s.model_dump() for s in plan.sequences],
                "moments": [{**m.model_dump(), "asked_for": m.n in hot} for m in plan.moments]}
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def tool_plan_coverage(self, args: dict[str, Any]) -> str:
        if self.work.edit is None:
            return "Write the edit plan first (write_edit_plan): the coverage serves it."
        known = {m.n for m in self.work.edit.moments}
        asked = [int(m) for m in args.get("moments") or []]
        unknown = [m for m in asked if m not in known]
        if unknown or not asked:
            return f"Moments {unknown or 'none given'} are not in the edit plan (it has {sorted(known)})."
        user = (f"{self.base}\n\n{self.length_note()}\n\n<edit_plan>\n{self.edit_context(set(asked))}\n</edit_plan>\n\n<bin>\n"
                + ("\n".join(compact(c) for c in self.work.clips) or "(empty)") + f"\n</bin>\n\n<brief>\n{args.get('brief') or ''}\n</brief>")
        system = prompt("coverage")
        model, _ = self.cfg.worker
        worst = self.meter.guard(model, tokens_of(system + user + json.dumps(schema.menu_schema())), self.cfg.worker_max_output)
        reply = self.ask("coverage_planner", system, user, schema.menu_schema(), worst)
        try:
            menu = schema.MenuListW.model_validate_json(reply.text)
        except (ValidationError, ValueError) as exc:
            return f"The coverage planner's answer did not fit its schema ({str(exc)[:200]}). Ask again or plan these yourself."
        kept = [e for e in menu.clips if e.moment in asked]
        added = [self.add(e) for e in kept]
        dropped = len(menu.clips) - len(kept)
        return (f"The coverage planner added {len(added)} clips" + (f" ({dropped} for moments you did not ask for were left out)"
                                                                      if dropped else "") + ":\n" + "\n".join(compact(c) for c in added))

    def ask(self, slot: str, system: str, user: str, sch: dict[str, Any], worst: float) -> Reply:
        """One worker call. The guard has reserved `worst`; this releases it by charging or failing."""
        model, effort = self.cfg.worker
        try:
            reply = self.backend.structured(system=system, user=user, schema=sch, model=model, effort=effort,
                                            max_output=self.cfg.worker_max_output)
        except Exception as exc:
            self.meter.fail(slot, model, effort, worst, type(exc).__name__)
            raise
        self.charge(slot, model, effort, reply, worst)
        return reply

    # the clip writers ----------------------------------------------------------------------------

    def context_for(self, moments: set[int], skip: set[str]) -> str:
        """The first designed clip of each moment, so the next clips copy its setting, light and people word for word."""
        rows = []
        for n in sorted(moments):
            done = next((c for c in self.work.clips if c.moment == n and c.ir is not None and c.id not in skip), None)
            if done is not None and done.ir:
                subs = [{"id": s.get("id"), "description": s.get("description")} for s in done.ir.get("subjects") or []
                        if isinstance(s, dict)]
                rows.append({"moment": n, "from_clip": done.id, "setting": done.ir.get("setting"),
                             "lighting": done.ir.get("lighting"), "subjects": subs})
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":")) if rows else "(none yet)"

    def voice_only(self) -> str:
        """The people who are only heard, listed by code from the script, so a writer cannot miss the rule."""
        names = checks.heard_names(self.reading.scene)
        if not names:
            return ""
        return ("<voice_only>\n" + ", ".join(names) + ": heard and never seen. Do not put them in subjects or first_frame, and do "
                "not name them anywhere in a clip's picture text, not even as the person someone listens to.\n</voice_only>\n\n")

    def tool_write_clips(self, args: dict[str, Any]) -> str:
        if self.work.edit is None:
            return "Write the edit plan first (write_edit_plan)."
        wanted = [str(i) for i in args.get("clip_ids") or []]
        clips = [c for i in wanted if (c := self.work.by_id(i)) is not None]
        missing = [i for i in wanted if self.work.by_id(i) is None]
        if not clips:
            return f"No such clips: {missing}. Use read_bin."
        seq_of = {m.n: m.sequence for m in self.work.edit.moments}
        clips.sort(key=lambda c: (seq_of.get(c.moment, ""), c.moment, c.id))
        batches: list[list[schema.Clip]] = []
        for c in clips:  # one batch per sequence, cut to `batch` clips: a writer sees a whole sequence's neighbours
            if batches and len(batches[-1]) < self.cfg.batch and seq_of.get(batches[-1][0].moment) == seq_of.get(c.moment):
                batches[-1].append(c)
            else:
                batches.append([c])
        system = prompt("clip_writer")
        users = []
        for b in batches:
            moments = {c.moment for c in b}
            rows = [c.model_dump(exclude={"ir", "sound", "slate", "editor_note"}) for c in b]
            users.append(f"{self.base}\n\n<edit_plan>\n{self.edit_context(moments)}\n</edit_plan>\n\n<clips>\n"
                         f"{json.dumps(rows, ensure_ascii=False, separators=(',', ':'))}\n</clips>\n\n<context>\n"
                         f"{self.context_for(moments, {c.id for c in b})}\n</context>\n\n<note>\n{args.get('note') or ''}\n</note>")
        model, _ = self.cfg.worker
        sch = schema.ir_list_schema()
        reserved: list[float] = []
        try:
            for u in users:  # reserve every call's worst case BEFORE any is sent, so the group cannot pass the budget
                reserved.append(self.meter.guard(model, tokens_of(system + u + json.dumps(sch)), self.cfg.worker_max_output))
        except (CapReached, LabError):
            for r in reserved:
                self.meter.release(r)
            raise

        def one(user: str, worst: float) -> Reply | Exception:
            try:
                return self.ask("clip_writer", system, user, sch, worst)
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=self.cfg.threads) as pool:
            replies = list(pool.map(one, users, reserved))
        written, problems = 0, []
        for b, reply in zip(batches, replies, strict=True):
            if isinstance(reply, Exception):
                problems.append(f"{', '.join(c.id for c in b)}: the call failed ({type(reply).__name__})")
                continue
            try:
                designs = schema.IrListW.model_validate_json(reply.text).designs
            except (ValidationError, ValueError) as exc:
                problems.append(f"{', '.join(c.id for c in b)}: the answer did not fit its schema ({str(exc)[:120]})")
                continue
            mine = {c.id: c for c in b}
            for d in designs:
                if d.id in mine:
                    mine[d.id].ir, mine[d.id].sound = d.ir, d.sound
                    written += 1
            problems += [f"{i}: no design came back" for i in mine if mine[i].ir is None and i not in {d.id for d in designs}]
        missing_note = f" Unknown ids: {missing}." if missing else ""
        return f"Designed {written} of {len(clips)} clips in {len(batches)} call(s)." + missing_note + (
            "\nProblems:\n" + "\n".join(problems) if problems else "")

    # checks and finish ---------------------------------------------------------------------------

    def tool_check(self, args: dict[str, Any]) -> str:
        found = checks.check_all(self.reading, self.work, self.cfg.allowed)
        again = {f.key for f in found} & self.last_faults
        self.last_faults = {f.key for f in found}
        rows = [f.line() + ("  [STILL FAILING after your last fix: try something else]" if f.key in again else "") for f in found]
        n = self.work.counts()
        tail = [f"- {e['tool']}: {e['result'][:100]}" for e in self.work.log[-6:]]
        return (f"{len(checks.blocking(found))} blocking fault(s), {len(found) - len(checks.blocking(found))} report(s). "
                f"Bin: {n['clips']} clips ({n['written']} designed; {n['must']} must, {n['should']} should, {n['nice']} nice).\n"
                + ("\n".join(rows) if rows else "No faults.") + ("\nWork log (latest):\n" + "\n".join(tail) if tail else ""))

    def tool_finish(self, args: dict[str, Any]) -> str:
        found = checks.check_all(self.reading, self.work, self.cfg.allowed)
        blocking = checks.blocking(found)
        if blocking:
            self.last_faults = {f.key for f in found}
            return ("Refused: the checks do not pass yet.\n" + "\n".join(f.line() for f in blocking)
                    + "\nFix these (reports do not block), then call finish again.")
        self.editor_notes = [str(n) for n in args.get("editor_notes") or []]
        self.done = True
        return "Finished. The intended cut, the shoot bin and your notes are written."
