"""Plan 2026-11-05b: Adam plans every scene the delivery can hold at once (`ADAM_WORKERS`), a rolling pool writes each
scene as it finishes, and a continued delivery keeps the request's choices.

A fake `Planner` stands in for the model and the write step is faked, so these tests are about WHEN scenes are planned
and written, not about what a plan is (the other tests in this folder cover that).
"""
from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from tests.adam.test_system import World

from hiru_ai.core import llm
from hiru_ai.core.fakes import FakeScenes
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.adam.adam_shot_planner import graph
from hiru_ai.systems.adam.adam_shot_planner import scene as adam

WAIT_S = 10.0  # what a test waits for something that should already have happened


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def crowd(n: int) -> tuple[World, list[str]]:
    """A production with `n` copies of the gold scene, headed "Scene 1" … "Scene n", and their ids in order."""
    world = World()
    base, base_lines = world.scene, world.scenes.line_rows
    scenes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for i in range(n):
        sid, ids = str(uuid4()), {v: str(uuid4()) for v in world.line_ids.values()}
        script = [{**b, "line_id": ids[b["line_id"]]} if b.get("line_id") else b for b in base["script"]]
        scenes.append({**base, "id": sid, "number": i + 1, "heading": f"Scene {i + 1}", "script": script})
        lines += [{**ln, "id": ids[ln["id"]], "scene_id": sid} for ln in base_lines]
    world.scenes = FakeScenes(production={"id": world.production, "settings": {}}, scenes=scenes, lines=lines)
    world.split.scene_rows = scenes
    return world, [s["id"] for s in scenes]


