"""Stage 2 of Raphael: the cinematic pass (plan/2026-11-08e §2.2, §3.5, phase 0c).

    load_stage1(folder)                                    the edit plan and the finished must bin of a stage 1 run
    CinematicPass(reading, work, backend, meter, folder).run()  ->  agent.Outcome

The same shape as stage 1: ONE model, one fresh conversation, code tools only, the check report after every write. It reads
the scene, the intended cut and stage 1's finished bin (locked) and adds cinematic clips (`should` / `nice`) on SELECTED
moments, each anchored to a must clip and saying how post blends it in. Its tools refuse every must clip id, so stage 1's
clips leave this stage exactly as they came in.

Tools: `put_extras` (add or replace cinematic clips, any number per call), `remove_extras` (cinematic clips only),
`read_bin`, `finish(blend_notes)`. The checks are every stage 1 check on the whole bin (DaVinci's, R2) plus `extra_checks`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from cinematic import pack
from davinci import checks
from davinci.brain import Backend
from davinci.checks import Fault
from davinci.money import Meter
from davinci.state import Bin, compact

from . import schema
from .agent import Config, Outcome, Raphael, _obj, _params, lab_checks, voice_only

TOOLS = ("put_extras", "remove_extras", "read_bin", "finish")
PER_MOMENT_MAX = 3  # S3, the person (2026-11-08, after pass 4): 3 a moment, blocking
STAGE2_MARGIN = 1.0  # S2, the person (2026-11-08, after pass 4): the whole bin may hold the given length x 2 once stage 2 adds


def stage2_config(**kw: Any) -> Config:
    """S4: the same model as stage 1, 12 turns."""
    return Config(**{"max_turns": 12, "prompt": "cinematic", **kw})


# ── stage 1's result, loaded (no stage 1 call) ───────────────────────────────────────────────────


def load_stage1(folder: Path, scene: str = "1") -> Bin:
    """A stage 1 run folder's edit plan and bin, as a `Bin` that gives the next clip id after stage 1's last. Refuses a run that
    did not finish: stage 2 adds to a complete must bin, it never repairs one."""
    outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
    if not outcome.get("complete", outcome.get("stopped") == "finished"):
        raise ValueError(f"{folder.name} did not finish (stopped: {outcome.get('stopped')}): stage 2 needs a finished must bin.")
    work = Bin(scene=scene)
    work.edit = schema.EditPlanW.model_validate_json((folder / "edit_plan.json").read_text(encoding="utf-8"))
    rows = json.loads((folder / "bin.json").read_text(encoding="utf-8"))
    layer = ("stage", "anchor", "blend")
    work.clips = [schema.Extra.model_validate(r) if r.get("stage") == 2 else
                  schema.Clip.model_validate({k: v for k, v in r.items() if k not in layer}) for r in rows]
    work._next = max((int(c.id[1:]) for c in work.clips), default=0) + 1
    if outcome.get("editor_notes"):
        work.edit = work.edit.model_copy(update={"editor_notes": list(outcome["editor_notes"])})
    return work


def is_extra(clip: schema.Clip) -> bool:
    return isinstance(clip, schema.Extra)


def extras(work: Bin) -> list[schema.Extra]:
    return [c for c in work.clips if isinstance(c, schema.Extra)]


def cap_s(reading: pack.Reading) -> float:
    """Stage 2's cap on the WHOLE bin: the given length x 2 (stage 1 keeps its own 1.5x). 0: no length was given."""
    return reading.guide_s * (1 + STAGE2_MARGIN)


# ── the new checks (§3.5) ────────────────────────────────────────────────────────────────────────


def _fault(code: str, sentence: str, clips: list[str], key: str, *, fix: str = "repair") -> Fault:
    return Fault(code=code, sentence=sentence, clips=clips, owner="clip_writer", fix=fix, key=key)  # type: ignore[arg-type]


