"""The Phase 2 spike of plan/2026-11-05e: can ONE call plan a scene and design its camera as well as one message to
ChatGPT?

    python scripts/david_spike.py --yes                            # configurations A and B on the gold scenes (~$5)
    python scripts/david_spike.py --yes --scene phone_call         # one scene
    python scripts/david_spike.py --yes --config A                 # one configuration
    python scripts/david_spike.py --yes --c-model gpt-5.5          # adds C with the strongest model the account can use
    python scripts/david_spike.py --yes --scene-dir real/          # real Hiru scenes (yaml as in eval/david/scenes)

It refuses to start without `--yes`: it calls the real model once to three times per scene and configuration (the
author, and a repair only where code cannot fix a fault), and that costs money. A person starts it (the plan's rule),
reads the table it writes and decides D2 (JSON directly or free text first) and D3 (which model and effort).

    A   gpt-5 at medium effort (`author` tier), JSON directly
    B   gpt-5 at medium effort writes free text, then gpt-5-mini puts it in the format (pattern rule 2's exception);
        code checks the formatted plan, so a change the small model made to a line or a block is found
    C   the strongest current OpenAI model the account can use (`--c-model`), JSON directly. Not run without it.

For each run it saves the stored plan and the model calls (`tests/eval/david/spike/<config>/<scene>.json`,
`.usage.json`), checks the plan with code (the problems of the author's FIRST answer, and what is left after any
repair), and records the
tokens, the hidden reasoning, the cost and the time. `tests/eval/david/spike/summary.md` is the table for
`IMPLEMENTED.md`.

D10: when a person has pasted ChatGPT's answer for a scene into `tests/eval/david/chatgpt/<scene>.txt`, the spike also
writes `tests/eval/david/spike/side_by_side/<scene>.md`: David's first configuration and ChatGPT's answer, both as plain
shot lists (`scripts/david_compare.py`), so the person reads them BEFORE anything else is built. Early stop (the plan's
rule 8): if David is clearly behind ChatGPT on most scenes, change the prompt or the pack and run this again; do not
add an
agent. Nothing is written to a database, and no number here is made up: an empty cell means no run finished.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import david_compare  # noqa: E402
import yaml  # noqa: E402

EVAL = ROOT / "tests" / "eval" / "david"
SPIKE = EVAL / "spike"
EXAMPLE_SCENE = "refuses_money"  # the scene the author's prompt shows: the model has seen that answer, so it is not run
CONFIGS = ("A", "B", "C")
# model prefix -> (input, cached input, output), US dollars per million tokens: OpenAI's list prices on the standard
# tier
# (plan §8). Longest prefix wins; a model not listed is priced as gpt-5.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00)}
Row = dict[str, Any]


def cost(row: Row) -> float:
    """US dollars one `token_usage` row cost. An output token includes the hidden reasoning."""
    name = str(row.get("model") or "").lower()
    pin, pcached, pout = next((PRICES[k] for k in sorted(PRICES, key=len, reverse=True) if name.startswith(k)),
                              PRICES["gpt-5"])
    prompt, cached = int(row.get("input_tokens") or 0), int(row.get("cached_input_tokens") or 0)
    return (max(prompt - cached, 0) * pin + cached * pcached + int(row.get("output_tokens") or 0) * pout) / 1_000_000


def gold_names() -> list[str]:
    return sorted(p.stem for p in (EVAL / "scenes").glob("*.yaml"))


def default_scenes() -> list[str]:
    return [n for n in gold_names() if n != EXAMPLE_SCENE]


def load_scene(name: str, scene_dir: Path | None) -> tuple[Any, str]:
    """-> (the scene as David is given it, its title)."""
    if scene_dir is None:
        from tests.david import gold

        return gold.scene(name), name.replace("_", " ").title()
    from contracts import sceneplan
    from contracts.david.scene import BlockS, PlaceS, SceneS
    from contracts.shotplan import Item

    raw = yaml.safe_load((scene_dir / f"{name}.yaml").read_text(encoding="utf-8"))
    sc = raw["scene"]
    items = sceneplan._read_unread([Item(b["index"], b["kind"], b["text"], b.get("speaker", ""), None,
                                         b.get("delivery", ""), b.get("line_id")) for b in sc["blocks"]])
    return (SceneS(blocks=[BlockS.of(i) for i in items], cast=list(sc["cast"]),
                   place=PlaceS(name=sc["place"]["name"], objects=sc["place"]["objects"]),
                   envelope_s=sc.get("envelope_s")),
            str(raw.get("title") or name))


def planner_for(config: str) -> Any:
    from hiru_ai.systems.david.david_shot_planner.scene import Planner

    if config != "B":
        return Planner

    class FreeTextPlanner(Planner):
        """B: the strong model writes free text, a small model puts it in the format. Code checks the formatted plan."""

        def author(self) -> Any:
            from langchain_core.messages import HumanMessage, SystemMessage

            from contracts.david.wire import DavidWire
            from hiru_ai.agents.david.david_author import agent as hooks
            from hiru_ai.agents.david.david_author.schema import Input, Output
            from hiru_ai.core import agents, llm
            from hiru_ai.core.usage import UsageCallback

            usage = self.ctx.usage_sink
            system = agents.build("david_author").prompt.system()
            free = UsageCallback(usage, "david.spike.free", "", None)
            self.calls["author"] += 1
            written = llm.get_llm("author", callbacks=[free]).invoke([
                SystemMessage(system + "\n\nFor this answer you may write the plan in plain text or loose JSON: "
                              "another "
                                       "writer will put it in the exact format."),
                HumanMessage(self.pack()["text"])]).content
            fmt = UsageCallback(usage, "david.spike.format", "", None)
            raw = llm.get_structured("medium", hooks.output_schema(), callbacks=[fmt]).invoke([
                SystemMessage("Put the plan you are given into the format. Change nothing, add nothing and leave "
                              "nothing out: every shot, block, line id, addition, mark and the end state exactly as "
                              "written. Where the plan lacks a field, write the empty value."),
                HumanMessage(str(written))])
            out = Output.model_validate(raw)
            return DavidWire.model_validate(hooks.finish(Input(scene=self.scene, pack=""), out).model_dump(mode="json"))

    return FreeTextPlanner


def run_one(config: str, name: str, scene_dir: Path | None) -> Row:
    """One scene through one configuration; the row the table is made from."""
    from contracts.david.stored import Link
    from hiru_ai.core.context import RunContext

    scene, title = load_scene(name, scene_dir)
    usage: list[Row] = []
    people = [{"name": n, "code": f"C{i:02d}"} for i, n in enumerate(scene.cast, start=1)]
    line_ids = {b.line_id: b.line_id for b in scene.lines if b.line_id}
    planner = planner_for(config)(RunContext(usage_sink=usage.append, usage_detail=True), scene, number=1,
                                  line_ids=line_ids, pack={"production": {"people": people},
                                                           "context": {"heading": title}},
                                  removed=[], link=Link(), start=None, before=None)
    started = time.monotonic()
    planned = planner.plan(previous={}, job_id="spike")
    seconds = time.monotonic() - started
    folder = SPIKE / config
    folder.mkdir(parents=True, exist_ok=True)
    saved = json.dumps(planned.stored.data(), ensure_ascii=False, indent=2)
    (folder / f"{name}.json").write_text(saved, encoding="utf-8")
    (folder / f"{name}.usage.json").write_text(json.dumps(usage, ensure_ascii=False, indent=1), encoding="utf-8")
    first = planned.stored.report.get("first_pass") or []
    left = planned.stored.problems
    row = {"config": config, "scene": name, "calls": len(usage), "repairs": planner.calls["repair"],
           "shots": len(planned.stored.plan.shots), "seconds": round(seconds, 1),
           "first": {fix: sum(1 for p in first if p["fix"] == fix) for fix in ("repair", "mend", "drop", "report")},
           "left": {fix: sum(1 for p in left if p.fix == fix) for fix in ("repair", "drop", "report")},
           "input": sum(int(r.get("input_tokens") or 0) for r in usage),
           "cached": sum(int(r.get("cached_input_tokens") or 0) for r in usage),
           "output": sum(int(r.get("output_tokens") or 0) for r in usage),
           "reasoning": sum(int(r.get("reasoning_tokens") or 0) for r in usage),
           "dollars": round(sum(cost(r) for r in usage), 4)}
    print(f"\n{config} {name}: {row['calls']} calls, {row['seconds']} s, ${row['dollars']}, first pass {row['first']}, "
          f"left {row['left']}", flush=True)
    return row


def median(rows: list[Row], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(values), 2) if values else None


def summary(rows: list[Row]) -> str:
    head = ("| Config | Scenes | Calls (median) | Repairs | First pass: for repair (median) | Left for repair "
            "| Reported | Reasoning tokens (median) | $ a scene (median) | Seconds (median) |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    lines = []
    for config in CONFIGS:
        mine = [r for r in rows if r["config"] == config]
        if not mine:
            continue
        first = [{"v": r["first"]["repair"]} for r in mine]
        lines.append(f"| {config} | {len(mine)} | {median(mine, 'calls')} | {sum(r['repairs'] for r in mine)} | "
                     f"{median(first, 'v')} | {sum(r['left']['repair'] for r in mine)} | "
                     f"{sum(r['left']['report'] for r in mine)} | {median(mine, 'reasoning')} | "
                     f"{median(mine, 'dollars')} | {median(mine, 'seconds')} |")
    return head + "\n" + "\n".join(lines) + "\n"


def side_by_side(names: list[str], config: str, scene_dir: Path | None) -> list[Path]:
    """D10: David's plan and the pasted ChatGPT answer, both as plain shot lists, for each scene that has both."""
    out = []
    for name in names:
        saved, pasted = SPIKE / config / f"{name}.json", david_compare.CHATGPT / f"{name}.txt"
        if not (saved.exists() and pasted.exists()):
            continue
        raw = yaml.safe_load(((scene_dir or EVAL / "scenes") / f"{name}.yaml").read_text(encoding="utf-8"))["scene"]
        david = david_compare.from_david(json.loads(saved.read_text(encoding="utf-8")), raw)
        folder = SPIKE / "side_by_side"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.md"
        path.write_text(f"# {name}\n\n## One of the plans (configuration {config})\n\n```\n{david}\n```\n\n"
                        f"## The other plan\n\n```\n{pasted.read_text(encoding='utf-8').strip()}\n```\n\n"
                        "Which would you shoot? Which can Veo make? (The first is David's; the order is not hidden "
                        "here: `scripts/david_compare.py` makes the blind page.)\n", encoding="utf-8")
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--yes", action="store_true", help="really call the model (it costs money)")
    ap.add_argument("--scene", action="append", help="a scene (default: the gold scenes but the one the prompt shows)")
    ap.add_argument("--config", action="append", choices=CONFIGS[:2], help="A or B (default both)")
    ap.add_argument("--c-model", help="the model for configuration C: the strongest one the account can use")
    ap.add_argument("--scene-dir", help="a folder of real scenes (yaml in the shape of tests/eval/david/scenes)")
    args = ap.parse_args(argv)
    if not args.yes:
        print("This calls the real model about once to three times per scene and configuration and costs money "
              "(roughly $5 to $10 in all). Run it again with --yes to start it.")
        return 2
    from _common import load_env

    load_env()
    from hiru_ai.core.telemetry import enable_tracing

    print("Langfuse tracing:", "on" if enable_tracing() else "off (no LANGFUSE_ keys)")
    scene_dir =Path(args.scene_dir) if args.scene_dir else None
    names = args.scene or (sorted(p.stem for p in scene_dir.glob("*.yaml")) if scene_dir else default_scenes())
    configs = list(args.config or ["A", "B"]) + (["C"] if args.c_model else [])
    rows: list[Row] = []
    for config in configs:
        previous = os.environ.get("OPENAI__MODEL_AUTHOR")
        if config == "C":
            os.environ["OPENAI__MODEL_AUTHOR"] = str(args.c_model)
        from hiru_ai.core.settings import get_settings

        get_settings.cache_clear()
        try:
            for name in names:
                try:
                    rows.append(run_one(config, name, scene_dir))
                except Exception as exc:  # a scene that could not be planned is a row left out, said aloud
                    print(f"\n{config} {name}: did not finish ({type(exc).__name__}: {exc})", flush=True)
        finally:
            if config == "C":
                if previous is None:
                    os.environ.pop("OPENAI__MODEL_AUTHOR", None)
                else:
                    os.environ["OPENAI__MODEL_AUTHOR"] = previous
                get_settings.cache_clear()
    SPIKE.mkdir(parents=True, exist_ok=True)
    table = summary(rows)
    (SPIKE / "summary.md").write_text(table, encoding="utf-8")
    print("\n" + table)
    for path in side_by_side(names, configs[0], scene_dir):
        print(f"side by side: {path}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
