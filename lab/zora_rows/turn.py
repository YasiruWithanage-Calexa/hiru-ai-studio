"""One Zora turn on the shot rows, as plan/2026-11-12d §3.6 proposes (the lab's copy; nothing here is the product).

    read rows → in code (undo · redo · Accept · Reject · Use N) ─┬─ conduct → chat | clarify | cannot ─────────┐
                                                                 └─ conduct → edit | craft | options → kernel → │
                                                                    author → board → delivery → checks → repair │
                                                                    → risk ─┬─ safe: save                       │
                                                                            └─ risky: card, nothing saved ─ reply┘

`Thread` holds the scene now, the undo stack, the open card and proposals, and the conversation. `run_turn` returns a
record of everything that happened, for the results page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import agents
import checks
import risk
from coverage import CINE, IR_JSON, IR_TEXT, Clip, Coverage
from kernel import PROSE, Kernel

Row = dict[str, Any]
WRITING = ("edit", "craft", "options")
MIN_CONFIDENCE = 0.5
KIND_OF = {**{f: "camera" for f in ("size", "link", *CINE)}, **{f: "picture" for f in ("why", "sees", *IR_JSON)},
           "setting": "light", "lighting": "light", "audio": "sound"}
ACTION = re.compile(r"^\[(accept|reject|use (\d+))\]$", re.I)
UNDO = re.compile(r"^\s*(undo|go back|redo)\b", re.I)


@dataclass
class Card:
    ops: list[Row]  # [{"op": ..., "by": ...}] in the order they landed
    made_on: str
    reasons: list[str]
    lines: list[str]
    state: str = ""


@dataclass
class Thread:
    cov: Coverage
    history: list[str] = field(default_factory=list)
    undo: list[Coverage] = field(default_factory=list)
    redo: list[Coverage] = field(default_factory=list)
    card: Card | None = None
    proposals: list[Row] = field(default_factory=list)
    proposals_on: str = ""
    rejected: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)
    revision: int = 0


# ── the ledger: what changed, read from the two scenes ───────────────────────────────────────────────────────────


def _cmp(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def changes(before: Coverage, after: Coverage) -> list[str]:
    old = {c.h: c for c in before.clips}
    out: list[str] = []
    for c in after.clips:
        code = after.code(c.h)
        o = old.get(c.h)
        if o is None:
            word = "new" if c.new else "restored"
            out.append(f"{word} {code}: {c.priority} {c.role} {c.size} {c.take_s} s over "
                       f"{', '.join(f'b{i}' for i in c.blocks)}" + (f" — {_q(c.why)}" if c.why else ""))
            continue
        pairs = [("size", o.size, c.size), ("take", f"{o.take_s} s", f"{c.take_s} s"), ("join", o.link, c.link),
                 ("role", f"{o.priority} {o.role}", f"{c.priority} {c.role}"),
                 ("blocks", f"b{o.first}-b{o.last - 1}", f"b{c.first}-b{c.last - 1}"),
                 ("why", o.why, c.why), ("what we see", o.sees, c.sees)]
        pairs += [(k, o.cine(k), c.cine(k)) for k in CINE]
        pairs += [(k, o.ir.get(k), c.ir.get(k)) for k in (*IR_TEXT, *IR_JSON)]
        pairs += [(f"sound {k}", o.sound.get(k), c.sound.get(k)) for k in ("ambience", "effects", "music", "silence")]
        for name, a, b in pairs:
            if not _cmp(a, b):
                if name in IR_JSON:
                    out.append(f"{code} · {name} rewritten")
                else:
                    out.append(f"{code} · {name}: {_q(a)} → {_q(b)}")
        bn, an = before.number_of(c.h), after.number_of(c.h)
        if bn != an and [h for h in (x.h for x in before.clips) if after.clip(h)].index(c.h) != \
                [x.h for x in after.clips if before.clip(x.h)].index(c.h):
            out.append(f"S{bn:02d} moved to {code}")
    for h, o in old.items():
        if after.clip(h) is None:
            out.append(f"S{before.number_of(h):02d} [{o.slate}] removed ({o.priority} {o.role} {o.size})")
    for lid, ln in after.lines.items():
        was = before.lines[lid].by
        if ln.by != was:
            out.append(f"{lid} ({ln.speaker}) now performed by {label(after, ln.by)} (was {label(before, was)})")
    return out


def label(cov: Coverage, h: str) -> str:
    """A clip as a person finds it after a renumbering: its number now, its slate and its role."""
    c = cov.clip(h) if h else None
    return f"{cov.code(h)} [{c.slate or 'new'}] {c.role} {c.size}" if c else "no clip"


def _q(v: Any, n: int = 70) -> str:
    text = " ".join(str(v if v not in (None, "") else "-").split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ── the turn ──────────────────────────────────────────────────────────────────────────────────────────────────────


def run_turn(th: Thread, message: str, backend: Any, slot: str) -> Row:
    rec: Row = {"message": message, "slot": slot, "lane": "", "calls_from": len(backend.calls), "saved": False,
                "done": [], "refused": [], "team_refused": [], "notes": [], "undelivered": [], "reported": [],
                "kernel_notes": [], "card": None, "proposals": [], "repair": None, "fact": "", "author": [],
                "before_s": th.cov.total_s()}
    m = ACTION.match(message.strip())
    if m:
        _action(th, m, rec)
    elif UNDO.match(message):
        _undo(th, UNDO.match(message).group(1).lower(), rec)
    else:
        _conduct_and_work(th, message, backend, slot, rec)
    if rec["lane"] in ("action", "undo", "redo"):  # a click: the work is code's, the words are the reply's
        _reply(th, message, backend, slot, rec)
    rec["after_s"] = th.cov.total_s()
    rec["revision"] = th.revision
    rec["calls"] = backend.calls[rec.pop("calls_from"):]
    rec["dollars"] = round(sum(c.get("dollars", 0) for c in rec["calls"] if agents.counted(c)), 5)
    rec["dollars_compare"] = round(sum(c.get("dollars", 0) for c in rec["calls"] if not agents.counted(c)), 5)
    th.history.append(f"Director: {message}")
    th.history.append(f"Zora: {rec['reply']}")
    return rec


def _save(th: Thread, work: Coverage) -> None:
    th.undo.append(th.cov)
    th.redo.clear()
    th.cov = work
    th.revision += 1


def _undo(th: Thread, word: str, rec: Row) -> None:
    rec["lane"] = "undo" if word != "redo" else "redo"
    stack, other = (th.undo, th.redo) if word != "redo" else (th.redo, th.undo)
    if not stack:
        rec["status"] = f"Nothing to {rec['lane']}"
        rec["fact"] = f"THE PERSON ASKED TO {rec['lane'].upper()}, but there is nothing to {rec['lane']}."
        return
    before = th.cov
    other.append(th.cov)
    th.cov = stack.pop()
    th.revision += 1
    rec["done"] = changes(before, th.cov)
    rec["saved"] = True
    rec["status"] = f"{'Undone' if word != 'redo' else 'Redone'} · revision {th.revision}"
    rec["fact"] = ("THE PERSON ASKED TO UNDO: the scene is back to how it was before the last change (saved as "
                   f"revision {th.revision}; they can redo)." if word != "redo" else
                   f"THE PERSON ASKED TO REDO: the change is back (revision {th.revision}).")


def _apply_saved(th: Thread, ops: list[Row], made_on: str, rec: Row, label: str) -> None:
    if th.cov.fingerprint() != made_on:
        rec["status"] = f"{label}: refused (the scene changed)"
        rec["fact"] = (f"THE PERSON PRESSED {label.upper()}, but the scene changed since the card was made, so nothing "
                       "was applied: they should ask again and Zora works from the scene as it is now.")
        return
    work = th.cov.copy()
    k = Kernel(work)
    applied, refused = [], []
    batches: list[tuple[str, list[Row]]] = []  # the batches as they landed: numbers are read at each batch's start
    for o in ops:
        if batches and batches[-1][0] == o["by"]:
            batches[-1][1].append(o["op"])
        else:
            batches.append((o["by"], [o["op"]]))
    for by, batch in batches:
        r = k.apply(batch, by=by)
        applied += r.applied
        refused += [x["reason"] for x in r.rejected]
        rec["kernel_notes"] += r.notes
    if refused:
        rec["refused"] = refused
    rec["done"] = changes(th.cov, work)
    rec["reported"] = [f.sentence for f in checks.new(th.cov, work)]
    if rec["done"]:
        _save(th, work)
        rec["saved"] = True
    rec["status"] = f"{label} · revision {th.revision}" if rec["saved"] else f"{label}: nothing applied"
    rec["fact"] = (f"THE PERSON PRESSED {label.upper()}: the change is now saved (revision {th.revision}; they can "
                   "undo it)." if rec["saved"] else f"THE PERSON PRESSED {label.upper()}, but nothing could be applied.")


def _action(th: Thread, m: re.Match[str], rec: Row) -> None:
    word = m.group(1).lower()
    rec["lane"] = "action"
    if word in ("accept", "reject"):
        card = th.card
        if card is None or card.state:
            rec["status"] = "No card waiting"
            rec["fact"] = "THE PERSON PRESSED A BUTTON, but no card is waiting."
            return
        if word == "reject":
            card.state = "rejected"
            th.rejected.append("; ".join(card.reasons))
            rec["status"] = "Rejected · nothing changed"
            rec["fact"] = ("THE PERSON PRESSED REJECT on the card (" + "; ".join(card.reasons) + "): nothing changed, "
                           "and Zora will not offer it again in this thread.")
            return
        card.state = "accepted"
        _apply_saved(th, card.ops, card.made_on, rec, "Accepted")
        return
    n = int(m.group(2))
    if not 1 <= n <= len(th.proposals):
        rec["status"] = "Option not available"
        rec["fact"] = "THE PERSON PICKED AN OPTION that is no longer available."
        return
    p = th.proposals[n - 1]
    _apply_saved(th, [{"op": o, "by": "author"} for o in p["ops"]], th.proposals_on, rec, f"Used: {p['label']}")
    th.proposals = []


def _conductor_user(th: Thread, message: str, problems: list[str]) -> str:
    talk = "\n".join(th.history[-4:]) or "(no earlier messages)"
    text = (f"CONVERSATION (recent):\n{talk}\n\n{th.cov.render(only=set())}\n\n"
            + ("STANDING RULES FROM THE PERSON:\n" + "\n".join(f"- {r}" for r in th.memory) + "\n\n" if th.memory else "")
            + (f"THE PERSON REJECTED IN THIS THREAD (do not offer again): {'; '.join(th.rejected)}\n\n"
               if th.rejected else "")
            + f"LATEST MESSAGE FROM THE DIRECTOR:\n{message}")
    if problems:
        text += ("\n\nYOUR LAST ANSWER COULD NOT BE USED (answer again, the whole answer, fixing exactly this):\n"
                 + "\n".join(f"- {p}" for p in problems))
    return text


def _invented(op: Row, message: str) -> bool:
    if op.get("op") not in ("set", "insert") or (op.get("op") == "set" and op.get("field") not in PROSE):
        return False
    said = set(re.findall(r"\w+", message.lower()))
    words = re.findall(r"\w+", str(op.get("value") or op.get("what") or "").lower())
    return len(words) > 4 and len([w for w in words if w not in said]) > len(words) // 3


def left(backend: Any, rec: Row) -> float:
    """What the turn may still spend (the person's cap, run 4): the counted calls so far against TURN_CAP_USD."""
    spent = sum(c.get("dollars", 0) for c in backend.calls[rec["calls_from"]:] if agents.counted(c))
    return agents.TURN_CAP_USD - spent


SIZE_WORDS = {"wide": "WIDE", "wide shot": "WIDE", "ws": "WIDE", "medium": "MS", "medium shot": "MS", "ms": "MS",
              "mcu": "MCU", "medium close-up": "MCU", "medium close up": "MCU", "close-up": "CU", "close up": "CU",
              "closeup": "CU", "cu": "CU", "two-shot": "TWO", "two shot": "TWO", "ots": "OTS", "insert": "INSERT",
              "over the shoulder": "OTS", "over-the-shoulder": "OTS"}
QUICK_REMOVE = re.compile(r"(?:please\s+)?(?:drop|remove|delete|cut)\s+(s\d+)(?:\s*,.*)?", re.I)
QUICK_SET = re.compile(r"(?:please\s+)?(?:make\s+)?(s\d+)\s+(?:a\s+|an\s+|to\s+|into\s+)?(.+)", re.I)


def quick(message: str, cov: Coverage) -> Row | None:
    """A plain command code reads itself, with no model (run 4: "a small request under $0.001"): remove a shot, or set
    a shot's size and/or take ("Make S01 a wide, 6 seconds", "S04 to 8 seconds", "Drop S08"). Anything else is None
    and goes to the conductor."""
    text = message.strip().rstrip(".!")
    ops: list[Row] = []
    m = QUICK_REMOVE.fullmatch(text)
    if m and cov.at(m.group(1)):
        ops = [{"op": "remove", "shot": m.group(1).upper()}]
    m = None if ops else QUICK_SET.fullmatch(text)
    if m and cov.at(m.group(1)):
        for part in re.split(r"\s*(?:,|\band\b)\s*", m.group(2)):
            p = re.sub(r"^(a|an)\s+", "", part.strip().lower())
            t = re.fullmatch(r"(\d+)\s*(?:s|secs?|seconds?)(?:\s+long)?", p)
            if t and int(t.group(1)) in (4, 6, 8):
                ops.append({"op": "retime", "shot": m.group(1).upper(), "take_s": int(t.group(1))})
            elif p in SIZE_WORDS:
                ops.append({"op": "set", "shot": m.group(1).upper(), "field": "size", "value": SIZE_WORDS[p]})
            else:
                return None
    if not ops:
        return None
    return {"lane": "edit", "confidence": 1.0, "ops": ops, "tasks": [], "variants": 0, "cannot": None, "memory": "",
            "by_code": True}


def _conduct_and_work(th: Thread, message: str, backend: Any, slot: str, rec: Row) -> None:
    answer = quick(message, th.cov)
    if answer is not None:
        _route(th, answer, [], message, backend, slot, rec)
        return
    problems: list[str] = []
    for attempt in (1, 2):
        try:
            text, _ = backend.ask("conductor", f"{slot}.conductor{'' if attempt == 1 else '.retry'}",
                                  agents.prompt("conductor"), _conductor_user(th, message, problems),
                                  agents.conductor_schema(), budget=left(backend, rec))
        except (agents.OverBudget, agents.CutOff) as exc:
            if answer is None:  # no answer at all: the turn asks, it never guesses
                answer = {"lane": "clarify", "confidence": 0.0, "ops": [], "tasks": [], "variants": 0,
                          "cannot": None, "memory": ""}
            rec["team_refused"].append(f"reading the message stopped at the turn's budget ({exc})")
            break
        answer = json.loads(text)
        answer["ops"] = [agents.clean_op(o) for o in answer.get("ops") or []]
        problems = []
        if answer["lane"] in ("edit", "craft") and not answer["ops"] and not answer["tasks"]:
            problems.append(f"lane {answer['lane']} carries no operations and no tasks: give them, or choose the lane "
                            "that changes nothing")
        problems += [f"the {o.get('op')} on {o.get('shot') or 'the scene'} writes words the person did not say: make "
                     "it a task for the author" for o in answer["ops"] if _invented(o, message)]
        if not problems:
            break
    _route(th, answer, problems, message, backend, slot, rec)


def _route(th: Thread, answer: Row, problems: list[str], message: str, backend: Any, slot: str, rec: Row) -> None:
    rec["conductor"] = answer
    if problems:
        rec["team_refused"] += problems
        answer["ops"] = [o for o in answer["ops"] if not _invented(o, message)]
    if answer.get("memory"):
        th.memory.append(answer["memory"])
        rec["memory"] = answer["memory"]
    lane = answer["lane"]
    if answer["confidence"] < MIN_CONFIDENCE and lane in WRITING:
        lane = "clarify"
    rec["lane"] = lane
    if lane in WRITING:
        _work(th, answer, backend, slot, rec)
    elif lane == "cannot":
        c = answer.get("cannot") or {}
        rec["fact"] = (f"NOT POSSIBLE HERE: {c.get('reason', '')} Route: {c.get('route', '')} Every clip is generated "
                       "by Veo: never suggest ADR, a reshoot, a recorded take or an actor's new performance.")
    elif lane == "clarify":
        rec["fact"] = "THE REQUEST WAS NOT CLEAR: nothing was changed. Ask ONE short question that tells the readings apart."
    _reply(th, message, backend, slot, rec)


def _tasks(answer: Row, work: Coverage, before: Coverage) -> list[Row]:
    out = []
    # run 5: on an insert the conductor still wrote a task for the new clip, aimed at the wrong shot; code tasks it
    conductor_tasks = [] if any(o.get("op") == "insert" for o in answer.get("ops") or []) else answer.get("tasks") or []
    for t in conductor_tasks:
        # numbers as printed, BEFORE this turn's ops (run 2: the conductor mis-counted post-op numbers); a clip the
        # ops removed drops out, a new clip is tasked by code below
        hs = [c.h for n in t.get("shots") or [] if (c := before.at(n)) is not None and work.clip(c.h) is not None]
        out.append({"writes": list(t.get("writes") or []), "scope": hs, "instruction": t.get("instruction", "")})
    # code's tasks, from what the ops provably did (never from how a message reads):
    for c in work.clips:  # a new or re-cut clip needs its picture
        if not c.why.strip() and not any(c.h in t["scope"] and "picture" in t["writes"] for t in out):
            if c.sees and "sees" in c.locks:
                text = (f"write this new clip: why, camera, beats, subjects, first frame, sound, in the scene's "
                        f"continuity. The person asked for “{c.sees}” as a {c.size}: that is what we see "
                        "and its size (locked); build the picture on it")
            else:
                text = ("write this new or re-cut clip whole: why, what we see, camera, beats, subjects, first frame, "
                        "sound, in the scene's continuity")
            out.append({"writes": ["picture", "camera", "light", "sound"], "scope": [c.h], "code": True,
                        "instruction": text})
    for ln in work.lines.values():  # a clip that now performs a line must show its speaker saying it
        if ln.by and ln.by != before.lines[ln.lid].by and work.clip(ln.by) and work.clip(ln.by).why.strip():
            out.append({"writes": ["picture", "sound"], "scope": [ln.by], "code": True,
                        "instruction": f"this clip now performs {ln.lid}: make its picture show {ln.speaker} saying "
                                       "it on camera (lips, beats, subjects, audio); keep its size and length"})
    return out


def _author_user(th: Thread, work: Coverage, tasks: list[Row], done: list[str], variants: int, faults: list[str]) -> str:
    whole = any(not t["scope"] for t in tasks)
    only = None if whole else {h for t in tasks for h in t["scope"]}
    # a whole-scene task sees every clip by its head, reason and camera, no IR (run 5: the options author was cut off
    # by the turn's budget reading the whole scene); a scoped task sees its clips in full
    scene = work.render(only=set(), brief=True) if whole else work.render(only=only)
    lines = ["CONVERSATION (recent):\n" + ("\n".join(th.history[-4:]) or "(none)"), "", scene, ""]
    if th.memory:
        lines.append("STANDING RULES FROM THE PERSON:\n" + "\n".join(f"- {r}" for r in th.memory) + "\n")
    lines.append("ALREADY DONE THIS TURN:\n" + ("\n".join(f"- {d}" for d in done) or "- nothing yet"))
    lines.append("\nTASKS THIS TURN:")
    for i, t in enumerate(tasks, start=1):
        on = ", ".join(work.code(h) for h in t["scope"]) or "any shot"
        lines.append(f"{i}. {t['instruction']}\n   YOU MAY CHANGE: {', '.join(t['writes'])}\n   ON: {on}")
    if variants:
        lines.append(f"\nGive {variants} VARIANTS (each a short label and its own operations, at most 6 operations "
                     "with short values); leave `ops` empty.")
    if faults:
        lines.append("\nAFTER THE EDIT THE CHECKS FOUND (fix exactly these; change nothing else):\n"
                     + "\n".join(f"- {f}" for f in faults))
    return "\n".join(lines)


def _kind(op: Row) -> str:
    name = op.get("op")
    if name == "set":
        return KIND_OF.get(str(op.get("field")), "picture")
    return {"retime": "timing", "sound": "sound"}.get(str(name), "order")


def board(ops: list[Row], tasks: list[Row], work: Coverage) -> tuple[list[Row], list[str]]:
    kept, refused = [], []
    for o in ops:
        c = work.at(o.get("shot")) if o.get("shot") is not None else None
        k = _kind(o)
        ok = any(k in t["writes"] and (not t["scope"] or c is None or c.h in t["scope"]) for t in tasks)
        if ok:
            kept.append(o)
        else:
            where = f" on {o.get('shot')}" if o.get("shot") else ""
            refused.append(f"the team's {o.get('op')} {o.get('field') or ''}{where}: outside this turn's task ({k})")
    return kept, refused


def _author(th: Thread, work: Coverage, tasks: list[Row], done: list[str], backend: Any, slot: str,
            variants: int = 0, faults: list[str] | None = None, budget: float | None = None) -> Row:
    text, _ = backend.ask("author", slot, agents.prompt("author"),
                          _author_user(th, work, tasks, done, variants, faults or []), agents.author_schema(),
                          budget=budget)
    ans = json.loads(text)
    ans["ops"] = [agents.clean_op(o) for o in ans.get("ops") or []]
    for v in ans.get("variants") or []:
        v["ops"] = [agents.clean_op(o) for o in v.get("ops") or []]
    return ans


def _work(th: Thread, answer: Row, backend: Any, slot: str, rec: Row) -> None:
    before = th.cov
    work = before.copy()
    k = Kernel(work)
    r0 = k.apply(answer["ops"], by="conductor")
    rec["refused"] += [f"{x['op'].get('op')} {x['op'].get('shot') or ''}: {x['reason']}" for x in r0.rejected]
    rec["kernel_notes"] += r0.notes
    applied = list(r0.applied)
    tasks = _tasks(answer, work, before)
    rec["tasks"] = [{**t, "scope": [work.code(h) for h in t["scope"]]} for t in tasks]
    ans, variants = None, 0
    if tasks:
        variants = max(2, int(answer.get("variants") or 2)) if rec["lane"] == "options" else 0
        # the reply needs its share of the turn: the author may spend what is left after it (run 4)
        try:
            ans = _author(th, work, tasks, changes(before, work), backend, f"{slot}.author", variants,
                          budget=left(backend, rec) - REPLY_RESERVE)
        except (agents.OverBudget, agents.CutOff) as exc:
            rec["team_refused"].append(f"the team's craft work did not fit this turn's budget ({exc})")
            rec["over_budget"] = True
    if ans is not None:
        rec["author"].append(ans)
        if ans.get("notes"):
            rec["notes"].append(ans["notes"])
        if variants:
            _proposals(th, before, work, tasks, ans, rec)
            return
        kept, refused = board(ans["ops"], tasks, work)
        rec["team_refused"] += refused
        r1 = k.apply(kept, by="author")
        applied += r1.applied
        rec["kernel_notes"] += r1.notes
        rec["team_refused"] += [f"the team's {x['op'].get('op')} {x['op'].get('shot') or ''}: {x['reason']}"
                                for x in r1.rejected]
        for t in tasks:  # delivery: a task about named shots that changed none of them was not done
            if t["scope"] and not t.get("code"):
                touched = {h for h in t["scope"] if work.clip(h) is None or
                           any(line.startswith(work.code(h)) for line in changes(before, work))}
                if not touched:
                    rec["undelivered"].append(t["instruction"])
    found = checks.new(before, work)
    fix = checks.repairable(found)
    if fix:
        snap = work.copy()
        allowed = sorted({w for t in tasks for w in t["writes"]} | {"picture", "camera", "timing", "light", "sound"})
        rep_task = [{"writes": allowed, "scope": [], "instruction": "repair what the checks found"}]
        try:  # a repair is sent only when the turn can still afford it with the reply (run 4)
            ans = _author(th, work, rep_task, changes(before, work), backend, f"{slot}.repair", 0,
                          [f.sentence for f in fix], budget=left(backend, rec) - REPLY_RESERVE)
        except (agents.OverBudget, agents.CutOff) as exc:
            ans = None
            rec["repair"] = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in fix],
                             "skipped": f"the turn's budget ({exc})"}
        if ans is not None:
            rec["author"].append(ans)
            rk = Kernel(work)
            r2 = rk.apply(ans["ops"], by="repair")
            again = checks.repairable(checks.new(before, work))
            if len(again) < len(fix):
                applied += r2.applied
                rec["repair"] = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in again]}
            else:
                work.__dict__.update(snap.__dict__)
                rec["repair"] = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in fix],
                                 "dropped": True}
        found = checks.new(before, work)
    unfixed = checks.repairable(found)
    rec["reported"] = [f.sentence for f in found if f.fix == "report"]
    done = changes(before, work)
    why = risk.reasons(applied, before, work, unfixed)
    rec["applied"] = [{"by": a["by"], "text": a["text"]} for a in applied]
    if why and done:
        th.card = Card(ops=[{"op": a["op"], "by": a["by"]} for a in applied], made_on=before.fingerprint(),
                       reasons=why, lines=risk.consequences(before, work, done, rec["kernel_notes"], unfixed))
        rec["card"] = {"reasons": why, "lines": th.card.lines}
        rec["would"] = done
        return
    rec["done"] = done
    if done:
        _save(th, work)
        rec["saved"] = True


