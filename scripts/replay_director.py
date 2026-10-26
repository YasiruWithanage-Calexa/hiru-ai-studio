"""Director-chat replay harness (PLAN.md §6.1 "Prompt hygiene + replay + tuner", §12).

Replays the cases in tests/eval/director_replay.json through the REAL turn
(`director_chat.engine.turn`) against an in-memory copy of a fixture scene, and scores what the
turn did: the lane it took, the operations it applied, whether it stored a production rule.
Nothing is written to a database.

    python scripts/replay_director.py              # rules mode (no model): the `rules` cases
    python scripts/replay_director.py --model -v   # every case through OpenAI (needs a key)
    python scripts/replay_director.py --model --only tenser

Rules mode is also run by pytest (tests/services/director_chat/test_replay.py). Model mode
compares each split's pass rate with tests/eval/director_thresholds.json and fails below it.
Tune prompts against `tune` cases; read `heldout` as the honest number. Do not edit cases to
make a change pass.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from _common import ROOT, load_env

sys.path.insert(0, str(ROOT / "src" / "services" / "director_chat"))

from director_chat.engine import proposals, refusals, turn

from contracts import sceneplan
from contracts.director import TurnPayload
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

    def memory(self, production_id: Any, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def open_questions(self, production_id: Any) -> list[dict[str, Any]]:
        return []

    def ready_documents(self, production_id: Any) -> list[dict[str, Any]]:
        return []

    def search(self, **kw: Any) -> list[dict[str, Any]]:
        return []

    def save_plan(self, *a: Any, **kw: Any) -> None:
        self.saved += 1

    def add_message(self, row: dict[str, Any]) -> None:
        self.message_rows.append(row)

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


def run_case(case: dict[str, Any], llm: Any) -> dict[str, Any]:
    store = ReplayStore(*fixture_scene(int(case.get("scene", 0))))
    # A case may carry the thread so far: the director's messages, as stored ({kind, text} or {kind, blocks}).
    store.history = [{"id": f"h{n}", "speaker": "Director", "blocks": [{"kind": "text", "text": m.get("text", "")}],
                      **{k: v for k, v in m.items() if k != "text"}} for n, m in enumerate(case.get("history", []))]
    req = TurnPayload(production_id=PRODUCTION, scene_id=uuid.UUID(store.scene_row["id"]), thread_id=uuid.uuid4(),
                      actor_user_id=uuid.uuid4(), actor_name="Replay", can_edit=True, can_edit_script=True,
                      message=case["message"],
                      user_message_id=uuid.uuid4())
    events = list(turn.run(req, store, llm))
    done = next((d for e, d in events if e == "done"), {})
    message = store.message_rows[-1] if store.message_rows else {}
    reply = next((b["text"] for b in message.get("blocks", []) if b["kind"] == "text"), "")
    return {"lane": done.get("lane", "error"), "ops": message.get("ops", []), "memory": bool(store.memory_rows),
            "saved": store.saved > 0, "reply": reply,
            "card": any(b["kind"] in ("options", "disagreement") for b in message.get("blocks", []))}


def failures(case: dict[str, Any], got: dict[str, Any]) -> list[str]:
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
    return out


def replay(mode: str, only: str | None = None, verbose: bool = False, llm: Any = None) -> dict[str, Any]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    cases = [c for c in cases if (mode == "model" or c.get("rules")) and (only is None or c["id"] == only)]
    llm = llm or NoModel()
    results = []
    for case in cases:
        got = run_case(case, llm)
        fails = failures(case, got)
        results.append({"id": case["id"], "split": case["split"], "ok": not fails, "failures": fails, **got})
        if verbose or fails:
            mark = "ok  " if not fails else "FAIL"
            print(f"{mark} {case['split']:<7} {case['id']:<24} lane={got['lane']:<7} ops={len(got['ops'])}"
                  + (f"  {'; '.join(fails)}" if fails else ""))
            if verbose and got["reply"]:
                print(f"       reply: {got['reply'][:160]}")
    by_split = {}
    for split in ("tune", "heldout"):
        rows = [r for r in results if r["split"] == split]
        if rows:
            by_split[split] = round(sum(r["ok"] for r in rows) / len(rows), 3)
    return {"mode": mode, "cases": results, "pass_rate": by_split}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="store_true", help="run every case through OpenAI (needs a key)")
    parser.add_argument("--only", help="one case id")
    parser.add_argument("-v", "--verbose", action="store_true")
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
    report = replay("model" if args.model else "rules", args.only, args.verbose, llm)
    print(f"\n{report['mode']} mode: " + ", ".join(f"{k} {v:.0%}" for k, v in report["pass_rate"].items()))
    if args.model:
        print(f"tokens: {usage['input']} in ({usage['cached']} cached), {usage['output']} out")
    floor = json.loads(THRESHOLDS.read_text(encoding="utf-8")).get(report["mode"], {})
    low = {k: v for k, v in report["pass_rate"].items() if args.only is None and v < floor.get(k, 0)}
    if low:
        sys.exit(f"below tests/eval/director_thresholds.json: {low}")


if __name__ == "__main__":
    main()