def extra_checks(reading: pack.Reading, work: Bin) -> list[Fault]:
    """Anchored, silent, different from the anchor, at most 3 per moment, the whole bin within 2x (all blocking)."""
    out: list[Fault] = []
    must = {c.id: c for c in work.clips if not is_extra(c)}
    for e in extras(work):
        if e.priority == "must":
            out.append(_fault("cinematic", f"{e.id} is a cinematic clip marked must: must clips are stage 1's. Use should or "
                              "nice.", [e.id], f"cinematic:must:{e.id}"))
        if e.blend not in schema.BLENDS:
            out.append(_fault("cinematic", f"{e.id}'s blend \"{e.blend}\" is not one of {', '.join(schema.BLENDS)}.", [e.id],
                              f"cinematic:blend:{e.id}"))
        if e.speaks:
            out.append(_fault("cinematic", f"{e.id} is a cinematic clip and performs a line: a cinematic clip is silent "
                              "(speaks false); the dialogue stays on the must clips and post lays it under.", [e.id],
                              f"cinematic:speaks:{e.id}"))
        if not e.anchor:
            out.append(_fault("cinematic", f"{e.id} names no anchor: give the must clip it sits with.", [e.id],
                              f"cinematic:anchor:none:{e.id}"))
        near = {e.moment - 1, e.moment, e.moment + 1} if e.blend == "transition" else {e.moment}
        for a in e.anchor:
            anchor = must.get(a)
            if anchor is None:
                out.append(_fault("cinematic", f"{e.id}'s anchor {a} is not a must clip of the bin (the anchors are stage 1's "
                                  "clips; read_bin lists them).", [e.id], f"cinematic:anchor:unknown:{e.id}:{a}"))
            elif anchor.moment not in near:
                where = "the same or a neighbouring moment" if e.blend == "transition" else f"moment {e.moment}"
                out.append(_fault("cinematic", f"{e.id} is in moment {e.moment} and its anchor {a} is in moment "
                                  f"{anchor.moment}: an anchor is in {where}.", [e.id], f"cinematic:anchor:moment:{e.id}:{a}"))
            elif (anchor.role, anchor.technique) == (e.role, e.technique):
                out.append(_fault("cinematic", f"{e.id} is a {e.role} {e.technique} like its anchor {a}: that is an alternate, "
                                  "not a cinematic shot. Change its role or its technique.", [e.id],
                                  f"cinematic:same:{e.id}:{a}"))
    per = Counter(e.moment for e in extras(work))
    for n, k in sorted(per.items()):
        if k > PER_MOMENT_MAX:
            ids = [e.id for e in extras(work) if e.moment == n]
            out.append(_fault("cinematic", f"Moment {n} has {k} cinematic clips; at most {PER_MOMENT_MAX}: keep the strongest, "
                              "remove the rest or move one to a moment that earns it.", ids, f"cinematic:crowded:{n}"))
    cap, total = cap_s(reading), work.counts()["take_s"]
    if cap and total > cap + 1e-9:
        out.append(_fault("length", f"The bin holds {total} s of takes and may hold {cap:g} s (the scene's {reading.guide_s:g} s "
                          "x 2): drop nice cinematic clips first, then should. The must clips are locked.",
                          [e.id for e in extras(work)], "length:stage2"))
    return out


def all_checks(reading: pack.Reading, work: Bin, allowed: tuple[str, ...]) -> list[Fault]:
    """Stage 1's checks on the whole bin (the 1.5x length fault replaced by stage 2's 2x cap) plus the cinematic checks."""
    kept = [f for f in lab_checks(reading, work, allowed) if f.key != "length:over"]
    return [*kept, *extra_checks(reading, work)]


# ── the first message ────────────────────────────────────────────────────────────────────────────


def _common(values: list[str]) -> str:
    values = [" ".join(v.split()) for v in values if v and v.strip()]
    return Counter(values).most_common(1)[0][0] if values else ""


def looks(work: Bin) -> dict[int, dict[str, Any]]:
    """Per moment, the words the must clips use for the place, the light and each person (the commonest), so a cinematic clip
    can copy them word for word and pass the consistency check."""
    out: dict[int, dict[str, Any]] = {}
    for n in sorted({c.moment for c in work.clips}):
        mine = [c for c in work.clips if c.moment == n and not is_extra(c) and c.ir]
        people: dict[str, list[str]] = {}
        for c in mine:
            for s in (c.ir or {}).get("subjects") or []:
                if isinstance(s, dict) and s.get("id"):
                    people.setdefault(str(s["id"]), []).append(str(s.get("description") or ""))
        out[n] = {"setting": _common([str((c.ir or {}).get("setting") or "") for c in mine]),
                  "lighting": _common([str((c.ir or {}).get("lighting") or "") for c in mine]),
                  "people": {k: _common(v) for k, v in sorted(people.items())}}
    return out


def _first_line(clip: schema.Clip) -> str:
    cam = (clip.ir or {}).get("cinematography") or {}
    return " ".join(str(cam.get("framing") or "").split())[:160] if isinstance(cam, dict) else ""


