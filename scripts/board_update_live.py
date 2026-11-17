"""plan/2026-11-17 phase 6: Update board, LIVE, on one real scene with an approved board, through the product's
own code.

PAID and it WRITES to the hosted database: run each paid step only with the person's yes. Steps, one at a time:

    plan      (free, no write) the three edits tried on a copy: what changes, what the board would say
    edit      (free, WRITES) the three edits saved through the shared row save (`core.coverage_rows.Saver`, as Zora's
              and Sable's), one revision each, so the scene's chat can undo them; a backup of the shots, lines and
              board rows is written first
    update    (PAID, WRITES) what `POST .../board/update` does (every part queued, approval carried) and then the job
              (`frame_render`, `state.update`), metered against CAP_USD
    look      (free) the board's cells and sheet downloaded into the run folder
    approve   (free, WRITES) the part approved, as `POST .../scene-boards/{id}/approve`
    frame     (PAID, WRITES) one MEDIUM first frame of one shot from its new panel, as `POST .../shots/{id}/frames`

    python scripts/board_update_live.py plan
    python scripts/board_update_live.py edit --yes
    python scripts/board_update_live.py update --yes --run live_<time>
    python scripts/board_update_live.py look --run live_<time>
    python scripts/board_update_live.py approve --yes --run live_<time>
    python scripts/board_update_live.py frame --yes --run live_<time> --shot <number>

Files go to `lab/panel_edit/runs/live_<time>/`. Token rows belong to a real `jobs` row per paid step.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from contracts import board as kit  # noqa: E402
from contracts.jobs import DispatchPayload, JobKind  # noqa: E402
from hiru_ai.adapters import supabase_rest  # noqa: E402
from hiru_ai.core import coverage_rows, parts  # noqa: E402
from hiru_ai.core.fakes import FakeJobs  # noqa: E402

SCENE = "bd5a6483-0eef-4a66-afac-b60556478618"  # Love Hour 4, scene 3: 5 shots, vertical, board v5 approved
CAP_USD = 1.00  # the whole live check
# $/1M tokens (input, output); gpt-image-2 over-stated on purpose, as the labs
PRICES = {"gpt-image-2": (10.00, 40.00)}
DEFAULT_PRICE = (2.00, 10.00)
RUNS = ROOT / "lab" / "panel_edit" / "runs"

# The three edits a director might make, in the kernel's own operations (`steps/coverage_kernel`), by a person.
CHANGE = [{"op": "set", "shot": "S03", "field": "angle", "value": "low, from curb height beside the drain"},
          {"op": "set", "shot": "S03", "field": "lens", "value": "24mm"}]
ADD = [{"op": "insert", "after": "S03", "role": "insert", "size": "INSERT", "take_s": 4, "first_block": 2,
        "last_block": 2, "who": ["Kasun"], "what": "the phone in Kasun's right hand, rain drops on its dark screen"}]
ADD_PICTURE = [  # the new clip's picture, as Zora's author would write it (the clip after S03 is the new S04)
    {"op": "set", "shot": "S04", "field": "setting",
     "value": "Beside the three-wheeler at the vending bay; wet pavement, light rain."},
    {"op": "set", "shot": "S04", "field": "first_frame",
     "value": {"composition": "Vertical 9:16 insert, close on Kasun's right hand turning the phone over; the wet curb "
                              "and the three-wheeler's maroon bodywork soft behind.",
               "subjects": ["Kasun's right hand holds the phone screen up, rain drops on the dark glass"]}}]
REMOVE = [{"op": "remove", "shot": "S02"}]


class Meter:
    def __init__(self, spent: float = 0.0) -> None:
        self.spent = spent
        self.calls: list[dict[str, Any]] = []

    def sink(self, inner: Any) -> Any:
        def write(row: Any) -> None:
            r = dict(row)
            model = str(r.get("model") or "")
            i, o = int(r.get("input_tokens") or 0), int(r.get("output_tokens") or 0)
            pin, pout = PRICES.get(model, DEFAULT_PRICE)
            dollars = i * pin / 1e6 + o * pout / 1e6
            self.spent += dollars
            self.calls.append({"phase": r.get("phase"), "model": model, "in": i, "out": o,
                               "dollars": round(dollars, 4)})
            print(f"  call {r.get('phase')} {model}: {i} in, {o} out, ${dollars:.4f}; run total ${self.spent:.4f}",
                  flush=True)
            if inner is not None:
                inner(row)

        return write


class LoudJobs(FakeJobs):
    def event(self, job_id: UUID, type_: Any, payload: dict[str, Any], agent: str | None = None) -> None:
        super().event(job_id, type_, payload, agent)
        print(f"  [{type_.value}] {payload.get('text', '')}", flush=True)


def _creds() -> tuple[str, str]:
    from hiru_ai.core.settings import get_settings

    s = get_settings()
    return s.supabase.url, s.supabase.service_role_key.get_secret_value()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Live:
    def __init__(self, run: str | None) -> None:
        self.rest = supabase_rest.Rest(*_creds())
        scene = self.rest.first("scenes", {"id": f"eq.{SCENE}", "select": "id,production_id,number,status"})
        if not scene:
            raise SystemExit("No such scene.")
        self.scene: dict[str, Any] = scene
        self.pid = str(self.scene["production_id"])
        prod = self.rest.first("productions", {"id": f"eq.{self.pid}", "select": "id,title,created_by,orientation"})
        assert prod is not None
        self.prod = prod
        self.actor = UUID(str(prod["created_by"]))
        self.dir = RUNS / (run or f"live_{time.strftime('%Y%m%d_%H%M%S')}")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.state: dict[str, Any] = (json.loads(self.state_file.read_text(encoding="utf-8"))
                                      if self.state_file.exists() else {"spent": 0.0, "steps": []})

    def save_state(self) -> None:
        self.state_file.write_text(json.dumps(self.state, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    def shots(self) -> list[dict[str, Any]]:
        return self.rest.select("shots", {"scene_id": f"eq.{SCENE}", "select": "*", "order": "number"})

    def boards(self) -> list[dict[str, Any]]:
        rows = self.rest.select("scene_boards", {"scene_id": f"eq.{SCENE}", "select": "*"})
        top = max(int(r["version"]) for r in rows)
        return sorted((r for r in rows if int(r["version"]) == top), key=lambda r: int(r["part"]))

    def context(self, kind: JobKind, state: dict[str, Any], meter: Meter | None = None) -> tuple[Any, Any, Any]:
        job_id = uuid4()
        self.rest.insert("jobs", [{"id": str(job_id), "kind": kind.value, "status": "running",
                                   "production_id": self.pid,
                                   "requested_by": str(self.actor),
                                   "request": {"pipeline": [kind.value], "by": "scripts/board_update_live.py"}}])
        payload = DispatchPayload(job_id=job_id, kind=kind, actor_user_id=self.actor, production_id=UUID(self.pid),
                                  pipeline=[kind], state=state)
        jobs = LoudJobs()
        ctx = supabase_rest.build_context(payload, jobs=jobs)
        if meter is not None:
            ctx = replace(ctx, usage_sink=meter.sink(ctx.usage_sink))
            # the painter after the meter: it keeps the sink it was built with, so image calls are metered too
            from hiru_ai.adapters import images as painter

            ctx = replace(ctx, ports=replace(ctx.ports, images=painter.build(sink=ctx.sink())))
        return ctx, payload, jobs

    def finish_job(self, payload: Any, jobs: Any) -> None:
        status = jobs.status if jobs.status in ("done", "failed") else "failed"
        self.rest.patch("jobs", {"id": f"eq.{payload.job_id}"}, {"status": status, "error": jobs.fields.get("error"),
                                                                  "result": jobs.fields.get("result")})


def stale_now(live: Live) -> kit.Stale:
    return kit.stale_cells([c for p in live.boards() for c in p.get("cells") or []], live.shots())


def edits(live: Live, *, write: bool) -> None:
    ctx = supabase_rest.build_context(DispatchPayload(job_id=uuid4(), kind=JobKind.FRAME_RENDER,
                                                      actor_user_id=live.actor, production_id=UUID(live.pid)),
                                      jobs=FakeJobs())
    kernel = parts.step("coverage_kernel", "logic").Kernel
    if write:
        (live.dir / "before.json").write_text(json.dumps({
            "shots": live.shots(), "boards": live.boards(),
            "lines": live.rest.select("dialogue_lines", {"scene_id": f"eq.{SCENE}", "select": "*"}),
        }, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"backup -> {live.dir / 'before.json'}")
    for name, batches in (("change", [CHANGE]), ("add", [ADD, ADD_PICTURE]), ("remove", [REMOVE])):
        world = coverage_rows.read(ctx, UUID(live.pid), UUID(SCENE))
        if isinstance(world, str):
            raise SystemExit(world)
        after = world.cov.copy()
        for ops in batches:
            res = kernel(after).apply(ops, by="person")
            for a in res.applied:
                print(f"  {name}: {a['text']}")
            if res.rejected:
                raise SystemExit(f"{name} refused: {res.rejected}")
        plan = coverage_rows.rows_for(world.cov, after, planner="raphael")
        print(f"  {name}: touches {len(plan.touched)} rows, removes {len(plan.removed)}")
        if not write:
            continue
        saved = coverage_rows.Saver(ctx, world, actor_user_id=live.actor, chat="zora").save(after, kind="use")
        if not saved.ok:
            raise SystemExit(f"{name} not saved: {saved.reason}")
        print(f"  {name}: saved, revision {saved.revision}")
        live.state["steps"].append({"step": f"edit:{name}", "revision": saved.revision, "at": _now()})
    if write:
        st = stale_now(live)
        print("board now says:", st.reasons(), st.items())
        live.save_state()


def update(live: Live) -> None:
    parts_rows = live.boards()
    st = stale_now(live)
    print("out of date:", st.reasons())
    if not (st.paint or st.tidy):
        raise SystemExit("Nothing on the board is out of date.")
    ids = [str(p["id"]) for p in parts_rows]
    approvals = {str(p["id"]): {"approved_at": p.get("approved_at"), "approved_by": p.get("approved_by")}
                 for p in parts_rows if p.get("approved_at")}
    for p in parts_rows:  # what the API does: queued, approval cleared and carried in the job
        live.rest.patch("scene_boards", {"id": f"eq.{p['id']}"}, {"status": "queued", "approved_at": None,
                                                                  "approved_by": None, "error": None})
    state = {"update": True, "scene_id": SCENE, "board_ids": ids, "shots": [], "approvals": approvals}
    meter = Meter(live.state["spent"])
    ctx, payload, jobs = live.context(JobKind.FRAME_RENDER, state, meter)
    for p in parts_rows:
        live.rest.patch("scene_boards", {"id": f"eq.{p['id']}"}, {"job_id": str(payload.job_id)})
    from hiru_ai.systems.frame_render import graph as fr_graph

    started = time.time()
    try:
        result = fr_graph.run(payload, ctx)
    finally:
        live.finish_job(payload, jobs)
    live.state["spent"] = meter.spent
    live.state["steps"].append({"step": "update", "job_id": str(payload.job_id), "result": result,
                                "seconds": round(time.time() - started), "calls": meter.calls, "at": _now()})
    live.save_state()
    print(json.dumps(result, indent=1, default=str))
    print(f"update done in {time.time() - started:.0f} s; run total ${meter.spent:.4f} of ${CAP_USD:.2f}")


def look(live: Live) -> None:
    files = supabase_rest.build_context(DispatchPayload(job_id=uuid4(), kind=JobKind.FRAME_RENDER,
                                                       actor_user_id=live.actor, production_id=UUID(live.pid)),
                                        jobs=FakeJobs()).need("files")
    out = live.dir / "look"
    out.mkdir(exist_ok=True)
    for p in live.boards():
        print(f"part {p['part']}: v{p['version']} {p['status']} approved={bool(p.get('approved_at'))} "
              f"error={p.get('error')}")
        if p.get("sheet_path"):
            (out / f"part{p['part']}_sheet.png").write_bytes(bytes(files.download("frames", p["sheet_path"])))
        for c in p.get("cells") or []:
            tag = "FRESH " if c.get("fresh") else ""
            print(f"  shot {c['number']}: {tag}{c['kind']} {c.get('source', 'sheet')} {c.get('path')}")
            if c.get("path"):
                (out / f"shot_{int(c['number']):02d}{'_fresh' if c.get('fresh') else ''}.png").write_bytes(
                    bytes(files.download("frames", c["path"])))
        w = kit.Writer.of(p.get("writer") or {})
        (out / f"part{p['part']}_writer.json").write_text(json.dumps(w.dump(), indent=1, ensure_ascii=False),
                                                          encoding="utf-8")
    print("stale now:", stale_now(live).reasons() or "nothing")
    print(f"pictures in {out}")


def approve(live: Live) -> None:
    for p in live.boards():
        if p["status"] != "done":
            raise SystemExit(f"part {p['part']} is {p['status']}")
        if not p.get("approved_at"):
            live.rest.patch("scene_boards", {"id": f"eq.{p['id']}"}, {"approved_at": _now(),
                                                                      "approved_by": str(live.actor)})
            print(f"part {p['part']} approved")
    live.state["steps"].append({"step": "approve", "at": _now()})
    live.save_state()


def frame(live: Live, number: int) -> None:
    from api.services import boards as board_rules  # the API's own D3 gate

    shot = next(s for s in live.shots() if int(s["number"]) == number)
    gate = board_rules.shot_panel(live.boards(), shot, plate=False)
    if not gate.ready:
        raise SystemExit(f"shot {number}: {gate.reason}")
    fid = str(uuid4())
    live.rest.insert("first_frames", [{"id": fid, "production_id": live.pid, "shot_id": shot["id"],
                                       "status": "queued", "stage": "final", "created_by": str(live.actor),
                                       "board_id": gate.board_id}])
    state = {"frame_ids": [fid], "from_board": True, "quality": "medium"}
    meter = Meter(live.state["spent"])
    ctx, payload, jobs = live.context(JobKind.FRAME_RENDER, state, meter)
    live.rest.patch("first_frames", {"id": f"eq.{fid}"}, {"job_id": str(payload.job_id)})
    from hiru_ai.systems.frame_render import graph as fr_graph

    try:
        result = fr_graph.run(payload, ctx)
    finally:
        live.finish_job(payload, jobs)
    row = live.rest.first("first_frames", {"id": f"eq.{fid}", "select": "*"})
    assert row is not None
    if row.get("storage_path"):
        files = ctx.need("files")
        (live.dir / f"frame_shot_{number:02d}.png").write_bytes(bytes(files.download("frames", row["storage_path"])))
    (live.dir / f"frame_shot_{number:02d}.json").write_text(json.dumps(row, indent=1, ensure_ascii=False,
                                                                       default=str), encoding="utf-8")
    live.state["spent"] = meter.spent
    live.state["steps"].append({"step": "frame", "shot": number, "frame_id": fid, "job_id": str(payload.job_id),
                                "result": result, "calls": meter.calls, "at": _now()})
    live.save_state()
    print(f"frame {row.get('status')} {row.get('error') or ''}; run total ${meter.spent:.4f} of ${CAP_USD:.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["plan", "edit", "update", "look", "approve", "frame"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to this step")
    ap.add_argument("--run", help="the run folder of an earlier step (live_<time>)")
    ap.add_argument("--shot", type=int, help="frame: the shot number")
    a = ap.parse_args()
    if a.step in ("edit", "update", "approve", "frame") and not a.yes:
        raise SystemExit("This step writes (and update / frame pay): add --yes only after the person said yes.")
    live = Live(a.run)
    print(f"{live.prod['title']} scene {live.scene['number']} ({live.prod.get('orientation')}); run {live.dir.name}")
    if a.step in ("update", "frame") and live.state["spent"] >= CAP_USD:
        raise SystemExit(f"cap reached: ${live.state['spent']:.4f}")
    if a.step == "plan":
        edits(live, write=False)
    elif a.step == "edit":
        edits(live, write=True)
    elif a.step == "update":
        update(live)
    elif a.step == "look":
        look(live)
    elif a.step == "approve":
        approve(live)
    else:
        if a.shot is None:
            raise SystemExit("frame needs --shot")
        frame(live, a.shot)


if __name__ == "__main__":
    main()