def _proposals(th: Thread, before: Coverage, work: Coverage, tasks: list[Row], ans: Row, rec: Row) -> None:
    th.proposals, th.proposals_on = [], before.fingerprint()
    for v in ans.get("variants") or []:
        trial = work.copy()
        kept, refused = board(v["ops"], tasks, trial)
        r = Kernel(trial).apply(kept, by="author")
        new = checks.repairable(checks.new(before, trial))
        lines = changes(before, trial)
        entry = {"label": v.get("label", "An option"), "ops": [a["op"] for a in r.applied], "lines": lines,
                 "refused": refused + [x["reason"] for x in r.rejected], "problems": [f.sentence for f in new],
                 "risky": risk.reasons(r.applied, before, trial, new)}
        if not lines:
            entry["dropped"] = "changes nothing"
        elif new:
            entry["dropped"] = "fails the checks"
        rec["proposals"].append(entry)
        if "dropped" not in entry:
            th.proposals.append(entry)


CHANGE = re.compile(r"^(S\d+) · (.+?): (.*) → (.*)$")
REWRITTEN = re.compile(r"^(S\d+) · (.+) rewritten$")


def plain(line: str) -> str:
    """A ledger line as a sentence a person would say ("S01's size went from MS to WIDE")."""
    m = CHANGE.match(line)
    if m:
        shot, what, a, b = m.groups()
        return f"{shot}'s {what} went from {a} to {b}" if a != "-" else f"{shot}'s {what} is now {b}"
    m = REWRITTEN.match(line)
    if m:
        return f"{m.group(1)}'s {m.group(2).replace('_', ' ')} were rewritten"
    return line