def must_table(work: Bin) -> str:
    rows = ["id | slate | moment | role | technique | size | take | covers | first line of its design"]
    for c in work.clips:
        if is_extra(c):
            continue
        covers = (f"b{','.join(str(b) for b in c.blocks)}" if c.blocks else "-") + (
            f" lines {','.join(c.lines)}{' (speaks)' if c.speaks else ''}" if c.lines else "")
        rows.append(f"{c.id} | {c.slate} | {c.moment} | {c.role} | {c.technique} | {c.size} | {c.take_s} s | {covers} | "
                    f"{_first_line(c)}")
    return "\n".join(rows)


def cut_block(work: Bin) -> str:
    plan = work.edit
    assert plan is not None
    t = plan.treatment
    seq = "\n".join(f"- {s.id}: {json.dumps(s.model_dump(), ensure_ascii=False)}" for s in plan.sequences)
    moments = "\n".join(f"- moment {m.n} (sequence {m.sequence}, blocks {m.blocks}): {m.what} Feeling: {m.feeling} The cut uses: "
                        f"{m.cut_uses}" for m in plan.moments)
    return (f"<intended_cut>\nLogline: {t.logline}\nApproach: {t.approach}\nKey image: {t.key_image}\nGeography: {t.geography}\n"
            f"Sequences:\n{seq}\nMoments:\n{moments}\n</intended_cut>")


def looks_block(work: Bin) -> str:
    lines = []
    for n, look in looks(work).items():
        people = "; ".join(f"{k}: {v}" for k, v in look["people"].items())
        lines.append(f"moment {n}\n  setting: {look['setting']}\n  lighting: {look['lighting']}\n  people: {people or '-'}")
    return ("<looks>\nThe words the must clips of each moment use. A cinematic clip of that moment copies them WORD FOR WORD "
            "(setting, lighting, each person's description): code checks it.\n" + "\n".join(lines) + "\n</looks>")


def room_block(reading: pack.Reading, work: Bin) -> str:
    cap = cap_s(reading)
    held = work.counts()["take_s"]
    room = (f"The scene is {reading.guide_s:g} s long. The must bin holds {held} s of takes. CAP: {cap:g} s of takes for the "
            f"WHOLE bin (the given length x {1 + STAGE2_MARGIN:g}): {max(cap - held, 0):g} s left for cinematic clips. "
            if cap else f"The must bin holds {held} s of takes. ")
    return (f"<room>\n{room}Use it on the moments that earn it, the turning moments first; never on repeats of a must "
            f"angle. At most {PER_MOMENT_MAX} cinematic clips in any moment. `finish` asks for a review of EVERY moment.\n</room>")


# ── the pass ─────────────────────────────────────────────────────────────────────────────────────


