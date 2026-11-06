"""The lab's one tool (plan/2026-11-06 §2, §3): dry run, paid run, budget, cache, check, render.

    python lab/cinematic/run.py dry                         what a paid run would send, and what it could cost (free)
    python lab/cinematic/run.py offline --answer FILE       check and render an answer that already exists (free)
    python lab/cinematic/run.py models                      the models the account can use (free; needs the key)
    python lab/cinematic/run.py ledger                      every paid call so far and the total (free)
    python lab/cinematic/run.py paid --yes --hypothesis "…" a real call (costs money; read the dry run first)
    python lab/cinematic/run.py compare [--run DIR]         the blind side-by-side page of a run (free)

Run it with `OPENAI__API_KEY=` blank for everything but `paid` and `models`: those two read the key from `.env`, nothing
else does. The money rules are code, not habit:

  * `BUDGET_USD` is a constant. A call is refused when the ledger total plus its WORST case would pass it. The worst case
    is the input tokens (estimated high) at the input price, plus `max_output_tokens` at the output price: every call sets
    `max_output_tokens`, reasoning included, so it is known before the call is sent.
  * A model with no price in `PRICES` is refused: put the price from OpenAI's pricing page in the table first.
  * A call that fails or is cut off without usage is entered in the ledger at its worst case.
  * A request is keyed by the hash of (system prompt, example, user message, schema, model, effort): the same key reuses
    the saved answer and costs nothing.
  * After the first run, a run needs a written hypothesis (`--hypothesis`), saved in `notes.md`: one change, one reason.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # started as a script: put the repo's import roots on the path
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_ROOT / "lab"), str(_ROOT / "src" / "libs"), str(_ROOT / "src")]

from pydantic import ValidationError

from cinematic import checks, mend, pack, render, schema
from hiru_ai.core.tokens import tokens_of

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
INPUT, PROMPT, RUNS = LAB / "input", LAB / "prompt", LAB / "runs"
LEDGER = RUNS / "ledger.csv"
GOLD = ROOT / "tests" / "eval" / "david" / "scenes"

BUDGET_USD = 5.00  # the whole lab (plan §2.4): raising it is a code change the person asks for
MAX_OUTPUT_TOKENS = 40_000  # reasoning included
TIMEOUT_S = 1200.0
EXPECTED_OUTPUT_TOKENS = 20_000  # what the dry run quotes as the likely price; the worst case is what is enforced
# model name -> (input, cached input, output), US dollars per million tokens. A name matches itself and its dated snapshot
# only. An unlisted model is refused. These three are the list prices `scripts/david_spike.py` uses; before using any other model, read its price off
# OpenAI's pricing page and add it here.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00),
    # read 2026-11-06 off OpenAI's model page for gpt-5.5 (developers.openai.com/api/docs/models/gpt-5.5); 2x input above 272K tokens
    "gpt-5.5": (5.00, 0.50, 30.00)}
LEDGER_FIELDS = ["time", "run", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens",
                 "dollars", "status", "hypothesis"]
SCENES = {"episode1": "reading.yaml", "second": "second_scene.yaml"}


def scene_path(name: str) -> Path:
    """A lab scene by key, a gold scene by name (tests/eval/david/scenes), or the path of a scene yaml."""
    if name in SCENES:
        return INPUT / SCENES[name]
    for candidate in (Path(name), GOLD / f"{name}.yaml"):
        if candidate.is_file():
            return candidate
    raise LabError(f"Unknown scene {name!r}: use {sorted(SCENES)}, a gold scene name ({', '.join(sorted(p.stem for p in GOLD.glob('*.yaml')))}) or a yaml path.")


class LabError(Exception):
    """A rule of the lab stopped the run; the message says which."""


# ── money ────────────────────────────────────────────────────────────────────────────────────────


def listed_price(model: str) -> tuple[float, float, float] | None:
    """The table's price for the model's own name or its dated snapshot (`gpt-5-2025-08-07`) only. A longer name
    (`gpt-5.5`, `gpt-5-pro`) is a different model with a different price, so it is never matched by prefix."""
    name = model.lower()
    for key, price in PRICES.items():
        if re.fullmatch(re.escape(key) + r"(-\d{4}-\d{2}-\d{2})?", name):
            return price
    return None


def price_of(model: str) -> tuple[float, float, float]:
    price = listed_price(model)
    if price is not None:
        return price
    raise LabError(f"The model {model} has no price in PRICES (run.py). Read it off OpenAI's pricing page and add it "
                   "before any paid run.")


def dollars(model: str, input_tokens: int, cached: int, output: int) -> float:
    pin, pcached, pout = price_of(model)
    return (max(input_tokens - cached, 0) * pin + cached * pcached + output * pout) / 1_000_000


def worst_case(model: str, input_tokens: int, max_output: int = MAX_OUTPUT_TOKENS) -> float:
    """Every input token uncached, every output token spent."""
    return dollars(model, input_tokens, 0, max_output)


def read_ledger() -> list[dict[str, str]]:
    if not LEDGER.exists():
        return []
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ledger_total() -> float:
    return sum(float(r["dollars"] or 0) for r in read_ledger())


def add_to_ledger(row: dict[str, Any]) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def guard(model: str, input_tokens: int, max_output: int = MAX_OUTPUT_TOKENS) -> float:
    """The worst case of the call, or a `LabError` when the budget cannot hold it."""
    worst = worst_case(model, input_tokens, max_output)
    spent = ledger_total()
    if spent + worst > BUDGET_USD + 1e-9:
        raise LabError(f"Refused: ${spent:.2f} is spent and this call could cost ${worst:.2f} more, which passes the "
                       f"${BUDGET_USD:.2f} limit. Spending more is the person's decision (BUDGET_USD in run.py).")
    return worst


# ── the request ──────────────────────────────────────────────────────────────────────────────────


def example_script() -> str:
    """The worked example's script: the gold scene `refuses_money` listed as the author reads it, the words hidden."""
    reading = pack.load(GOLD / "refuses_money.yaml")
    rows = pack.listing(reading.scene).splitlines()
    return "\n".join(re.sub(r': ".*"$', ': "..."', r) if " line [" in r else r for r in rows)


