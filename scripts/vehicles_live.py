"""plan/2026-11-24b phase 8: vehicles, LIVE, on Love Hour scenes 4 and 2, through the product's own code.

PAID and it WRITES to the hosted database: run each paid step only with the person's yes. Steps, one at a time:

    find      (free, no write) the scene, its board, each shot's vehicles and roles as the product reads them now
    roles     (free, WRITES) scene 2's roles as a person would set them on the shot screen (`PersonEdits.vehicles`):
              shot 1 INSIDE the Family car, shots 2-5 the car AT the kerb; a backup of the shots is written first
    board     (PAID, WRITES) a whole board, a new version at LOW, as `POST .../scenes/{id}/board`
    look      (free) the board's sheet and cells downloaded into the run folder
    approve   (free, WRITES) every part of the newest board approved, as `POST .../scene-boards/{id}/approve`
    frame     (PAID, WRITES) one MEDIUM first frame of one shot from its panel, as `POST .../shots/{id}/frames`

    python scripts/vehicles_live.py find --scene de75bc31
    python scripts/vehicles_live.py roles --scene 6de06ab0 --yes
    python scripts/vehicles_live.py board --scene de75bc31 --yes [--run live_<time>]
    python scripts/vehicles_live.py look --scene de75bc31 --run live_<time>
    python scripts/vehicles_live.py approve --scene de75bc31 --yes --run live_<time>
    python scripts/vehicles_live.py frame --scene de75bc31 --shot 1 --yes --run live_<time>

Files go to `lab/vehicle_role/runs/live_<time>/`. Every paid step is metered against CAP_USD (the whole check).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src"), str(ROOT / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import board_update_live as bul  # noqa: E402  (its meter, jobs and job context)

from contracts import board as kit  # noqa: E402
from contracts import vehicles as vh  # noqa: E402
from contracts.jobs import DispatchPayload, JobKind  # noqa: E402
from contracts.producer import PersonEdits  # noqa: E402
from hiru_ai.adapters import supabase_rest  # noqa: E402
from hiru_ai.core.fakes import FakeJobs  # noqa: E402

PRODUCTION = "b89f79a3-3ce6-4123-aee5-759f35c09d69"  # Love Hour (the labs' production)
CAP_USD = 1.00  # the whole live check: about $0.52 expected
RUNS = ROOT / "lab" / "vehicle_role" / "runs"
SCENE_4, SCENE_2 = "de75bc31", "6de06ab0"  # the labs' scenes: "A conversation that changes everything", "Anudi arrives"
KERB = ("stopped on the asphalt beside the kerb drain, all four wheels on the road, nose toward screen right, its "
        "pavement-side rear door toward the pavement")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Live(bul.Live):
    """`board_update_live.Live` on another scene of Love Hour, with this check's run folder."""

    def __init__(self, scene_id: str, run: str | None) -> None:
        self.rest = supabase_rest.Rest(*bul._creds())
        rows = [r for r in self.rest.select("scenes", {"production_id": f"eq.{PRODUCTION}",
                                                       "select": "id,production_id,number,status,heading,"
                                                                 "location_id,episode_id"})
                if str(r["id"]).startswith(scene_id)]
        if len(rows) != 1:
            raise SystemExit(f"{len(rows)} Love Hour scenes start with {scene_id}")
        self.scene = rows[0]
        bul.SCENE = str(self.scene["id"])  # the borrowed helpers read the scene from here
        self.pid = PRODUCTION
        prod = self.rest.first("productions", {"id": f"eq.{self.pid}", "select": "id,title,created_by,orientation"})
        assert prod is not None
        self.prod = prod
        self.actor = UUID(str(prod["created_by"]))
        self.dir = RUNS / (run or f"live_{time.strftime('%Y%m%d_%H%M%S')}")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.state: dict[str, Any] = (json.loads(self.state_file.read_text(encoding="utf-8"))
                                      if self.state_file.exists() else {"spent": 0.0, "steps": []})

    def canon(self) -> list[dict[str, Any]]:
        return self.rest.select("canon_entities", {
            "production_id": f"eq.{self.pid}",
            "select": "*,current:canon_versions!canon_entities_current_version_fkey(*)"})

    def all_boards(self) -> list[dict[str, Any]]:
        return self.rest.select("scene_boards", {"scene_id": f"eq.{self.scene['id']}", "select": "*"})


def find(live: Live) -> None:
    canon = live.canon()
    loc = next((c for c in canon if str(c["id"]) == str(live.scene.get("location_id"))), None)
    print(f"scene {live.scene['number']} {live.scene.get('heading')} [{live.scene.get('status')}] at "
          f"{(loc or {}).get('name')}")
    for c in vh.vehicle_cards(canon):
        print(f"  vehicle {c.get('code')} {c['name']} make={vh.make_of(c)!r} plate="
              f"{'yes' if kit_sheet(c) else 'no'} views={'yes' if views(c) else 'no'} locked={c.get('locked')}")
    print(f"  place views sheet: {'yes' if loc and views(loc) else 'no'}")
    boards = live.all_boards()
    top = max((int(b["version"]) for b in boards), default=0)
    for b in sorted((b for b in boards if int(b["version"]) == top), key=lambda r: int(r["part"])):
        print(f"  board v{b['version']} part {b['part']}: {b['status']} approved={bool(b.get('approved_at'))} "
              f"{b.get('quality')}")
    for s in live.shots():
        got = vh.shot_vehicles(s, canon, PersonEdits.of(s).vehicles)
        said = "; ".join(f"{v.name} {v.role}" + (f" ({v.where})" if v.where else "") for v in got) or "none"
        stored = "ir" if isinstance((s.get("ir") or {}).get("vehicles"), list) else "found by name"
        print(f"  shot {s['number']}: {said} [{stored}]  {str((s.get('ir') or {}).get('setting') or '')[:90]}")


