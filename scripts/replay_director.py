"""Director-chat replay harness (PLAN.md §6.1 "Prompt hygiene + replay + tuner", §12).

Replays the cases in tests/eval/director_replay.json through the REAL turn
(`director_chat.engine.turn`) against an in-memory copy of a fixture scene, and scores what the
turn did: the lane it took, the operations it applied, whether it stored a production rule.
Nothing is written to a database.

    python scripts/replay_director.py              # rules mode (no model): the `rules` cases
    python scripts/replay_director.py --model -v   # every case through OpenAI (needs a key)
    python scripts/replay_director.py --model --only tenser
    python scripts/replay_director.py --model --k 4    # each case 4 times: pass@1 and pass^4 (all four pass)

Rules mode is also run by pytest (tests/services/director_chat/test_replay.py). Model mode
compares each split's pass rate with tests/eval/director_thresholds.json and fails below it. With
`--k N` each case runs N times in model mode: `pass@1` is the first run's pass rate, `pass^N` the share of
cases that passed EVERY run (a reply that is right three times in four is not reliable), checked against
`model_pass<N>`. Every run also reports an honesty score: the share of replies whose claims all have receipts.
Tune prompts against `tune` cases; read `heldout` as the honest number. Do not edit cases to
make a change pass.

A case is one message (`message`, `expect`) or a conversation (`turns`). A turn is
`{"person": text, "model": {...}, "expect": {...}}` or `{"choose": {"block", "option"}}` (the person
clicks an option on the latest card; skipped when there is no open card). `model` holds the recorded
answers of the real model for that turn, by schema name (`turn_plan`, `chat_options`, ...) and
`reply`; in rules mode they stand in for OpenAI, in model mode they are ignored. Each turn is
stored like the API stores it, so the next turn reads the thread.

A case may carry `role` ({"can_edit": bool, "can_edit_script": bool}); the default is a director who can edit
everything. In a recorded translator answer (`dialogue_translation`) a `line_id` of "#2" means the scene's third line.

Expectations beyond lane / ops / card: `no_unbacked_promise` (the reply offers nothing it cannot
do), `claims_match_state` (a reply that says something was changed is true of the saved scene),
`end_state` (`{"dialogue_script": "si"}`: the saved lines are Sinhala, OR the turn's outcome is a
plain "cannot" or a staged card), `outcome`, `reply_has`, `reply_lacks`, `card_label_true`. These
oracles are written here, apart from the guards in the engine, so a guard cannot mark its own work.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from _common import ROOT, load_env

sys.path.insert(0, str(ROOT / "src" / "services" / "director_chat"))

from director_chat.engine import choice, proposals, refusals, turn

from contracts import sceneplan
from contracts.director import ChoicePayload, TurnPayload
from contracts.screenplay import parse_document
from contracts.shotplan import ProposedShot, fit

CASES = ROOT / "tests" / "eval" / "director_replay.json"
THRESHOLDS = ROOT / "tests" / "eval" / "director_thresholds.json"
SCRIPT = ROOT / "tests" / "fixtures" / "corpus" / "harbour-lights-ep01-script.fountain"
PRODUCTION = uuid.UUID("e0000000-0000-4000-8000-00000000d1c7")
NS = uuid.UUID("0b8f3c52-7d0e-4c1a-9a55-3f2a9d1e7c11")


def fixture_scene(n: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Scene `n` of the fixture script, one shot per block, fitted by the kernel. Ids are
    derived from the scene number, so a run is reproducible."""
    parsed = parse_document(SCRIPT.read_text(encoding="utf-8")).scenes[n]
    scene_id = str(uuid.uuid5(NS, f"scene-{n}"))
    blocks: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for b in parsed.blocks:
        if b.kind == "dialogue":
            lid = str(uuid.uuid5(NS, f"scene-{n}-line-{len(lines)}"))
            lines.append({"id": lid, "production_id": str(PRODUCTION), "scene_id": scene_id, "ord": len(lines),
                          "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                          "character_id": str(uuid.uuid5(NS, b.speaker.title()))})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PRODUCTION), "episode_id": str(uuid.uuid5(NS, "ep-1")),
             "number": n + 1, "heading": parsed.heading.raw, "envelope_s": 60, "status": "split", "script": blocks,
             "location_id": None}
    items = sceneplan.items_for(blocks, lines)
    proposal = [ProposedShot(i, i + 1, "MS") for i in range(len(items))]
    ids = iter(str(uuid.uuid5(NS, f"scene-{n}-shot-{i}")) for i in range(len(items) * 2))
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal],
                                                   fit(items, proposal, envelope_s=60), lines,
                                                   new_id=lambda: next(ids))
    return scene, line_rows, shots