def system_prompt() -> str:
    """The team prompt, then ONE worked example (a different scene from Episode 1, written cinematically)."""
    example = json.loads((PROMPT / "example.json").read_text(encoding="utf-8"))
    return (f"{(PROMPT / 'system.md').read_text(encoding='utf-8').rstrip()}\n\n# A worked example\n\n<example>\n"
            f"<scene>\nScene: The Envelope\n</scene>\n\n<script>\n{example_script()}\n</script>\n\nYour answer:\n"
            f"{json.dumps(example['answer'], ensure_ascii=False, separators=(',', ':'))}\n</example>\n\n"
            "The example shows the shape and the level of craft of one scene; it is not a template for yours. A real "
            "answer has a shot for every block.")


def revise_message(run: str) -> str:
    """The second call (the revise pass): the draft and what code found in it, to be corrected and not rewritten."""
    folder = RUNS / run
    draft = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
    found = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    problems = [f"- {p['sentence']}" for p in found.get("left") or [] if p.get("fix") != "report"]
    craft = [f"- {m['label']}: {m['detail']}" for m in found.get("measures") or [] if m.get("status") == "missed"]
    return ("\n\n<draft>\n" + json.dumps(draft, ensure_ascii=False, separators=(",", ":")) + "\n</draft>\n\n<findings>\n"
            "Problems code found in the draft (fix every one):\n" + ("\n".join(problems) or "- none") + "\n\n"
            "Craft gaps (improve them where the scene allows it):\n" + ("\n".join(craft) or "- none") + "\n</findings>\n\n"
            "The draft is your own first answer. Return the complete corrected plan in the same shape. Change only what the "
            "findings need: keep every shot, sequence and choice that already works, and never remove coverage, a block or a "
            "line to fix a problem.")


def build_request(scene: str, model: str, effort: str, max_output: int = MAX_OUTPUT_TOKENS, repeat: int = 0,
                  revise: str = "") -> dict[str, Any]:
    reading = pack.load(scene_path(scene))
    req: dict[str, Any] = {"scene": scene, "model": model, "effort": effort, "max_output_tokens": max_output,
           "system": system_prompt(), "user": pack.message(reading) + (revise_message(revise) if revise else ""),
           "schema": schema.output_schema()}
    if repeat:  # the same request asked again for a fresh sample (the stability check); it is not sent to the model
        req["repeat"] = repeat
    req["key"] = request_key(req)
    return req