def _facts(th: Thread, rec: Row) -> list[str]:
    out = []
    if rec["fact"]:
        out.append(rec["fact"])
    if rec["lane"] == "chat":
        return [*out, "THEY ASKED A QUESTION and nothing was changed. Answer it from the scene (the clips' why, what "
                      "we see, camera, sound), as the director who made these choices."]
    nl = "\n"
    if rec.get("card"):
        out.append("WAITING FOR THEIR OK: a card with Accept and Reject is under your message; nothing is saved yet. "
                   "It is asked because it " + "; ".join(rec["card"]["reasons"]) + ". If they accept:\n"
                   + nl.join(f"- {plain(x)}" for x in rec.get("would", [])))
    elif rec["done"]:
        out.append("WHAT CHANGED (the app also shows this list under your message):\n"
                   + nl.join(f"- {plain(x)}" for x in rec["done"]))
    elif not th.proposals or rec["lane"] != "options":
        out.append("NOTHING CHANGED this turn.")
    if rec["refused"] or rec["team_refused"]:
        out.append("COULD NOT BE DONE (say so honestly, with the reason):\n"
                   + nl.join(f"- {x}" for x in rec["refused"] + rec["team_refused"]))
    if rec["undelivered"]:
        out.append("ASKED FOR BUT NOT DONE:\n" + nl.join(f"- {x}" for x in rec["undelivered"]))
    if rec["reported"]:
        out.append("HEADS-UP (reported, never trimmed):\n" + nl.join(f"- {x}" for x in rec["reported"]))
    if rec["lane"] == "options" and not th.proposals:  # run 5: the reply described options that did not exist
        why = "the team's work did not fit this turn" if rec.get("over_budget") else "none of them passed the checks"
        out.append(f"NO OPTIONS ARE SHOWN ({why}). Say so plainly in one sentence and offer to try again on fewer "
                   "shots (for example only the last moment). Do not describe any option.")
    elif rec["lane"] == "options":
        rows = [f"- {p['label']}" + (" (needs their OK: " + "; ".join(p["risky"]) + ")" if p["risky"] else "")
                for p in th.proposals]
        out.append("OPTIONS shown as cards under your message, each with \u201cUse this\u201d:\n" + nl.join(rows))
    if rec["notes"] and not rec["team_refused"] and not rec["undelivered"]:  # a note about refused work misleads
        out.append("WHY THE TEAM DID IT (their own words; use only where WHAT CHANGED backs it):\n"
                   + nl.join(f"- {n}" for n in rec["notes"]))
    return out