@dataclass
class ReplayStore:
    """director_chat's Store over one in-memory scene; records what the turn writes."""

    scene_row: dict[str, Any]
    line_rows: list[dict[str, Any]]
    shot_rows: list[dict[str, Any]]
    saved: int = 0
    message_rows: list[dict[str, Any]] = field(default_factory=list)
    memory_rows: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)  # the thread before this message
    pending_rows: list[dict[str, Any]] = field(default_factory=list)
    thread_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def production(self, production_id: Any) -> dict[str, Any]:
        return {"id": str(production_id), "title": "Harbour Lights", "orientation": "horizontal", "settings": {},
                "summary": "A fishing family on the south coast; the elder son returns to sell the boat."}

    def scene(self, production_id: Any, scene_id: Any) -> dict[str, Any] | None:
        return self.scene_row if str(scene_id) == self.scene_row["id"] else None

    def lines(self, scene_id: Any) -> list[dict[str, Any]]:
        return self.line_rows

    def shots(self, scene_id: Any) -> list[dict[str, Any]]:
        return self.shot_rows

    def canon(self, production_id: Any) -> list[dict[str, Any]]:
        return [{"id": str(uuid.uuid5(NS, n)), "kind": "character", "code": c, "name": n, "aliases": [],
                 "locked": False, "current": None} for c, n in (("C01", "Kamala"), ("C02", "Nimal"), ("C03", "Sunil"))]

    def board(self, production_id: Any) -> list[dict[str, Any]]:
        return []

    def default_persona(self) -> dict[str, Any]:
        return {"id": None, "name": "Classic Teledrama", "style_note": "Clear coverage, readable emotion.",
                "charter": "Cover every speaker clearly: establish, then singles in shot / reverse shot."}

    def messages(self, thread_id: Any, limit: int = 12) -> list[dict[str, Any]]:
        return self.history[-limit:]

    def message(self, message_id: Any) -> dict[str, Any] | None:
        return next((m for m in self.history if str(m.get("id")) == str(message_id)), None)

    def open_pending(self, thread_id: Any) -> dict[str, Any] | None:
        return next((p for p in self.pending_rows if p["status"] == "open"), None)

    def add_pending(self, row: dict[str, Any]) -> None:
        self.pending_rows.append(dict(row))

    def close_pending(self, thread_id: Any, status: str) -> None:
        for p in self.pending_rows:
            if p["status"] == "open":
                p["status"] = status

    def set_blocks(self, message_id: Any, blocks: list[dict[str, Any]]) -> None:
        if (m := self.message(message_id)) is not None:
            m["blocks"] = blocks

    def memory(self, production_id: Any, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def open_questions(self, production_id: Any) -> list[dict[str, Any]]:
        return []

    def ready_documents(self, production_id: Any) -> list[dict[str, Any]]:
        return []

    def search(self, **kw: Any) -> list[dict[str, Any]]:
        return []

    def save_plan(self, scene_id: Any, shots: list[dict[str, Any]], removed: list[str], lines: list[dict[str, Any]],
                  scene_fields: dict[str, Any], removed_lines: list[str] | None = None) -> None:
        self.saved += 1
        keep = {s["id"] for s in shots}
        self.shot_rows = [s for s in self.shot_rows if s["id"] not in removed and s["id"] not in keep] + shots
        self.line_rows = lines
        self.scene_row = {**self.scene_row, **scene_fields}

    def add_message(self, row: dict[str, Any]) -> None:
        self.message_rows.append(row)
        self.history.append(row)  # the next turn reads it, as the API's store would return it

    def audit(self, row: dict[str, Any]) -> None:
        pass

    def add_memory(self, item: dict[str, Any], embedding: Any, model: str) -> None:
        self.memory_rows.append(item)


class NoModel:
    enabled = False

    def json(self, **kw: Any) -> dict[str, Any]:
        raise RuntimeError("no model in rules mode")

    def tool_round(self, **kw: Any) -> Any:
        raise RuntimeError("no model in rules mode")

    def stream(self, **kw: Any) -> Iterator[str]:
        raise RuntimeError("no model in rules mode")

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        raise RuntimeError("no model in rules mode")


class RecordedModel:
    """What the real model answered on one turn of a stored thread, played back: strict-JSON calls by
    schema name, and the reply text. A call nothing was recorded for fails, as a failed call would."""

    enabled = True

    def __init__(self, answers: dict[str, Any], store: ReplayStore | None = None) -> None:
        self.answers = answers
        self.store = store
        self.reply = str(answers.get("reply", ""))

    def json(self, *, schema_name: str, **kw: Any) -> dict[str, Any]:
        if schema_name not in self.answers:
            raise RuntimeError(f"no recorded answer for {schema_name}")
        answer = dict(self.answers[schema_name])
        if schema_name == "dialogue_translation" and self.store is not None:
            ids = [str(ln["id"]) for ln in self.store.line_rows]

            def resolved(row: dict[str, Any]) -> dict[str, Any]:
                at = str(row["line_id"])
                return {**row, "line_id": ids[int(at[1:])]} if at.startswith("#") else row

            answer["lines"] = [resolved(row) for row in answer.get("lines", [])]
        return answer

    def tool_round(self, **kw: Any) -> Any:
        return SimpleNamespace(content=self.reply, tool_calls=None)

    def stream(self, **kw: Any) -> Iterator[str]:
        yield self.reply

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]


