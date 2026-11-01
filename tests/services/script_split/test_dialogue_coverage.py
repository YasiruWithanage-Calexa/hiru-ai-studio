"""The three-episode Kasun / Anudi script, end to end: structure build → shot split.

PLAN 2026-10-31 §1: every line was bound, but silent shots filled half of each episode, five
scenes ran over their envelope and the father's phone call sat on a shot of Anudi. Here the same
script goes through the build and the split with fake models, in rules mode and in model mode."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "structure_build"))

import pytest  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from script_split.engine import pipeline, planner  # noqa: E402
from structure_build.engine import pipeline as build  # noqa: E402

from contracts.shotplan import Item, ProposedShot, fit  # noqa: E402
from tests.services.fakes import FakeJobs, FakeLLM  # noqa: E402
from tests.services.script_split.test_split import FakeStore, payload  # noqa: E402
from tests.services.structure_build.test_prose import DRAMA, good_cut  # noqa: E402
from tests.services.structure_build.test_structure_build import FakeStore as BuildStore  # noqa: E402
from tests.services.structure_build.test_structure_build import build_payload, doc  # noqa: E402

EPISODE_S = 60
ONE_SHOT_S = 4


def phone_call_cut(system: str, user: str) -> dict[str, Any]:
    """Episode 1 cut by a faithful prose model, which marks the father as heard on the phone."""
    cut = good_cut(system, user)
    for scene in cut["scenes"]:
        for block in scene["blocks"]:
            if block["speaker"] == "Anudi's Father":
                block["delivery"] = "on the phone"
    return cut


def built_script() -> BuildStore:
    store = BuildStore([doc("pack.pdf", "bible", DRAMA)])
    build.run(build_payload(uuid4()), store, FakeJobs(status="running", cursor=1),
              FakeLLM({"prose_scenes": phone_call_cut}, enabled=True), InMemorySaver(), durable=False)
    return store


class SplitStore(FakeStore):
    def __init__(self, built: BuildStore) -> None:
        super().__init__([(s, built.line_rows[sid]) for sid, s in built.scene_rows.items()])
        self._episodes = [{"id": e["id"], "number": e["number"], "status": e.get("status", "")}
                          for e in built.episode_rows.values()]

    def episodes(self, production_id: Any) -> list[dict[str, Any]]:
        return self._episodes


def speech_first_plan(system: str, user: str) -> dict[str, Any]:
    """A model that follows the planner rules: each line in a shot on its speaker, an action rides
    with the line it introduces, a trailing action with the last line."""
    kinds = [(int(m[1]), m[2]) for m in re.finditer(r"^\[(\d+)\] (\w+)", user, re.M)]
    shots: list[list[int]] = []
    start = 0
    for index, kind in kinds:
        if kind == "DIALOGUE":
            shots.append([start, index + 1])
            start = index + 1
    if shots and start < len(kinds):
        shots[-1][1] = len(kinds)
    elif not shots:
        shots = [[0, len(kinds)]]
    return {"shots": [{"start": a, "end": b, "framing": "MCU", "title": f"shot {n}", "sound_mode": "dialogue",
                       "duration": 4, "camera_link": "cut"} for n, (a, b) in enumerate(shots, start=1)]}


def split(built: BuildStore, llm: FakeLLM) -> SplitStore:
    store = SplitStore(built)
    pipeline.run(payload({"build": True}), store, FakeJobs(), llm)
    return store


MODES = {
    "rules": lambda: FakeLLM(enabled=False),
    "model": lambda: FakeLLM({"shot_plan": speech_first_plan,
                              "shot_review": lambda s, u: {"acceptable": True, "notes": []}}),
}


@pytest.mark.parametrize("mode", MODES)
def test_every_line_is_bound_and_the_phone_call_is_heard_not_seen(mode: str):
    built = built_script()
    before = {ln["id"]: (ln["text"], ln["delivery"]) for ls in built.line_rows.values() for ln in ls}
    store = split(built, MODES[mode]())
    lines = [ln for ls in store.line_rows.values() for ln in ls]
    assert len(lines) == 24 and all(ln["shot_id"] for ln in lines)  # 24 of 24 bound
    assert {ln["id"]: (ln["text"], ln["delivery"]) for ln in lines} == before  # verbatim

    reports = [s["fit_report"] for s in store.scene_rows.values()]
    assert not [i for r in reports for i in r["issues"] if i["code"] == "multi_speaker"]
    assert all(r["multi_speaker"] == [] for r in reports)

    shot_by_id = {sh["id"]: sh for shots in store.shots.values() for sh in shots}
    [call] = [ln for ln in lines if ln["delivery"] == "on the phone"]
    assert shot_by_id[call["shot_id"]]["sound_mode"] == "voiceover"
    assert any(r["voiceover"] for r in reports)


@pytest.mark.parametrize("mode", MODES)
def test_an_episode_that_needs_more_than_its_minute_says_so_and_nothing_is_squeezed(mode: str):
    """plan/2026-11-01b R6: pictures are never folded away to hit the target; the build reports the
    seconds the script needs and the director decides."""
    built = built_script()
    jobs = FakeJobs()
    store = SplitStore(built)
    pipeline.run(payload({"build": True}), store, jobs, MODES[mode]())
    number = {e["id"]: e["number"] for e in built.episode_rows.values()}
    need: dict[int, int] = {}
    shots: dict[int, int] = {}
    for scene_id, scene in store.scene_rows.items():
        ep = number[scene["episode_id"]]
        need[ep] = need.get(ep, 0) + scene["fit_report"]["need_s"]
        shots[ep] = shots.get(ep, 0) + sum(s["duration_s"] for s in store.shots[scene_id])
    for ep, line in zip((1, 2, 3), jobs.texts("agent_step"), strict=True):
        assert need[ep] >= shots[ep] and not scene_has_crowding(store, number, ep)
        if need[ep] > EPISODE_S:
            assert f"needs {need[ep]} s to show its script; target {EPISODE_S} s" in line, line


def scene_has_crowding(store: SplitStore, number: dict[str, int], ep: int) -> bool:
    return any(s["fit_report"]["crowded"] for sid, s in store.scene_rows.items() if number[s["episode_id"]] == ep)


def test_a_build_says_per_episode_how_it_went():
    store = SplitStore(built_script())
    jobs = FakeJobs()
    pipeline.run(payload({"build": True}), store, jobs, FakeLLM(enabled=False))
    steps = jobs.texts("agent_step")
    assert [s.split(":")[0] for s in steps] == ["Episode 1", "Episode 2", "Episode 3"]
    assert "1 line off screen" in steps[0] and all(" s spoken" in s for s in steps)


# ── folding silent shots when the rules plan runs over ─────────────────────────────────────

def silent_scene() -> list[Item]:
    def say(i: int, who: str, words: int) -> Item:
        return Item(i, "dialogue", " ".join(["w"] * words), who, who, "", f"l{i}")

    def act(i: int) -> Item:
        return Item(i, "action", " ".join(["a"] * 40))

    return [act(0), say(1, "kasun", 6), act(2), say(3, "anudi", 6), act(4)]


def test_rules_give_up_silent_shots_only_while_over_the_envelope():
    items = silent_scene()
    roomy = fit(items, planner.plan_by_rules(items, envelope_s=60), envelope_s=60)
    assert roomy.silent_s > 0  # nothing is folded while there is room

    tight = fit(items, planner.plan_by_rules(items, envelope_s=12), envelope_s=12)
    assert tight.total_s <= 12 and tight.silent_s == 0
    assert [ln.line_id for ln in tight.lines] == ["l1", "l3"]  # every line kept, in order
    assert not [i for i in tight.issues if i.code in ("line_overrun", "repaired")]


def test_folding_stops_when_only_speech_is_left():
    items = silent_scene()
    shots = planner.plan_by_rules(items, envelope_s=1)  # impossible: speech alone is 8 s
    assert all(any(i.is_line for i in items[p.start:p.end]) for p in shots)
    # speech alone is 8 s, but each action now rides with a line and takes its picture time: 6 s + 6 s
    assert fit(items, shots, envelope_s=1).total_s == 12


def test_a_scene_inside_its_envelope_is_planned_exactly_as_before():
    items = silent_scene()
    assert planner.plan_by_rules(items, envelope_s=600) == planner.plan_by_rules(items)
    assert planner.fold_silent(items, [ProposedShot(0, 5)], envelope_s=1) == [ProposedShot(0, 5)]