def request_key(req: dict[str, Any]) -> str:
    """The hash of what decides the answer: the same key reuses the saved answer (plan §2.5)."""
    parts = [req["system"], req["user"], json.dumps(req["schema"], sort_keys=True), req["model"], req["effort"]]
    if req.get("repeat"):
        parts.append(f"repeat {req['repeat']}")
    return hashlib.sha256("\n\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def input_estimate(req: dict[str, Any]) -> int:
    return tokens_of(req["system"] + req["user"] + json.dumps(req["schema"]))


def saved_run(key: str) -> Path | None:
    """The run folder that already holds this request's answer."""
    for folder in sorted(RUNS.glob("*/")):
        meta = folder / "request.json"
        if meta.exists() and (folder / "answer.json").exists():
            try:
                if json.loads(meta.read_text(encoding="utf-8")).get("key") == key:
                    return folder
            except ValueError:
                continue
    return None


def next_run_folder(model: str, effort: str, scene: str = "episode1") -> Path:
    numbers = [int(m.group(1)) for p in RUNS.glob("*/") if (m := re.match(r"(\d+)-", p.name))]
    label = "" if scene == "episode1" else "-" + re.sub(r"[^A-Za-z0-9.]+", "_", Path(scene).stem)
    return RUNS / f"{max(numbers, default=0) + 1}-{re.sub(r'[^A-Za-z0-9.]+', '_', model)}-{effort}{label}"


# ── check and render ─────────────────────────────────────────────────────────────────────────────


def process(folder: Path, raw_answer: str, scene: str) -> dict[str, Any]:
    """Parse an answer, check it before and after code's mends, and write what the person reads into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "answer.json").write_text(raw_answer, encoding="utf-8")
    reading = pack.load(scene_path(scene))
    try:
        plan = schema.CinemaWire.model_validate_json(raw_answer)
    except (ValidationError, ValueError) as exc:
        failed = {"error": f"The answer does not fit the schema: {exc}"}
        (folder / "checks.json").write_text(json.dumps(failed, indent=1), encoding="utf-8")
        return failed
    first = checks.hard(reading.scene, plan)
    mended, done, dropped = mend.mend(reading.scene, plan)
    left = checks.hard(reading.scene, mended)
    measured = checks.measures(reading, mended)
    summary: dict[str, Any] = {"first_pass": [p.model_dump() for p in first], "mended": done,
               "dropped": [p.model_dump() for p in dropped], "left": [p.model_dump() for p in left],
               "measures": [m.model_dump() for m in measured],
               "counts": {"shots": len(mended.shots), "take_s": sum(s.take_s for s in mended.shots),
                          "use_s": sum(s.use_s for s in mended.shots), "problems_left": len(left),
                          "faults_left": sum(p.fix != "report" for p in left),  # a keyword advisory (a mirror, screen text) is not one
                          "reports_left": sum(p.fix == "report" for p in left),
                          "measures_met": sum(m.status == "met" for m in measured),
                          "measures_missed": sum(m.status == "missed" for m in measured)}}
    (folder / "plan_mended.json").write_text(mended.model_dump_json(indent=1), encoding="utf-8")
    (folder / "checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "plan.html").write_text(render.plan_html(reading, mended, found=[*left, *dropped], measures=measured,
                                                       mended=done), encoding="utf-8")
    return summary


def contestants(reading: pack.Reading, plan: schema.CinemaWire | None) -> dict[str, str]:
    """The plans of the blind read that exist: this plan, David today, ChatGPT's (each only if its file is there)."""
    out: dict[str, str] = {}
    if plan is not None:
        out["this plan"] = render.plain_list(reading, plan)
    today = INPUT / "david_today.json"
    if today.exists():
        out["David today"] = render.david_today(json.loads(today.read_text(encoding="utf-8")))
    chatgpt = INPUT / "chatgpt.md"
    if chatgpt.exists():
        text = render.comments_stripped(chatgpt.read_text(encoding="utf-8"))
        if text:
            out["ChatGPT"] = text
    return out


# ── commands ─────────────────────────────────────────────────────────────────────────────────────


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines into os.environ; real environment variables win. Only `paid` and `models` call this."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def client() -> Any:
    from hiru_ai.core.llm import openai_client
    from hiru_ai.core.settings import get_settings

    load_env()
    get_settings.cache_clear()
    return openai_client(timeout_s=TIMEOUT_S, retries=0)


def cmd_dry(args: argparse.Namespace) -> int:
    req = build_request(args.scene, args.model, args.effort, args.max_output_tokens, args.repeat, args.revise)
    tokens = input_estimate(req)
    worst = worst_case(args.model, tokens, args.max_output_tokens)
    likely = dollars(args.model, tokens, 0, min(EXPECTED_OUTPUT_TOKENS, args.max_output_tokens))
    hit = saved_run(req["key"])
    print(f"=== system prompt ({len(req['system'])} characters) ===\n{req['system']}\n")
    print(f"=== user message ({len(req['user'])} characters) ===\n{req['user']}\n")
    print(f"=== schema: {len(json.dumps(req['schema']))} characters, name {req['schema']['title']} ===\n")
    print(f"model {args.model}, effort {args.effort}, max_output_tokens {args.max_output_tokens}")
    print(f"input tokens (estimated high): {tokens}")
    print(f"likely price (about {EXPECTED_OUTPUT_TOKENS} output tokens): ${likely:.2f}")
    print(f"WORST case: ${worst:.2f}   spent so far: ${ledger_total():.2f}   limit: ${BUDGET_USD:.2f}")
    print(f"request key {req['key']}" + (f"   ALREADY ANSWERED in {hit.name}: a paid run reuses it for free" if hit else ""))
    try:
        guard(args.model, tokens, args.max_output_tokens)
    except LabError as exc:
        print(str(exc))
        return 1
    return 0


def cmd_paid(args: argparse.Namespace) -> int:
    if not args.yes:
        print("A paid run costs money. Read `dry` first, then run this again with --yes.")
        return 2
    req = build_request(args.scene, args.model, args.effort, args.max_output_tokens, args.repeat, args.revise)
    hit = saved_run(req["key"])
    if hit is not None:
        print(f"Already answered in {hit.name}: reused, nothing spent.")
        process(hit, (hit / "answer.json").read_text(encoding="utf-8"), args.scene)
        return 0
    if read_ledger() and not (args.hypothesis or "").strip():
        raise LabError("After the first run, a run needs --hypothesis: one change, one reason (plan §2.6).")
    tokens = input_estimate(req)
    worst = guard(args.model, tokens, args.max_output_tokens)
    folder = next_run_folder(args.model, args.effort, args.scene)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "notes.md").write_text(f"# Run {folder.name}\n\nHypothesis: {args.hypothesis or '(the first run)'}\n",
                                     encoding="utf-8")
    base: dict[str, Any] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": folder.name, "model": args.model,
            "effort": args.effort, "hypothesis": (args.hypothesis or "").replace("\n", " ")}
    started = time.monotonic()
    try:
        resp = client().responses.create(
            model=args.model, instructions=req["system"], input=req["user"], max_output_tokens=args.max_output_tokens,
            reasoning={"effort": args.effort},
            text={"format": {"type": "json_schema", "name": req["schema"]["title"], "schema": req["schema"],
                             "strict": True}})
    except Exception as exc:  # the call failed: it may still have been billed, so it is entered at its worst case
        add_to_ledger({**base, "dollars": f"{worst:.4f}", "status": f"failed at worst case ({type(exc).__name__})"})
        (folder / "notes.md").write_text((folder / "notes.md").read_text(encoding="utf-8")
                                         + f"\nThe call failed: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"The call failed ({type(exc).__name__}: {exc}); ${worst:.2f} is entered in the ledger (its worst case).")
        return 1
    usage = getattr(resp, "usage", None)
    row: dict[str, Any]
    if usage is None:
        spent, row = worst, {"dollars": f"{worst:.4f}", "status": "no usage reported: worst case"}
    else:
        cached = int(getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0)
        reasoning = int(getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0)
        spent = dollars(args.model, int(usage.input_tokens or 0), cached, int(usage.output_tokens or 0))
        row = {"input_tokens": usage.input_tokens, "cached_tokens": cached, "output_tokens": usage.output_tokens,
               "reasoning_tokens": reasoning, "dollars": f"{spent:.4f}",
               "status": "done" if getattr(resp, "status", "completed") == "completed" else
               f"cut off ({getattr(resp, 'status', '')})"}
    add_to_ledger({**base, **row})
    seconds = time.monotonic() - started
    (folder / "usage.json").write_text(json.dumps({**row, "seconds": round(seconds, 1)}, indent=1), encoding="utf-8")
    summary = process(folder, str(getattr(resp, "output_text", "") or ""), args.scene)
    print(f"{folder.name}: {row['status']}, ${spent:.4f}, {seconds:.0f} s; total ${ledger_total():.2f} of "
          f"${BUDGET_USD:.2f}")
    print(json.dumps(summary.get("counts") or summary, indent=1))
    print(f"read {folder / 'plan.html'}")
    return 0


def score(summary: dict[str, Any]) -> tuple[int, int]:
    """How good a checked plan is, lower is better: real faults first, then craft gaps. (A taste judgement is a person's.)"""
    counts = summary.get("counts") or {}
    return int(counts.get("faults_left", 99)), int(counts.get("measures_missed", 99))


def latest_folder() -> Path:
    numbered = [(int(m.group(1)), p) for p in RUNS.glob("*/") if (m := re.match(r"(\d+)-", p.name))]
    return max(numbered)[1]


def cmd_auto(args: argparse.Namespace) -> int:
    """The stabiliser: the author writes a draft; while code still finds a fault or a craft gap, the author gets its own best
    draft back with the findings and corrects it (at most `--passes` times); the best plan is kept. A pass that makes the
    plan worse is not built on: the next pass starts again from the best one."""
    if not args.yes:
        print("`auto` makes up to 1 + --passes paid calls. Read `dry` first, then run this again with --yes.")
        return 2
    best: tuple[tuple[int, int], str] | None = None
    revise = ""
    for i in range(args.passes + 1):
        sub = argparse.Namespace(**{**vars(args), "revise": revise,
                                    "hypothesis": args.hypothesis or ("auto: the draft" if not revise else f"auto: revise pass {i} of {revise}")})
        if cmd_paid(sub):
            break
        folder = latest_folder()
        found = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
        here = score(found)
        print(f"pass {i}: {folder.name}  faults {here[0]}, craft gaps {here[1]}")
        if best is None or here < best[0]:
            best = (here, folder.name)
        if here == (0, 0):
            break
        revise = best[1]
    if best is None:
        return 1
    print(f"best: {best[1]}  faults {best[0][0]}, craft gaps {best[0][1]}  (read {RUNS / best[1] / 'plan.html'})")
    return 0


def cmd_offline(args: argparse.Namespace) -> int:
    folder = RUNS / "offline"
    summary = process(folder, Path(args.answer).read_text(encoding="utf-8"), args.scene)
    print(json.dumps(summary.get("counts") or summary, indent=1))
    if "left" in summary:
        for p in summary["left"]:
            print(f"  [{p['code']}] {p['sentence']}")
        print(f"read {folder / 'plan.html'}")
    return 0 if "left" in summary else 1


def cmd_compare(args: argparse.Namespace) -> int:
    folder = Path(args.run) if args.run else RUNS / "offline"
    reading = pack.load(scene_path(args.scene))
    mended = folder / "plan_mended.json"
    plan = schema.CinemaWire.model_validate_json(mended.read_text(encoding="utf-8")) if mended.exists() else None
    entries = contestants(reading, plan)
    html, key = render.side_by_side(entries, seed=args.seed)
    (folder / "side_by_side.html").write_text(html, encoding="utf-8")
    (folder / "side_by_side_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(entries)} plan(s) on the page: {folder / 'side_by_side.html'} (the key is beside it; do not open it first)")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    ids = sorted(m.id for m in client().models.list())
    print("\n".join(i + ("" if listed_price(i) else "   (no price in PRICES yet)")
                    for i in ids))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    for r in read_ledger():
        print(f"{r['time']}  {r['run']:<28} ${float(r['dollars'] or 0):7.4f}  {r['status']}  {r['hypothesis']}")
    print(f"total ${ledger_total():.2f} of ${BUDGET_USD:.2f}")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("dry", cmd_dry, "show the request and its price; call nothing"),
                            ("paid", cmd_paid, "make the call (costs money)"),
                            ("auto", cmd_auto, "the stabiliser: a draft, then up to --passes revise calls (costs money)")):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        p.add_argument("--scene", default="episode1", help="a lab key, a gold scene name or a yaml path")
        p.add_argument("--revise", default="", help="a run folder name: send its draft and findings back for a correction")
        p.add_argument("--model", default="gpt-5")
        p.add_argument("--effort", default="high", choices=["minimal", "low", "medium", "high"])
        p.add_argument("--max-output-tokens", type=int, default=MAX_OUTPUT_TOKENS)
        p.add_argument("--repeat", type=int, default=0, help="ask the same request again for a fresh sample (1, 2 …)")
        if name in ("paid", "auto"):
            p.add_argument("--yes", action="store_true")
            p.add_argument("--hypothesis", default="")
        if name == "auto":
            p.add_argument("--passes", type=int, default=2, help="revise calls after the draft (default 2)")
    p = sub.add_parser("offline", help="check and render an existing answer")
    p.set_defaults(fn=cmd_offline)
    p.add_argument("--answer", default=str(LAB / "fixtures" / "fake_answer.json"))
    p.add_argument("--scene", default="episode1")
    p = sub.add_parser("compare", help="the blind side-by-side page")
    p.set_defaults(fn=cmd_compare)
    p.add_argument("--run", default="")
    p.add_argument("--scene", default="episode1")
    p.add_argument("--seed", type=int, default=0)
    sub.add_parser("models", help="list the account's models").set_defaults(fn=cmd_models)
    sub.add_parser("ledger", help="the paid calls so far").set_defaults(fn=cmd_ledger)
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except LabError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