PERSONA = ("You are Zora, the director's creative partner: a seasoned Sri Lankan TV drama director who loves this "
           "scene and talks to the team like a colleague on set.")


REPLY_RESERVE = 0.003  # what the author and a repair leave in the turn for the reply (gpt-5-mini: about $0.002)


def _reply(th: Thread, message: str, backend: Any, slot: str, rec: Row) -> None:
    """The reply, by tier (run 4): a turn the author worked on is BIG (gpt-6.1-terra), every other turn is SMALL
    (gpt-5-nano). Its scene is only the clips the turn touched and the shots the message names; the rest one line each."""
    shown: set[str] = set()
    for line in rec.get("would", []) + rec["done"]:
        mm = re.match(r"(?:new |restored )?S(\d+)", line)
        if mm and (c := th.cov.at(mm.group(1))):
            shown.add(c.h)
    for n in re.findall(r"\bS(\d+)\b", message, re.I):
        if c := th.cov.at(n):
            shown.add(c.h)
    big = bool(rec["author"])
    talk = "\n".join(th.history[-(12 if big else 6):]) or "(none)"
    said = message if not message.startswith("[") else f"(they pressed {message.strip('[]')})"
    user = (f"<persona>{PERSONA}</persona>\n<recent_chat>\n{talk}\n</recent_chat>\n<scene>\n"
            f"{th.cov.render(only=shown)}\n</scene>\n<message>\n{said}\n</message>\n<turn>\nWHAT HAPPENED "
            "THIS TURN (the truth; it outranks the conversation):\n" + "\n\n".join(_facts(th, rec)) + "\n</turn>")
    has_card = bool(rec.get("card"))
    has_options = bool(th.proposals) and rec["lane"] == "options"
    tier = "reply_big" if big else "reply_small"
    rec["reply_models"] = [backend.models[tier][0]]
    try:
        text, _ = backend.ask(tier, f"{slot}.{tier}", agents.prompt("reply"), user, None, budget=left(backend, rec))
        rec["reply"], rec["guard_cut"] = guard(text.strip(), card=has_card, proposals=has_options)
    except (agents.OverBudget, agents.CutOff) as exc:
        rec["reply"], rec["guard_cut"] = plain_reply(rec), [f"the model reply did not fit the turn ({exc})"]
    role = f"{tier}_b"
    if agents.COMPARE_REPLIES and role in backend.models:  # a second voice, only to compare: not counted
        rec["reply_models"].append(backend.models[role][0])
        try:
            text, _ = backend.ask(role, f"{slot}.{role}", agents.prompt("reply"), user, None)
            rec["reply_b"], rec["guard_cut_b"] = guard(text.strip(), card=has_card, proposals=has_options)
        except (agents.OverBudget, agents.CutOff) as exc:
            rec["reply_b"], rec["guard_cut_b"] = "", [str(exc)]


