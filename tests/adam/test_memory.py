"""plan/2026-11-05d: Shot Planner Adam's agents and the production memory.

The generic behaviour (topics, scope, cap, byte-identity) is held in `tests/hiru_ai/test_production_memory.py` against
any agent; what is Adam's is here, so removing the group removes these with it.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import yaml

from hiru_ai.core import agents, middleware
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeMemory
from hiru_ai.core.middleware.base import ModelCall
from hiru_ai.core.registry import default

REGISTRY = default()
PID = uuid4()


def case_input(ident: str) -> dict[str, Any]:
    comp = REGISTRY.get("agent", ident)
    out: list[dict[str, Any]] = []
    for path in sorted((comp.folder / "evals").glob("*.yaml")):
        out += yaml.safe_load(path.read_text(encoding="utf-8"))
    return next(c["input"] for c in out if c.get("variant") in (None, "base"))


def row(topic: str, says: str, applies_to: str = "production", strength: str = "prefer") -> dict[str, Any]:
    return {"id": f"{topic}-{says[:8]}", "production_id": str(PID), "document_id": None, "topic": topic,
            "applies_to": applies_to, "says": says, "quote": "", "strength": strength, "status": "approved",
            "source": "reader"}


def sent(ident: str, inp: dict[str, Any], rows: list[dict[str, Any]]) -> ModelCall:
    agent = agents.build(ident)
    seen: list[ModelCall] = []
    chain = middleware.build(agent.manifest.middleware, writes_dialogue=agent.manifest.writes_dialogue)
    ctx = RunContext(production_id=PID, ports=Ports(memory=FakeMemory(rows)))
    middleware.run_chain(chain, agent.prepare(inp), ctx, lambda c: seen.append(c) or "answered")
    return seen[0]


def test_the_adam_agents_are_subscribed_to_the_topics_the_plan_gives():
    topics = {i: REGISTRY.get("agent", i).manifest.memory for i in REGISTRY.ids("agent")}  # type: ignore[union-attr]
    assert topics["adam_dramaturg"] == ["series", "tone", "performance"]
    assert topics["adam_director"] == topics["adam_moment_writer"] == ["tone", "visual", "camera", "edit"]
    assert topics["adam_shot_designer"] == topics["adam_take"] == ["visual", "camera", "lighting"]
    assert topics["adam_sound_designer"] == ["sound", "music"]
    # the critic reads everything, because it also reports a `must` entry the plan breaks; the one-call critic of
    # plan/2026-11-05 (ADAM_MODE=take) does the same in its fidelity lens
    assert topics["adam_critic_fidelity"] == topics["adam_critic"] == ["*"]
    for ident in ("adam_critic_fidelity", "adam_critic"):
        prompt = (REGISTRY.get("agent", ident).folder / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "<production_memory>" in prompt and "`must` entry the plan breaks" in prompt


def test_the_three_scene_agents_say_what_the_call_is_about():
    base = case_input("adam_director")
    base["episode"] = 3
    maker = agents.build("adam_director")
    director = maker.hooks.memory_scope(maker.input_cls.model_validate(base))
    assert director == {"place": base["scene"]["place"]["name"], "people": base["scene"]["cast"], "episode": 3}
    shots = case_input("adam_shot_designer")
    shots["episode"] = 3
    designer = agents.build("adam_shot_designer")
    assert designer.hooks.memory_scope(designer.input_cls.model_validate(shots))["episode"] == 3
    dramaturg = case_input("adam_dramaturg")
    dramaturg.setdefault("context", {})["episode"] = 3
    reader = agents.build("adam_dramaturg")
    assert reader.hooks.memory_scope(reader.input_cls.model_validate(dramaturg))["episode"] == 3
    assert reader.hooks.memory_scope(reader.input_cls.model_validate(case_input("adam_dramaturg")))["episode"] is None


def test_a_place_entry_reaches_the_director_only_for_a_scene_at_that_place():
    rows = [row("visual", "Cold blue and sodium orange.", "place:Colombo"),
            row("visual", "Warm amber and earthy red.", "place:Mahawewa village")]
    inp = case_input("adam_director")
    inp["scene"]["place"] = {"name": "Colombo harbour, night", "objects": []}
    colombo = sent("adam_director", inp, rows).user
    inp["scene"]["place"] = {"name": "Mahawewa village", "objects": []}
    village = sent("adam_director", inp, rows).user
    assert "Cold blue" in colombo and "Warm amber" not in colombo
    assert "Warm amber" in village and "Cold blue" not in village


def test_an_episode_entry_reaches_the_shot_designer_only_for_that_episode():
    rows = [row("visual", "Shot entirely in the rain.", "episode:2")]
    inp = case_input("adam_shot_designer")
    inp["episode"] = 2
    assert "entirely in the rain" in sent("adam_shot_designer", inp, rows).user
    inp["episode"] = 1
    assert "entirely in the rain" not in sent("adam_shot_designer", inp, rows).user


def test_the_system_hands_the_episode_number_to_the_agents():
    from hiru_ai.systems.adam.adam_shot_planner import scene

    context = scene.context_of({"heading": "INT. HOUSE"}, {"number": 2, "title": "Home", "synopsis": ""}, "", "", [])
    assert context["episode"] == 2
