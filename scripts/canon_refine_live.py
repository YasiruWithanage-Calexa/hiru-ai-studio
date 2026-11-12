"""plan/2026-11-12c phase 8: the canon refine on one production, LIVE, through the product's own system.

PAID and it WRITES to the hosted database (new canon versions, draft looks, scene looks, through `canon_refine_apply`):
run only with the person's yes. Before anything is sent, the canon, looks and scene looks as they are now are saved to
`lab/canon_refine/runs/live_<time>/before.json`, so every change can be read back and undone by hand. A real `jobs` row
is made so the token usage rows belong to it. One hard cap (CAP_USD) is checked before every call at its worst case.

    python scripts/canon_refine_live.py <production id> --yes
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts.jobs import DispatchPayload, JobKind  # noqa: E402
from hiru_ai.adapters import supabase_rest  # noqa: E402
from hiru_ai.core.fakes import FakeJobs  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402
from hiru_ai.systems.breakdown.breakdown_canon_refine import graph  # noqa: E402

CAP_USD = 1.00
PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output (gpt-6.1-sol, as the lab)
WORST_OUT = 24_000
SYSTEM_TOKENS = 2_500  # the agent's prompt and house rules, generously


class Meter:
    def __init__(self) -> None:
        self.spent = 0.0
        self.calls: list[dict[str, Any]] = []

    def sink(self, inner: Any) -> Any:
        def write(row: Any) -> None:
            r = dict(row)
            i, c, o = int(r.get("input_tokens") or 0), int(r.get("cached_input_tokens") or 0), int(
                r.get("output_tokens") or 0)
            dollars = (i - c) * PRICE[0] / 1e6 + c * PRICE[1] / 1e6 + o * PRICE[2] / 1e6
            self.spent += dollars
            self.calls.append({"phase": r.get("phase"), "model": r.get("model"), "in": i, "cached": c, "out": o,
                               "dollars": round(dollars, 4)})
            print(f"  call {r.get('phase')}: {i} in ({c} cached), {o} out, ${dollars:.4f}; total ${self.spent:.4f}",
                  flush=True)
            if inner is not None:
                inner(row)

        return write

    def guard(self, name: str, call: Any) -> Any:
        def run(message: str) -> Any:
            worst = (tokens_of(message) + SYSTEM_TOKENS) * PRICE[0] / 1e6 + WORST_OUT * PRICE[2] / 1e6
            if self.spent + worst > CAP_USD:
                raise RuntimeError(f"cap: ${self.spent:.4f} spent, {name} could cost ${worst:.4f}, cap ${CAP_USD:.2f}")
            print(f"  {name}: sending (~{tokens_of(message)} tokens, worst case ${worst:.4f})", flush=True)
            started = time.time()
            out = call(message)
            print(f"  {name}: answered in {time.time() - started:.0f} s", flush=True)
            return out

        return run


class LoudJobs(FakeJobs):
    def event(self, job_id: UUID, type_: Any, payload: dict[str, Any], agent: str | None = None) -> None:
        super().event(job_id, type_, payload, agent)
        print(f"  [{type_.value}] {payload.get('text', '')}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("production")
    ap.add_argument("--yes", action="store_true", help="the person said yes to this paid run that writes")
    a = ap.parse_args()
    if not a.yes:
        raise SystemExit("Paid and it writes: add --yes only after the person said yes.")

    out = ROOT / "lab" / "canon_refine" / "runs" / f"live_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    production_id = UUID(a.production)
    rest = supabase_rest.Rest(*_creds())
    prod = rest.first("productions", {"id": f"eq.{production_id}", "select": "id,title,created_by"})
    if not prod:
        raise SystemExit("No such production.")
    pid = str(production_id)
    before = {
        "canon": rest.select("canon_entities", {"production_id": f"eq.{pid}", "select": "*"}),
        "versions": rest.select("canon_versions", {"production_id": f"eq.{pid}", "select": "*"}),
        "looks": rest.select("canon_looks", {"production_id": f"eq.{pid}", "select": "*"}),
        "scene_looks": rest.select("scene_looks", {"production_id": f"eq.{pid}", "select": "*"}),
    }
    (out / "before.json").write_text(json.dumps(before, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{prod['title']}: backup of {len(before['canon'])} entries, {len(before['versions'])} versions, "
          f"{len(before['looks'])} looks -> {out / 'before.json'}")

    actor = UUID(str(prod["created_by"]))
    job_id = uuid4()
    rest.insert("jobs", [{"id": str(job_id), "kind": JobKind.CANON_REFINE.value, "status": "running",
                          "production_id": pid, "requested_by": str(actor),
                          "request": {"pipeline": [JobKind.CANON_REFINE.value], "by": "scripts/canon_refine_live.py"}}])
    payload = DispatchPayload(job_id=job_id, kind=JobKind.CANON_REFINE, actor_user_id=actor, production_id=production_id,
                              pipeline=[JobKind.CANON_REFINE])
    meter = Meter()
    jobs = LoudJobs()
    ctx = supabase_rest.build_context(payload, jobs=jobs)
    ctx = replace(ctx, usage_sink=meter.sink(ctx.usage_sink))

    def make_calls(c: Any) -> graph.Calls:
        real = graph.calls(c)
        return graph.Calls(canon=meter.guard("canon", real.canon), looks=meter.guard("looks", real.looks))

    started = time.time()
    try:
        result = graph.run(payload, ctx, make_calls=make_calls)
    finally:
        status = jobs.status if jobs.status in ("done", "failed") else "failed"
        rest.patch("jobs", {"id": f"eq.{job_id}"}, {"status": status, "error": jobs.fields.get("error"),
                                                     "result": jobs.fields.get("result")})
    after = {
        "versions": rest.select("canon_versions", {"production_id": f"eq.{pid}", "source": "eq.refine",
                                                   "select": "*"}),
        "canon": rest.select("canon_entities", {"production_id": f"eq.{pid}", "select": "*"}),
        "looks": rest.select("canon_looks", {"production_id": f"eq.{pid}", "origin": "eq.refine", "select": "*"}),
        "scene_looks": rest.select("scene_looks", {"production_id": f"eq.{pid}", "select": "*"}),
    }
    (out / "after.json").write_text(json.dumps(after, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "result.json").write_text(json.dumps({"result": result, "spent": round(meter.spent, 4),
                                                 "seconds": round(time.time() - started), "calls": meter.calls,
                                                 "job_id": str(job_id)}, indent=1, ensure_ascii=False, default=str),
                                     encoding="utf-8")
    print(f"done in {time.time() - started:.0f} s, ${meter.spent:.4f} of ${CAP_USD:.2f}; job {job_id}; files in {out}")
    print(json.dumps({k: v for k, v in result.items() if k not in ("review", "story")}, indent=1))


def _creds() -> tuple[str, str]:
    from hiru_ai.core.settings import get_settings

    s = get_settings()
    return s.supabase.url, s.supabase.service_role_key.get_secret_value()


if __name__ == "__main__":
    main()