def kit_sheet(row: dict[str, Any]) -> str:
    from contracts.frame_brief import sheet_path

    return sheet_path(row)


def views(row: dict[str, Any]) -> bool:
    from contracts.canon import views_asset

    return views_asset(row) is not None


def roles(live: Live) -> None:
    if not str(live.scene["id"]).startswith(SCENE_2):
        raise SystemExit("roles are set for scene 2 (Anudi arrives) only")
    canon = live.canon()
    car = next((c for c in vh.vehicle_cards(canon) if c["name"] == "Family car"), None)
    if car is None:
        raise SystemExit("No Family car card.")
    shots = live.shots()
    (live.dir / "before_roles.json").write_text(json.dumps(shots, indent=1, ensure_ascii=False, default=str),
                                                encoding="utf-8")
    print(f"backup -> {live.dir / 'before_roles.json'}")
    for s in shots:
        n = int(s["number"])
        if n > 5:
            continue
        edits = PersonEdits.of(s)
        mine = vh.VehicleEdit(id=str(car["id"]), role="inside" if n == 1 else "at", where="" if n == 1 else KERB)
        edits.vehicles = [*(e for e in edits.vehicles if e.id != mine.id), mine]
        live.rest.patch("shots", {"id": f"eq.{s['id']}"}, {"person_edits": edits.dump()})
        print(f"  shot {n}: Family car {mine.role}")
    live.state["steps"].append({"step": "roles", "at": _now()})
    live.save_state()


def board(live: Live) -> None:
    boards = live.all_boards()
    top = max((int(b["version"]) for b in boards), default=0)
    current = [b for b in boards if int(b["version"]) == top]
    board_id = str(uuid4())
    live.rest.insert("scene_boards", [{"id": board_id, "production_id": live.pid, "scene_id": live.scene["id"],
                                       "version": top + 1, "part": 1, "parts": 1, "status": "queued",
                                       "quality": "low", "created_by": str(live.actor)}])
    state = {"board_id": board_id, "carry": [str(p["id"]) for p in current if p.get("status") == "done"]}
    meter = bul.Meter(live.state["spent"])
    ctx, payload, jobs = live.context(JobKind.FRAME_RENDER, state, meter)
    live.rest.patch("scene_boards", {"id": f"eq.{board_id}"}, {"job_id": str(payload.job_id)})
    from hiru_ai.systems.frame_render import graph as fr_graph

    started = time.time()
    try:
        result = fr_graph.run(payload, ctx)
    finally:
        live.finish_job(payload, jobs)
    live.state["spent"] = meter.spent
    live.state["steps"].append({"step": "board", "board_id": board_id, "version": top + 1, "result": result,
                                "seconds": round(time.time() - started), "calls": meter.calls, "at": _now()})
    live.save_state()
    rows = live.all_boards()
    for b in sorted((b for b in rows if int(b["version"]) == top + 1), key=lambda r: int(r["part"])):
        (live.dir / f"board_v{b['version']}_part{b['part']}_prompt.txt").write_text(str(b.get("prompt") or ""),
                                                                                  encoding="utf-8")
        print(f"part {b['part']}: {b['status']} {b.get('error') or ''}")
    print(f"board done in {time.time() - started:.0f} s; run total ${meter.spent:.4f} of ${CAP_USD:.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["find", "roles", "board", "look", "approve", "frame"])
    ap.add_argument("--scene", required=True, help=f"the scene id or its start: {SCENE_4} (4), {SCENE_2} (2)")
    ap.add_argument("--yes", action="store_true", help="the person said yes to this step")
    ap.add_argument("--run", help="the run folder of an earlier step (live_<time>)")
    ap.add_argument("--shot", type=int)
    a = ap.parse_args()
    if a.step in ("roles", "board", "approve", "frame") and not a.yes:
        raise SystemExit("This step writes (and board / frame pay): add --yes only after the person said yes.")
    live = Live(a.scene, a.run)
    bul.CAP_USD = CAP_USD
    print(f"{live.prod['title']} scene {live.scene['number']}; run {live.dir.name}")
    if a.step in ("board", "frame") and live.state["spent"] >= CAP_USD:
        raise SystemExit(f"cap reached: ${live.state['spent']:.4f}")
    if a.step == "find":
        find(live)
    elif a.step == "roles":
        roles(live)
    elif a.step == "board":
        board(live)
    elif a.step == "look":
        bul.look(live)
    elif a.step == "approve":
        bul.approve(live)
    else:
        if a.shot is None:
            raise SystemExit("frame needs --shot")
        bul.frame(live, a.shot)


if __name__ == "__main__":
    _ = (kit, DispatchPayload, FakeJobs)  # imported for the borrowed helpers' types
    main()