class Stage:
    """What the fakes record, and what a test lets each scene do."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []  # ("start" | "end" | "written", heading), in the order they happened
        self.work: dict[str, Callable[[], None]] = {}  # heading -> run inside the worker, between start and end
        self.planned: list[str] = []

    def kinds(self, kind: str) -> list[str]:
        return [h for k, h in list(self.log) if k == kind]


def staged(monkeypatch: pytest.MonkeyPatch, workers: int) -> Stage:
    """Fake the planner and the write step; `workers` is `ADAM_WORKERS`."""
    monkeypatch.setenv("ADAM_WORKERS", str(workers))
    get_settings.cache_clear()
    stage = Stage()

    class FakePlanner:
        def __init__(self, ctx: Any, script: Any, **kw: Any) -> None:
            self.heading = str(kw["context"]["heading"])

        def input_hash(self, mode: str) -> str:
            return "unused: no scene here has a stored plan"

        def plan(self, **kw: Any) -> adam.Planned:
            stage.log.append(("start", self.heading))
            stage.planned.append(self.heading)
            if self.heading in stage.work:
                stage.work[self.heading]()
            stage.log.append(("end", self.heading))
            stored = SimpleNamespace(data=lambda: {"heading": self.heading}, report={})
            return adam.Planned(stored=cast(Any, stored), fit={"runtime_s": 10, "issues": []})

        plan_take = plan

    class FakeWrite:
        def run(self, inp: dict[str, Any]) -> dict[str, Any]:
            stage.log.append(("written", str(inp["stored"]["heading"])))
            return {"shots": [{"id": str(uuid4()), "scene_id": inp["scene"]["id"], "number": 1}], "lines": [],
                    "fields": {}}

    monkeypatch.setattr(graph.adam, "Planner", FakePlanner)
    real = graph.parts.step
    monkeypatch.setattr(graph.parts, "step",
                        lambda ident, kind: FakeWrite() if ident == "adam_write" else real(ident, kind))
    return stage


def deliver(world: World, ids: list[str], *, budget_s: float | None = None, **state: Any) -> dict[str, Any]:
    with llm.use_models(lambda tier: cast(Any, None)):  # "a model exists"; the fake planner never calls it
        return graph.run(world.payload(scene_ids=ids, **state), world.ctx(), budget_s=budget_s)


def test_every_scene_the_delivery_holds_starts_before_any_finishes(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(9)
    stage = staged(monkeypatch, workers=10)
    barrier = threading.Barrier(9, timeout=WAIT_S)  # opens only if all nine are being planned at the same time
    for n in range(1, 10):
        stage.work[f"Scene {n}"] = barrier.wait
    out = deliver(world, ids)
    assert out == {"scenes": 9, "skipped": 0, "shots": 9, "failed": 0} and not world.jobs.advanced
    assert [k for k, _ in stage.log[:9]] == ["start"] * 9  # nine seats, nine starts before the first end


def test_the_pool_is_no_larger_than_adam_workers(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(6)
    stage = staged(monkeypatch, workers=2)
    running = peak = 0
    lock = threading.Lock()

    def seat() -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    for n in range(1, 7):
        stage.work[f"Scene {n}"] = seat
    assert deliver(world, ids)["scenes"] == 6 and peak == 2


def test_a_slow_scene_holds_back_nothing_the_others_are_written_as_they_finish(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(6)
    stage = staged(monkeypatch, workers=2)
    seen: list[int] = []

    def slow() -> None:
        # in waves of two the other seat's scene could not be written until this one ended, so this would time out
        deadline = time.monotonic() + WAIT_S
        while len(stage.kinds("written")) < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        seen.append(len(stage.kinds("written")))

    stage.work["Scene 1"] = slow
    out = deliver(world, ids)
    assert seen == [5] and out["scenes"] == 6
    assert stage.kinds("written")[-1] == "Scene 1"  # the slow one is written last, not first


def test_past_the_cut_off_no_scene_starts_and_the_rest_are_handed_on_in_order_none_lost_none_twice(
        monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(6)
    stage = staged(monkeypatch, workers=2)
    for n in (1, 2):
        stage.work[f"Scene {n}"] = lambda: time.sleep(0.6)  # still running when the 0.3 s budget is spent
    out = deliver(world, ids, budget_s=0.3)
    assert sorted(stage.planned) == ["Scene 1", "Scene 2"] and sorted(stage.kinds("written")) == ["Scene 1", "Scene 2"]
    assert out["scenes"] == 2 and out["continued"] == 4
    assert world.jobs.advanced[0]["state"]["scene_ids"] == ids[2:]  # in order, the first two are not among them


def test_the_first_scene_always_starts_even_with_no_time_left(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(4)
    stage = staged(monkeypatch, workers=3)
    out = deliver(world, ids, budget_s=0.0)
    assert stage.planned == ["Scene 1"] and out["scenes"] == 1 and out["continued"] == 3
    assert world.jobs.advanced[0]["state"]["scene_ids"] == ids[1:]


def test_one_scene_that_cannot_be_planned_is_recorded_and_the_others_are_still_written(
        monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(4)
    stage = staged(monkeypatch, workers=4)

    def refuse() -> None:
        raise adam.Failed("adam_director could not answer.")

    stage.work["Scene 2"] = refuse
    out = deliver(world, ids)
    assert out["scenes"] == 3 and out["failed"] == 1
    assert sorted(stage.kinds("written")) == ["Scene 1", "Scene 3", "Scene 4"]
    assert any("Scene 2" in t and "adam_director" in t for t in world.jobs.texts("warning"))


def test_a_continued_delivery_keeps_the_mode_the_replan_and_the_screening_it_was_asked_for(
        monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(3)
    staged(monkeypatch, workers=2)
    out = deliver(world, ids, budget_s=0.0, mode="take", replan=True, screening=False)
    nxt = world.jobs.advanced[0]["state"]
    assert out["continued"] == 2 and nxt["scene_ids"] == ids[1:]
    assert (nxt["mode"], nxt["replan"], nxt["screening"]) == ("take", True, False)


def test_a_continued_delivery_of_a_plain_request_carries_the_defaults(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(2)
    staged(monkeypatch, workers=2)
    monkeypatch.setenv("ADAM_MODE", "staged")  # the setting, whatever the developer's .env says
    get_settings.cache_clear()
    deliver(world, ids, budget_s=0.0)
    nxt = world.jobs.advanced[0]["state"]
    assert (nxt["mode"], nxt["replan"], nxt["screening"]) == ("staged", False, True)


def test_each_worker_has_a_context_of_its_own_and_the_main_thread_keeps_its_value(monkeypatch: pytest.MonkeyPatch):
    world, ids = crowd(4)
    stage = staged(monkeypatch, workers=4)
    job = contextvars.ContextVar("job", default="none")
    seen: dict[str, tuple[str, str]] = {}
    barrier = threading.Barrier(4, timeout=WAIT_S)

    def mark(heading: str) -> Callable[[], None]:
        def work() -> None:
            before = job.get()  # copied from the main thread when the task was submitted
            job.set(heading)
            barrier.wait()  # all four have set theirs; none may see another's
            seen[heading] = (before, job.get())
        return work

    for n in range(1, 5):
        stage.work[f"Scene {n}"] = mark(f"Scene {n}")
    job.set("main")
    assert deliver(world, ids)["scenes"] == 4 and job.get() == "main"
    assert seen == {f"Scene {n}": ("main", f"Scene {n}") for n in range(1, 5)}