# ── oracles: written here, not imported from the engine, so a guard cannot mark its own work ──

PROMISE = re.compile(
    r"\bconfirm\b[^.!?\n]{0,40}\b(?:and|then)\b[^.!?\n]{0,15}\b(?:we|i)\b|\bsay the word\b|\bready to apply\b"
    r"|\b(?:i|we)(?:'ll|\s+will)\s+(?:apply|switch|translate|change|make|do)\b|\bwhen you(?:'re| are) ready\b"
    r"|\bjust (?:say|confirm|tell me)\b", re.I)
CLAIM = re.compile(
    r"\balready (?:applied|done|made|changed|switched)\b"
    r"|\b(?:has|have|had) been (?:applied|changed|switched|done|made)\b"
    r"|\bnow (?:play|read|run)s? in sinhala\b|\bis now (?:in )?sinhala\b"
    r"|\bi(?:'ve| have) (?:applied|changed|switched|made|updated)\b|^\s*done\b|\ball done\b", re.I)
NEGATED = re.compile(r"\b(?:no|not|nothing|never|none)\b|n't\b", re.I)  # "nothing has been applied" is no claim
ABOUT_DIALOGUE = re.compile(r"sinhala|dialogue|\blines?\b", re.I)
SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def script_of(text: str) -> str:
    """"si" when at least 80% of a line's letters are Sinhala (U+0D80-U+0DFF), "en" when most are Latin."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "none"
    sinhala = sum("඀" <= c <= "෿" for c in letters)
    latin = sum(c.isascii() for c in letters)
    return "si" if sinhala / len(letters) >= 0.8 else "en" if latin / len(letters) >= 0.8 else "mixed"


def dialogue_is(store: ReplayStore, script: str) -> bool:
    return bool(store.line_rows) and all(script_of(str(ln.get("text", ""))) == script for ln in store.line_rows)


def chosen_effects(store: ReplayStore) -> list[str]:
    return [str(b.get("outcome", "")) for m in store.message_rows for b in m.get("blocks", [])
            if b.get("kind") == "options" and b.get("chosen") is not None and b.get("outcome")]


def outcome_of(done: dict[str, Any], message: dict[str, Any]) -> str:
    """What the turn came to: cannot (it said so, with the route), card, applied, or just chat."""
    blocks = message.get("blocks", [])
    if done.get("lane") == "cannot" or any(b.get("route") for b in blocks if b.get("kind") == "text"):
        return "cannot"
    if any(b["kind"] in ("options", "disagreement") for b in blocks):
        return "card"
    return "applied" if message.get("ops") else "chat"


def fixture_store(case: dict[str, Any]) -> ReplayStore:
    store = ReplayStore(*fixture_scene(int(case.get("scene", 0))))
    # `dialogue`: the scene's lines in order, in another language (the fixture script is Sinhala; the thread
    # this replays had English lines).
    for line, text in zip(store.line_rows, case.get("dialogue", []), strict=False):
        line["text"] = text
    # A case may carry the thread so far: the director's messages, as stored ({kind, text} or {kind, blocks}).
    store.history = [{"id": f"h{n}", "speaker": "Director", "blocks": [{"kind": "text", "text": m.get("text", "")}],
                      **{k: v for k, v in m.items() if k != "text"}} for n, m in enumerate(case.get("history", []))]
    return store


def run_turn(store: ReplayStore, llm: Any, message: str, role: dict[str, bool] | None = None) -> dict[str, Any]:
    """One person message through the real turn, stored as the API stores it (the person's message
    first, then the director's), so the next turn reads the thread."""
    user_id = uuid.uuid4()
    store.history.append({"id": str(user_id), "kind": "user", "speaker": "You", "text": message, "blocks": []})
    req = TurnPayload(production_id=PRODUCTION, scene_id=uuid.UUID(store.scene_row["id"]), thread_id=store.thread_id,
                      actor_user_id=uuid.uuid4(), actor_name="Replay", message=message, user_message_id=user_id,
                      **{"can_edit": True, "can_edit_script": True, **(role or {})})
    seen = len(store.message_rows)
    events = list(turn.run(req, store, llm))
    done = next((d for e, d in events if e == "done"), {})
    row = store.message_rows[-1] if len(store.message_rows) > seen else {}
    reply = next((b["text"] for b in row.get("blocks", []) if b["kind"] == "text"), "")
    return {"lane": done.get("lane", "error"), "ops": row.get("ops", []), "memory": bool(store.memory_rows),
            "saved": store.saved > 0, "reply": reply, "blocks": row.get("blocks", []),
            "card": any(b["kind"] in ("options", "disagreement") for b in row.get("blocks", [])),
            "pending": any(p["status"] == "open" for p in store.pending_rows),
            "outcome": outcome_of(done, row)}


def choose(store: ReplayStore, block: int, option: int) -> dict[str, Any]:
    """The person clicks an option on the latest card, as `POST /messages/{id}/option` does: its stored
    edit is applied and the outcome written on the card. Skipped when no card is waiting."""
    msg = next((m for m in reversed(store.message_rows) if any(
        b.get("kind") == "options" and b.get("chosen") is None for b in m.get("blocks", []))), None)
    if msg is None or block >= len(msg["blocks"]) or msg["blocks"][block].get("kind") != "options" \
            or msg["blocks"][block].get("chosen") is not None or option >= len(msg["blocks"][block]["options"]):
        return {"skipped": True}
    card = msg["blocks"][block]
    chosen = card["options"][option]
    if chosen.get("ops"):
        extra = {"intent": chosen["intent"]} if chosen.get("intent") and "intent" in ChoicePayload.model_fields else {}
        result = choice.apply_choice(ChoicePayload(production_id=PRODUCTION, scene_id=uuid.UUID(store.scene_row["id"]),
                                                   actor_user_id=uuid.uuid4(), can_edit_script=True,
                                                   ops=chosen["ops"], **extra), store)
        if not result.applied:
            return {"skipped": True, "summary": result.summary}
        outcome = result.summary
    else:
        outcome = "Asked the board." if chosen.get("prompt") else "Kept as it is."
    card["chosen"], card["outcome"] = option, outcome
    for row in store.pending_rows:
        if row.get("message_id") == msg["id"] and row["status"] == "open":
            row["status"] = "closed"
    return {"skipped": False, "summary": outcome}


def unbacked_claims(got: dict[str, Any], store: ReplayStore) -> list[str]:
    """The sentences of a reply that say a change was made which neither this turn's receipts, a chosen card's
    recorded effect nor the saved lines show."""
    out = []
    for s in SENTENCES.split(got["reply"]):
        if not CLAIM.search(s) or NEGATED.search(s):
            continue
        if ABOUT_DIALOGUE.search(s):
            if not dialogue_is(store, "si") and not got["ops"]:
                out.append(f"claims a dialogue change the saved lines do not show: {s.strip()[:90]!r}")
        elif not got["ops"] and not chosen_effects(store):
            out.append(f"claims a change with no receipt: {s.strip()[:90]!r}")
    return out


def failures(case: dict[str, Any], got: dict[str, Any], store: ReplayStore | None = None) -> list[str]:
    exp = case["expect"]
    out = []
    lanes = exp["lane"] if isinstance(exp.get("lane"), list) else [exp.get("lane")]
    if exp.get("lane") is not None and got["lane"] not in lanes:
        out.append(f"lane {got['lane']} (want {'/'.join(lanes)})")
    for want in exp.get("ops", []):
        if not any(all(op.get(k) == v for k, v in want.items()) for op in got["ops"]):
            out.append(f"missing op {want}")
    if exp.get("no_ops") and got["ops"]:
        out.append(f"changed the plan: {got['ops']}")
    if exp.get("memory") and not got["memory"]:
        out.append("stored no production rule")
    if "card" in exp and exp["card"] != got["card"]:
        out.append("offered no card" if exp["card"] else "offered a card")
    if exp.get("clean_reply"):
        if refusals.INTERNAL.search(got["reply"]):
            out.append(f"reply has internal wording: {got['reply'][:80]!r}")
        if not got["card"] and proposals.guard_reply(got["reply"], has_card=False) != got["reply"]:
            out.append("reply points at a card the message does not carry")
    if "outcome" in exp and got.get("outcome") != exp["outcome"]:
        out.append(f"outcome {got.get('outcome')} (want {exp['outcome']})")
    for needle in exp.get("reply_has", []):
        if needle.lower() not in got["reply"].lower():
            out.append(f"reply lacks {needle!r}: {got['reply'][:100]!r}")
    for needle in exp.get("reply_lacks", []):
        if needle.lower() in got["reply"].lower():
            out.append(f"reply has {needle!r}: {got['reply'][:100]!r}")
    if exp.get("no_unbacked_promise") and not got["card"] and not got.get("pending"):
        for s in SENTENCES.split(got["reply"]):
            if PROMISE.search(s):
                out.append(f"unbacked promise (no card, nothing pending): {s.strip()[:90]!r}")
    if exp.get("claims_match_state") and store is not None:
        out += unbacked_claims(got, store)
    if exp.get("card_label_true"):
        for b in got["blocks"]:
            for o in b.get("options", []) if b.get("kind") == "options" else []:
                if re.search(r"sinhala|translat", str(o.get("label", "")), re.I) and not any(
                        op.get("op") == "block.set" and op.get("field") == "text" for op in o.get("ops", [])):
                    out.append(f"card says {o['label']!r} but its edit does not change the words")
    if (want := exp.get("end_state")) and store is not None:
        if "dialogue_script" in want and not dialogue_is(store, want["dialogue_script"]) \
                and got.get("outcome") not in ("cannot", "card"):
            out.append(f"end state: dialogue is not {want['dialogue_script']} and the turn neither said it cannot "
                       f"nor staged a card (outcome {got.get('outcome')})")
    return out


def case_turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case.get("turns") or [{"person": case["message"], "expect": case["expect"]}]


def run_case(case: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """→ the last turn's result, plus `failures` for the whole conversation and the honesty tally (`replies`,
    `unbacked`). With no `llm`, a turn that carries recorded `model` answers plays them back; one without runs
    with no model."""
    store = fixture_store(case)
    got: dict[str, Any] = {}
    fails: list[str] = []
    replies = unbacked = 0
    for n, t in enumerate(case_turns(case), start=1):
        if "choose" in t:
            got = {**choose(store, int(t["choose"].get("block", 1)), int(t["choose"].get("option", 0))),
                   "lane": "choose", "ops": [], "reply": "", "blocks": [], "card": False, "memory": False,
                   "saved": store.saved > 0, "outcome": "chat"}
            continue
        model = llm if llm is not None else (RecordedModel(t["model"], store) if t.get("model") else NoModel())
        got = run_turn(store, model, t["person"], case.get("role"))
        fails += [f"turn {n}: {f}" if "turns" in case else f
                  for f in failures({"expect": t.get("expect", {})}, got, store)]
        if got["reply"]:
            replies += 1
            unbacked += bool(unbacked_claims(got, store))
    return {**got, "failures": fails, "replies": replies, "unbacked": unbacked}


def replay(mode: str, only: str | None = None, verbose: bool = False, llm: Any = None, k: int = 1) -> dict[str, Any]:
    """Every case once (rules mode), or `k` times in model mode. `ok` is the first run; `pass_all` is every run."""
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    cases = [c for c in cases if (mode == "model" or c.get("rules")) and (only is None or c["id"] == only)]
    runs = k if mode == "model" else 1
    results = []
    replies = unbacked = 0
    for case in cases:
        tries = [run_case(case, llm) for _ in range(runs)]
        fails = tries[0]["failures"]
        got = {k: v for k, v in tries[0].items() if k != "failures"}
        replies += sum(t["replies"] for t in tries)
        unbacked += sum(t["unbacked"] for t in tries)
        results.append({"id": case["id"], "split": case["split"], "ok": not fails, "failures": fails,
                        "pass_all": all(not t["failures"] for t in tries), "runs": runs, **got})
        if verbose or fails:
            mark = "ok  " if not fails else "FAIL"
            print(f"{mark} {case['split']:<7} {case['id']:<24} lane={got['lane']:<7} ops={len(got['ops'])}"
                  + (f"  {'; '.join(fails)}" if fails else "")
                  + (f"  [{sum(not t['failures'] for t in tries)}/{runs} runs]" if runs > 1 else ""))
            if verbose and got["reply"]:
                print(f"       reply: {got['reply'][:160]}")
    by_split: dict[str, float] = {}
    by_split_all: dict[str, float] = {}
    for split in ("tune", "heldout"):
        rows = [r for r in results if r["split"] == split]
        if rows:
            by_split[split] = round(sum(r["ok"] for r in rows) / len(rows), 3)
            by_split_all[split] = round(sum(r["pass_all"] for r in rows) / len(rows), 3)
    honesty = round(1 - unbacked / replies, 3) if replies else 1.0
    return {"mode": mode, "cases": results, "pass_rate": by_split, "pass_all": by_split_all, "runs": runs,
            "honesty": honesty}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="store_true", help="run every case through OpenAI (needs a key)")
    parser.add_argument("--only", help="one case id")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--k", type=int, default=1, help="model mode: run each case K times (pass@1 and pass^K)")
    args = parser.parse_args()
    llm = None
    if args.model:
        load_env()
        from director_chat.runtime.config import get_config
        from director_chat.runtime.llm import LLM

        config = get_config()
        if not config.llm_enabled:
            sys.exit("OPENAI__API_KEY is not set (.env or environment).")
        usage = {"input": 0, "cached": 0, "output": 0}

        def on_usage(row: dict[str, Any]) -> None:
            usage["input"] += row["input_tokens"]
            usage["cached"] += row["cached_input_tokens"]
            usage["output"] += row["output_tokens"]

        llm = LLM(config, on_usage)
    report = replay("model" if args.model else "rules", args.only, args.verbose, llm, args.k)
    print(f"\n{report['mode']} mode: pass@1 " + ", ".join(f"{k} {v:.0%}" for k, v in report["pass_rate"].items()))
    if report["runs"] > 1:
        print(f"pass^{report['runs']}: " + ", ".join(f"{k} {v:.0%}" for k, v in report["pass_all"].items()))
    print(f"honesty: {report['honesty']:.1%} of replies claim only what a receipt shows")
    if args.model:
        print(f"tokens: {usage['input']} in ({usage['cached']} cached), {usage['output']} out")
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    floor = thresholds.get(report["mode"], {})
    low = {k: v for k, v in report["pass_rate"].items() if args.only is None and v < floor.get(k, 0)}
    if report["runs"] > 1:
        every = thresholds.get(f"model_pass{report['runs']}", {})
        low |= {f"pass^{report['runs']} {k}": v for k, v in report["pass_all"].items()
                if args.only is None and v < every.get(k, 0)}
    if args.only is None and report["honesty"] < thresholds.get("honesty", 0):
        low["honesty"] = report["honesty"]
    if low:
        sys.exit(f"below tests/eval/director_thresholds.json: {low}")


if __name__ == "__main__":
    main()
