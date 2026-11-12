"""Canon refine lab (2026-11-12): one model call that writes the canon from the finished breakdown, code checks, and at
most one repair call for the entries that failed. NOTHING is written to the database: the result is files and a report.

    python lab/canon_refine/run.py dry  [run name]         # builds the request, prints its size and worst-case cost
    python lab/canon_refine/run.py live <run name> --yes   # PAID: only with the person's yes

Money (the person's rule): a hard cap for the whole lab (LAB_CAP_USD), checked BEFORE each call at its worst case (every
input token uncached, `max_output` spent); every answer cached by the hash of its request, so the same request never
costs twice; every call entered in runs/ledger.csv. Only `client()` reads the .env key.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import checks  # noqa: E402
import inputs  # noqa: E402
from contracts import safe_depiction  # noqa: E402
from contracts.canon import CanonCard, CanonKind, name_key, reference_sheet_prompt  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402
from schema import Answer, json_schema  # noqa: E402

LAB_CAP_USD = 1.00
MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output (as lab/two_memories/paid.py)
MAX_OUTPUT = 24000
RUNS = HERE / "runs"
LEDGER = RUNS / "ledger.csv"
FIELDS = ["time", "run", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "dollars", "status"]


class CapError(Exception):
    pass


# ── money ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def worst_case(system: str, user: str) -> float:
    return (tokens_of(system) + tokens_of(user)) * PRICE[0] / 1e6 + MAX_OUTPUT * PRICE[2] / 1e6


def _enter(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def call(run: str, slot: str, system: str, user: str, schema: dict[str, Any] | None = None, name: str = "canon") -> str:
    schema = schema or json_schema()
    key = hashlib.sha256(json.dumps([system, user, schema, MODEL, EFFORT], sort_keys=True).encode()).hexdigest()[:24]
    cached = RUNS / "cache" / f"{key}.json"
    if cached.exists():
        print(f"  {slot}: from the cache (no cost)")
        return cached.read_text(encoding="utf-8")
    worst = worst_case(system, user)
    if spent() + worst > LAB_CAP_USD + 1e-9:
        raise CapError(f"Refused: ${spent():.4f} spent; this call could cost ${worst:.4f}; the cap is ${LAB_CAP_USD:.2f}.")
    from cinematic.run import client  # the only place a client is built; it reads .env

    base = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run, "slot": slot, "model": MODEL, "effort": EFFORT}
    print(f"  {slot}: calling {MODEL} ({EFFORT}), worst case ${worst:.4f} ...", flush=True)
    started = time.time()
    try:
        resp = client().responses.create(
            model=MODEL, instructions=system, input=user, max_output_tokens=MAX_OUTPUT, reasoning={"effort": EFFORT},
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}})
    except Exception as exc:
        _enter({**base, "dollars": f"{worst:.4f}", "status": f"failed, worst case entered: {type(exc).__name__}"})
        raise
    u = getattr(resp, "usage", None)
    if u is None:
        dollars, usage = worst, {}
    else:
        c = int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0)
        i, o = int(u.input_tokens or 0), int(u.output_tokens or 0)
        dollars = (i - c) * PRICE[0] / 1e6 + c * PRICE[1] / 1e6 + o * PRICE[2] / 1e6
        usage = {"input_tokens": i, "cached_tokens": c, "output_tokens": o}
    status = "done" if getattr(resp, "status", "completed") == "completed" else f"cut off ({resp.status})"
    _enter({**base, "dollars": f"{dollars:.4f}", "status": status, **usage})
    print(f"  {slot}: {status} in {time.time() - started:.0f} s, ${dollars:.4f} {usage}")
    text = str(getattr(resp, "output_text", "") or "")
    if status != "done":
        raise CapError(f"The answer was {status}; not cached. ${dollars:.4f} entered.")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


# ── the request ────────────────────────────────────────────────────────────────────────────────────────────────────


def system_prompt() -> str:
    return (HERE / "system.md").read_text(encoding="utf-8").strip() + "\n\n" + safe_depiction.PROMPT_LINE


def repair_message(user: str, answer: Answer, found: list[checks.Finding]) -> str:
    ids = sorted({f.id for f in found})
    bad = {
        "people": [p.model_dump() for p in answer.people if p.id in ids],
        "places": [p.model_dump() for p in answer.places if p.id in ids],
        "things": [t.model_dump() for t in answer.things if t.id in ids],
    }
    return (f"{user}\n\nYOUR EARLIER ANSWER FOR THESE IDS FAILED A CHECK\n{json.dumps(bad, ensure_ascii=False, indent=1)}\n\n"
            "THE CHECKS SAID\n" + "\n".join(f"- {f.message}" for f in found) +
            f"\n\nAnswer again for ONLY these ids: {', '.join(ids)}. Fix exactly what the checks say; keep the rest. "
            "Return `looks` as an empty list.")


def merge(answer: Answer, fixed: Answer) -> Answer:
    def by_id(old: list[Any], new: list[Any]) -> list[Any]:
        repl = {x.id: x for x in new}
        return [repl.get(x.id, x) for x in old] + [x for x in new if x.id not in {o.id for o in old}]

    return Answer(people=by_id(answer.people, fixed.people), places=by_id(answer.places, fixed.places),
                  things=by_id(answer.things, fixed.things), looks=answer.looks)


# ── the report ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _v(v: Any) -> str:
    return f"{v.value}  _({v.source}{f', line {v.line}' if v.source == 'script' else ''}{f': {v.reason}' if v.reason else ''})_"


def report(export: dict[str, Any], answer: Answer, found: list[checks.Finding], fixed: bool) -> str:
    mem = export["memory"]
    ents = {e["id"]: e for e in mem["entities"]}
    kinds = {"person": "character", "place": "location", "thing": "prop"}
    canon = {(c["kind"], name_key(c["name"])): c for c in export["canon"]}

    def today(eid: str) -> dict[str, Any]:
        e = ents[eid]
        return canon.get((kinds[e["kind"]], name_key(e["name"]))) or {}

    out = [f"# Canon refine · {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"Findings after {'the repair call' if fixed else 'the first call'}: **{len(found)}**", ""]
    out += [f"- `{f.code}` {f.message}" for f in found] or ["- none"]
    out += ["", "## People", ""]
    for p in answer.people:
        c = today(p.id)
        card = CanonCard(age=p.age.value, gender=p.gender.value, appearance=p.appearance.value[:600],
                         wardrobe=p.wardrobe.value[:600], voice=p.voice.value[:300])
        out += [f"### {p.id} {ents.get(p.id, {}).get('name', '?')}  (today: {c.get('code', '-')}, {c.get('source', '-')}"
                f"{', LOCKED' if c.get('locked') else ''})", "",
                "| | today | refined |", "|---|---|---|"]
        for k in ("gender", "age", "appearance", "wardrobe", "voice"):
            out.append(f"| {k} | {(c.get('card') or {}).get(k, '') or '—'} | {_v(getattr(p, k))} |")
        out += ["", "Sheet prompt facts:", "```", reference_sheet_prompt(CanonKind.CHARACTER, ents[p.id]["name"], card).split("Aspect ratio")[1].split("\n", 1)[1], "```", ""]
    out += ["## Places", ""]
    for pl in answer.places:
        c = today(pl.id)
        plate = pl.kind in ("set", "vehicle")
        out += [f"### {pl.id} {ents.get(pl.id, {}).get('name', '?')} · **{pl.kind}**{f' of {pl.parent}' if pl.parent else ''}"
                f"  (today: {c.get('code', '-')}, {c.get('source', '-')})", "", f"_why:_ {pl.why}", "",
                f"- today's summary: {((c.get('card') or {}).get('summary') or '—')[:160]}",
                f"- today's look: {(c.get('card') or {}).get('look') or '—'}",
                f"- refined look: {_v(pl.look)}",
                f"- plate: {'yes' if plate else 'no'}", ""]
        if plate:
            facts = reference_sheet_prompt(CanonKind.LOCATION, ents[pl.id]["name"], CanonCard(look=pl.look.value[:800]))
            out += ["```", facts.split("\n", 1)[1], "```", ""]
    out += ["## Things", ""]
    for t in answer.things:
        c = today(t.id)
        out += [f"- **{t.id} {ents.get(t.id, {}).get('name', '?')}** · {t.kind} · today ({c.get('source', '-')}): "
                f"{((c.get('card') or {}).get('details') or (c.get('card') or {}).get('summary') or '—')[:100]}",
                f"  - refined: {_v(t.details)}"]
    out += ["", "## Looks", ""]
    for lk in answer.looks:
        out += [f"- **{lk.person} · {lk.name}** ({lk.from_scene} → {lk.to_scene or 'end'}): outfit {lk.outfit}; hair {lk.hair}; "
                f"makeup {lk.makeup}; accessories {lk.accessories}. _{lk.why}_"]
    if not answer.looks:
        out.append("- none")
    return "\n".join(out) + "\n"


# ── main ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dry", "live"])
    ap.add_argument("run", nargs="?", default="dry")
    ap.add_argument("--export", default=str(HERE / "ekama" / "export.json"))
    ap.add_argument("--yes", action="store_true", help="the person said yes to this paid run")
    ap.add_argument("--no-repair", action="store_true")
    a = ap.parse_args()

    export = json.loads(Path(a.export).read_text(encoding="utf-8"))
    system, user = system_prompt(), inputs.message(export)
    lines = [ln for s in export["sources"] for ln in s["body"]["lines"]]
    out = RUNS / a.run
    out.mkdir(parents=True, exist_ok=True)
    (out / "request_system.md").write_text(system, encoding="utf-8")
    (out / "request_user.txt").write_text(user, encoding="utf-8")
    tin = tokens_of(system) + tokens_of(user)
    print(f"request: ~{tin} input tokens, max {MAX_OUTPUT} output; worst case ${worst_case(system, user):.4f} per call; "
          f"lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")
    if a.mode == "dry":
        print(f"dry run: request saved to {out}; nothing was sent")
        return
    if not a.yes:
        raise SystemExit("A live run is paid: add --yes only after the person said yes.")

    answer = Answer.model_validate_json(call(a.run, "refine", system, user))
    (out / "answer.json").write_text(answer.model_dump_json(indent=1), encoding="utf-8")
    found = checks.check(answer, export["memory"], lines)
    print(f"  checks: {len(found)} findings")
    for f in found:
        print(f"    - {f.code}: {f.message}")
    fixed = False
    if found and not a.no_repair:
        patch = Answer.model_validate_json(call(a.run, "repair", system, repair_message(user, answer, found)))
        (out / "repair.json").write_text(patch.model_dump_json(indent=1), encoding="utf-8")
        answer = merge(answer, patch)
        found = checks.check(answer, export["memory"], lines)
        fixed = True
        print(f"  after repair: {len(found)} findings")
    (out / "final.json").write_text(answer.model_dump_json(indent=1), encoding="utf-8")
    (out / "findings.json").write_text(json.dumps([f.__dict__ for f in found], indent=1), encoding="utf-8")
    (out / "report.md").write_text(report(export, answer, found, fixed), encoding="utf-8")
    print(f"report: {out / 'report.md'}; lab spent ${spent():.4f} of ${LAB_CAP_USD:.2f}")


if __name__ == "__main__":
    main()