def plain_reply(rec: Row) -> str:
    """The reply in code, when no model reply fits the turn: what changed, in one sentence."""
    if rec.get("card"):
        return "This one needs your OK first: " + "; ".join(rec["card"]["reasons"]) + "."
    if rec["done"]:
        return "Done: " + "; ".join(plain(x) for x in rec["done"][:3]) + "."
    return "Nothing changed this time."


# run 3: "the script card" is a route, not a card under the message, so only Zora's own cards and buttons count
CARD_WORDS = re.compile(r"\b(accept|reject|use this)\b|(?<!script )\b(the|a|on the) cards?\b", re.I)


LEAK = re.compile(r"(?i:what happened this turn)|WHAT CHANGED \(|WAITING FOR THEIR OK:|NOTHING CHANGED this turn|"
                  r"COULD NOT BE DONE|ASKED FOR BUT NOT DONE:|HEADS-UP \(|WHY THE TEAM DID IT|NOT POSSIBLE HERE:|"
                  r"THE PERSON (PRESSED|ASKED TO|PICKED)|THEY ASKED A QUESTION|OPTIONS shown as cards")  # run 4: the header in any case


def guard(text: str, *, card: bool, proposals: bool) -> tuple[str, list[str]]:
    """Code takes out what cannot stand: the fact sheet pasted back (run 2), a card or a button that is not there."""
    cut: list[str] = []
    m = LEAK.search(text)
    if m and m.start() > 0:
        cut.append(text[m.start():])
        text = text[: m.start()].strip()
    if card or proposals:
        return text, cut
    kept = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        (cut if CARD_WORDS.search(s) else kept).append(s)
    return " ".join(kept).strip() or text, cut


def clip_summary(c: Clip, cov: Coverage) -> str:
    return cov.clip_head(c)