class CinematicPass(Raphael):
    SLOT = "cinematic"
    TOOLS: tuple[str, ...] = TOOLS

    def __init__(self, reading: pack.Reading, work: Bin, backend: Backend, meter: Meter, folder: Path,
                 cfg: Config | None = None) -> None:
        super().__init__(reading, backend, meter, folder, cfg or stage2_config())
        self.work = work
        self.blend_notes: list[str] = []
        self.review: list[dict[str, Any]] = []
        self.locked = {c.id: c.model_dump_json() for c in work.clips if not is_extra(c)}
        self.opening = "\n\n".join(p for p in (
            pack.message(reading), voice_only(reading), cut_block(work),
            "<must_bin>\nStage 1's finished bin: the must clips, LOCKED (you cannot change or remove them).\n"
            + must_table(work) + "\n</must_bin>", looks_block(work), room_block(reading, work),
            "Review every moment: which earn cinematic clips and what kind (the turning moments first), then write them.") if p)

    def specs(self) -> list[dict[str, Any]]:
        ids = {"type": "array", "items": {"type": "string"}}
        texts = {"type": "array", "items": {"type": "string"}}
        return [
            {"type": "function", "name": "put_extras", "strict": True, "parameters": _params(schema.extras_schema()),
             "description": "Add or replace cinematic clips, any number in one call, each COMPLETE: its plan, its Veo design "
                            "(ir, sound), its anchor (the must clip id(s) it sits with) and its blend. id \"\" adds a new clip "
                            "(code gives the id and slate); the id of one of YOUR cinematic clips replaces it. A must clip id "
                            "is refused: the must clips are locked. Returns the check report of the whole bin."},
            {"type": "function", "name": "remove_extras", "strict": True, "parameters": _obj(clip_ids=ids),
             "description": "Take cinematic clips out of the bin. A must clip id is refused. Returns the check report."},
            {"type": "function", "name": "read_bin", "strict": True, "parameters": _obj(moment={"type": "integer"}),
             "description": "The clips in the bin, one row each (plan only, not the designs; must clips marked LOCKED). "
                            "moment 0 = every moment."},
            {"type": "function", "name": "finish", "strict": True,
             "parameters": _obj(blend_notes=texts, moment_review={"type": "array", "items": _obj(
                 moment={"type": "integer"}, earns={"type": "boolean"}, why={"type": "string"})}),
             "description": "Write the result. blend_notes: for EACH cinematic clip, one note that starts with its id and says "
                            "where it goes in the intended cut and over whose audio. moment_review: EVERY moment of the intended "
                            "cut once: earns true when it has cinematic clips (why: what they give), false when it has none "
                            "(why: why it needs none). REFUSES until no blocking fault remains and the review matches the bin. "
                            "It is the last call."}]

    def end(self, stopped: str, detail: str) -> Outcome:
        found = all_checks(self.reading, self.work, self.cfg.allowed)
        return Outcome(stopped=stopped, turns=self.turn, faults=found, editor_notes=self.blend_notes, detail=detail)

    def changed_must(self) -> list[str]:
        """The must clips that differ from what stage 1 handed over (a test, and the page, prove this is empty)."""
        now = {c.id: c.model_dump_json() for c in self.work.clips if not is_extra(c)}
        return sorted(i for i in self.locked if now.get(i) != self.locked[i]) + sorted(set(now) - set(self.locked))

    # ── the report ───────────────────────────────────────────────────────────────────────────────

    def report(self) -> str:
        found = all_checks(self.reading, self.work, self.cfg.allowed)
        mine = {e.id for e in extras(self.work)}
        again = {f.key for f in found if f.key in self.last_faults and set(f.clips) & self.touched}
        self.last_faults, self.touched = {f.key for f in found}, set()
        block = checks.blocking(found)
        told = [f for f in found if f.fix == "report"]
        yours = [f for f in told if not f.clips or set(f.clips) & mine]
        locked = [f for f in told if f not in yours]

        def row(f: Fault) -> str:
            return f"- {f.code}{' [' + ', '.join(f.clips) + ']' if f.clips else ''}: {f.sentence}"

        n = self.work.counts()
        cap = cap_s(self.reading)
        extra_s = sum(e.take_s for e in extras(self.work))
        per = Counter(e.moment for e in extras(self.work))
        seconds = (f"Seconds: {n['take_s']} s of takes ({n['must_take_s']} s must, {extra_s} s cinematic); cap {cap:g} s, "
                   f"{max(cap - n['take_s'], 0):g} s left." if cap else f"Seconds: {n['take_s']} s of takes.")
        spread = ", ".join(f"moment {m}: {k}" for m, k in sorted(per.items())) or "none yet"
        head = (f"Report: {len(block)} blocking fault(s), {len(told)} report(s). Cinematic clips: {len(mine)} (at most "
                f"{PER_MOMENT_MAX} a moment; {spread}). {seconds} Turns left after this one: "
                f"{self.cfg.max_turns - self.turn}.")
        rows = [row(f) + ("  [STILL FAILING after your last change: change the approach]" if f.key in again else "")
                for f in block]
        body = ("\nFix (blocking):\n" + "\n".join(rows)) if rows else "\nNothing blocks. You may call finish."
        if yours:
            body += "\nYours to fix where you can (they do not block finish):\n" + "\n".join(row(f) for f in yours)
        if locked:  # counted, not listed: the must clips are locked, so their reports are never this stage's to act on
            body += f"\nOn the locked must clips: {len(locked)} report(s), nothing to do."
        return head + body

    # ── tools ────────────────────────────────────────────────────────────────────────────────────

    def tool_put_extras(self, args: dict[str, Any]) -> str:
        entries = schema.ExtrasW.model_validate(args).clips  # all or nothing: a call that does not fit changes nothing
        added, replaced, refused = [], [], []
        for e in entries:
            fields = e.model_dump(exclude={"id", "ir", "sound", "anchor", "blend"})
            letter = (str(fields["setup"]).strip()[:1] or "A").upper()
            fields["setup"] = letter if letter.isalpha() else "A"
            clip_id = e.id.strip()
            if clip_id in self.locked:
                refused.append(f"{clip_id} is a must clip of stage 1 and is locked (use \"\" to add a new cinematic clip)")
                continue
            old = self.work.by_id(clip_id) if clip_id else None
            if clip_id and old is None:
                refused.append(f"{clip_id} is not in the bin (use \"\" for a new clip, or read_bin)")
                continue
            if old is not None:
                new = schema.Extra(**fields, id=old.id, slate="", ir=e.ir, sound=e.sound, anchor=list(e.anchor), blend=e.blend)
                self.work.clips[self.work.clips.index(old)] = new
                replaced.append(new)
                self.touched.add(new.id)
            else:
                new = schema.Extra(**fields, id=f"c{self.work._next:02d}", slate="", ir=e.ir, sound=e.sound,
                                   anchor=list(e.anchor), blend=e.blend)
                self.work._next += 1
                self.work.clips.append(new)
                added.append(new)
            self.work.reslate()
        parts = []
        if added:
            parts.append("Added " + ", ".join(f"{c.id} [{c.slate}]" for c in added) + ".")
        if replaced:
            parts.append("Replaced " + ", ".join(f"{c.id} [{c.slate}]" for c in replaced) + ".")
        if refused:
            parts.append("Not done: " + "; ".join(refused) + ".")
        return " ".join(parts or ["No clips were sent."]) + "\n" + self.report()

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
        return (f"Removed {', '.join(gone) or 'nothing'}." + ("\n" + "\n".join(refused) if refused else "")
                + "\n" + self.report())

    def tool_read_bin(self, args: dict[str, Any]) -> str:
        moment = int(args.get("moment") or 0)
        rows = []
        for c in self.work.clips:
            if moment and c.moment != moment:
                continue
            tag = (f" CINEMATIC anchor {','.join(c.anchor)} blend {c.blend}" if isinstance(c, schema.Extra) else " LOCKED")
            rows.append(compact(c) + tag)
        return f"{len(self.work.clips)} clips. " + ("\n" + "\n".join(rows) if rows else "The bin is empty.")

    def tool_finish(self, args: dict[str, Any]) -> str:
        found = all_checks(self.reading, self.work, self.cfg.allowed)
        if checks.blocking(found):
            return "Refused: blocking faults remain.\n" + self.report()
        notes = [str(n).strip() for n in args.get("blend_notes") or [] if str(n).strip()]
        mine = [e.id for e in extras(self.work)]
        review = [r for r in args.get("moment_review") or [] if isinstance(r, dict)]
        wrong = self.review_faults(review)
        if wrong:
            return "Refused: the moment review does not match the bin.\n" + "\n".join(f"- {w}" for w in wrong)
        missing = [i for i in mine if not any(n.startswith(i) or f"{i} " in n or f"{i}:" in n for n in notes)]
        if missing:
            return (f"Refused: no blend note names {', '.join(missing)}. Give each cinematic clip one note that starts with its "
                    "id: where it goes in the intended cut and over whose audio.")
        self.blend_notes, self.review = notes, review
        self.done = True
        return "Finished. The cinematic clips and your blend notes are written."


    def review_faults(self, review: list[dict[str, Any]]) -> list[str]:
        """Every moment of the intended cut once, each with a reason; `earns` true exactly where cinematic clips are."""
        assert self.work.edit is not None
        moments = [m.n for m in self.work.edit.moments]
        has = {e.moment for e in extras(self.work)}
        seen = [int(r.get("moment") or 0) for r in review]
        out = [f"moment {n} is not reviewed" for n in moments if n not in seen]
        out += [f"moment {n} is reviewed {seen.count(n)} times" for n in sorted(set(seen)) if seen.count(n) > 1]
        out += [f"moment {n} is not in the intended cut" for n in sorted(set(seen) - set(moments))]
        for r in review:
            n, earns = int(r.get("moment") or 0), bool(r.get("earns"))
            if not str(r.get("why") or "").strip():
                out.append(f"moment {n} has no reason")
            if n in moments and earns != (n in has):
                out.append(f"moment {n} says earns {str(earns).lower()} but has {'cinematic clips' if n in has else 'none'}")
        return out


def dump(folder: Path, work: Bin) -> None:
    """`Bin.dump`, with every clip's layer named: `stage` 1 for the must clips, 2 (plus `anchor`, `blend`) for the rest."""
    work.dump(folder)
    rows = [{**c.model_dump(), "stage": 2} if is_extra(c) else {**c.model_dump(), "stage": 1, "anchor": [], "blend": ""}
            for c in work.clips]
    (folder / "bin.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


__all__ = ["TOOLS", "CinematicPass", "all_checks", "cap_s", "dump", "extra_checks", "extras", "is_extra", "load_stage1",
           "looks", "must_table", "stage2_config"]
