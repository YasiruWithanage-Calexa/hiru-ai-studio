"""Stuck work ends (plan/2026-11-08c phase 5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from api.workers.sweeper import sweep
from tests.api.fakes import FakeDocuments, FakeFrames, FakeJobs, FakeRenders, FakeSceneBoards

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


class _Repos:
    def __init__(self) -> None:
        self.jobs, self.frames, self.renders, self.documents = FakeJobs(), FakeFrames(), FakeRenders(), FakeDocuments()
        self.scene_boards = FakeSceneBoards()


async def _job(repos: _Repos, kind: str, minutes: float, status: str = "running") -> str:
    jid = str(uuid4())
    await repos.jobs.create({"id": jid, "kind": kind, "status": status, "production_id": str(uuid4())})
    repos.jobs.rows[jid]["updated_at"] = ago(minutes)
    return jid


async def test_old_job_without_events_fails_with_a_reason() -> None:
    repos = _Repos()
    old = await _job(repos, "shot_produce", 16)
    assert await sweep(repos, NOW) == 1  # type: ignore[arg-type]
    assert repos.jobs.rows[old]["status"] == "failed"
    assert repos.jobs.rows[old]["error"] == "Stopped: no progress for 15 minutes."


async def test_recent_event_keeps_a_job_alive() -> None:
    repos = _Repos()
    jid = await _job(repos, "shot_produce", 40)
    repos.jobs.event_rows.append({"job_id": jid, "seq": 1, "type": "x", "agent": None, "payload": {},
                                  "created_at": ago(2)})
    assert await sweep(repos, NOW) == 0  # type: ignore[arg-type]
    assert repos.jobs.rows[jid]["status"] == "running"


async def test_limits_differ_by_kind_and_waiting_input_is_never_swept() -> None:
    repos = _Repos()
    frame_job = await _job(repos, "frame_render", 11)
    video_job = await _job(repos, "video_render", 11)  # a take may take 30 minutes
    waiting = await _job(repos, "shot_produce", 600, status="waiting_input")
    await sweep(repos, NOW)  # type: ignore[arg-type]
    assert repos.jobs.rows[frame_job]["status"] == "failed"
    assert repos.jobs.rows[frame_job]["error"].endswith("10 minutes.")
    assert repos.jobs.rows[video_job]["status"] == "running"
    assert repos.jobs.rows[waiting]["status"] == "waiting_input"


async def test_frames_renders_and_documents_of_a_dead_worker_end() -> None:
    repos = _Repos()
    job = await _job(repos, "video_render", 31)
    pid = str(uuid4())
    await repos.frames.create_many([
        {"id": "f-old", "production_id": pid, "shot_id": "s", "status": "running", "job_id": None},
        {"id": "f-new", "production_id": pid, "shot_id": "s", "status": "running", "job_id": None},
    ])
    repos.frames.rows["f-old"]["updated_at"] = ago(11)
    await repos.renders.create_many([{"id": "r1", "production_id": pid, "shot_id": "s", "job_id": job},
                                     {"id": "r2", "production_id": pid, "shot_id": "s", "job_id": None}])
    repos.renders.rows["r1"]["updated_at"] = ago(31)
    repos.renders.rows["r2"]["updated_at"] = ago(5)
    await repos.documents.create({"id": "d1", "production_id": pid, "status": "processing"})
    repos.documents.rows["d1"]["updated_at"] = ago(21)
    await sweep(repos, NOW)  # type: ignore[arg-type]
    assert repos.frames.rows["f-old"]["status"] == "failed"
    assert repos.frames.rows["f-new"]["status"] == "running"
    assert repos.renders.rows["r1"]["status"] == "failed"
    assert repos.renders.rows["r2"]["status"] == "queued"
    assert repos.documents.rows["d1"]["status"] == "failed"
    assert repos.documents.rows["d1"]["error"] == "Stopped: no progress for 20 minutes."

async def test_a_board_part_left_running_by_a_crash_ends() -> None:
    """2026-11-16: part 1 crashed after its paint; part 2 stayed `running` and the board could not be painted again."""
    repos = _Repos()
    base = {"production_id": "p", "scene_id": "s", "version": 1, "parts": 2}
    await repos.scene_boards.create({**base, "id": "b1", "part": 1, "status": "failed"})
    await repos.scene_boards.create({**base, "id": "b2", "part": 2, "status": "running"})
    await repos.scene_boards.create({**base, "id": "b3", "version": 2, "part": 1, "status": "running"})
    repos.scene_boards.rows["b2"]["updated_at"] = ago(16)
    repos.scene_boards.rows["b3"]["updated_at"] = ago(3)
    assert await sweep(repos, NOW) == 1  # type: ignore[arg-type]
    assert repos.scene_boards.rows["b2"]["status"] == "failed"
    assert repos.scene_boards.rows["b2"]["error"] == "Stopped: no progress for 15 minutes."
    assert repos.scene_boards.rows["b3"]["status"] == "running"


async def test_a_queued_frame_waiting_on_a_live_job_is_kept() -> None:
    """2026-11-25: a bulk job wrote 14 shot prompts for 9.5 min, then painted 4 at a time; the 10 frames still waiting
    their turn were stopped although the job was sending progress. A queued frame is judged by its job."""
    repos = _Repos()
    live = await _job(repos, "frame_render", 12)
    repos.jobs.event_rows.append({"job_id": live, "seq": 1, "type": "progress", "agent": None, "payload": {},
                                  "created_at": ago(1)})
    finished = await _job(repos, "frame_render", 12, status="done")
    pid = str(uuid4())
    await repos.frames.create_many([
        {"id": "waiting", "production_id": pid, "shot_id": "s", "status": "queued", "job_id": live},
        {"id": "painting", "production_id": pid, "shot_id": "s", "status": "running", "job_id": live},
        {"id": "orphan", "production_id": pid, "shot_id": "s", "status": "queued", "job_id": finished},
        {"id": "no-job", "production_id": pid, "shot_id": "s", "status": "queued", "job_id": None},
    ])
    for fid in ("waiting", "painting", "orphan", "no-job"):
        repos.frames.rows[fid]["updated_at"] = ago(11)
    await sweep(repos, NOW)  # type: ignore[arg-type]
    assert repos.jobs.rows[live]["status"] == "running"
    assert repos.frames.rows["waiting"]["status"] == "queued"
    assert repos.frames.rows["painting"]["status"] == "failed"  # a claimed frame keeps its own clock
    assert repos.frames.rows["orphan"]["status"] == "failed"
    assert repos.frames.rows["no-job"]["status"] == "failed"


async def test_queued_frames_end_with_their_job_once_it_goes_quiet() -> None:
    repos = _Repos()
    quiet = await _job(repos, "frame_render", 11)
    await repos.frames.create_many([{"id": "f", "production_id": "p", "shot_id": "s", "status": "queued",
                                     "job_id": quiet}])
    repos.frames.rows["f"]["updated_at"] = ago(30)
    await sweep(repos, NOW)  # type: ignore[arg-type]
    assert repos.jobs.rows[quiet]["status"] == "failed"
    assert repos.frames.rows["f"]["status"] == "failed"
    assert repos.frames.rows["f"]["error"] == "Stopped: no progress for 10 minutes."
