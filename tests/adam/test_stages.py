"""Phase 3 and 4 exit checks (plan/2026-11-04b §10) that code can make, on the gold set.

The six agents are run for real (their prompts, their user messages, their strict wire shapes, their `finish` hooks)
against a SCRIPTED model whose answers are the masters', each stage fed what the stage before it actually returned.
That proves the wiring: what the agents hand each other is enough to rebuild the master, every stage passes the code
rules it must pass, and nothing is lost between a wire shape and the plan.

It does NOT prove a model can do it. The exits that need a person ("a Hiru director judges at least 4 of 5 treatments a
real director's idea", "the test scene's cards read like section 9 to the person") and every live run wait for one
(`hiru-ai eval <agent> --live`, plan/2026-11-04b IMPLEMENTED.md).
"""
from __future__ import annotations

from typing import Any

import pytest
import yaml
from tests.adam import gold, stages

from contracts.adam import wire as w
from contracts.adam.plan import AdamPlan, Treatment
from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.testing import ScriptedChatModel

NAMES = gold.names()


def ask(agent_id: str, inp: dict[str, Any], reply: dict[str, Any], *, strict: bool = True) -> Any:
    """Run the real agent against a scripted model; the agent's `Output`, after its `finish` hook."""
    agent = agents.build(agent_id)
    model = ScriptedChatModel(replies=[reply])
    with llm.use_models(model):
        out = agent.run(agent.input_cls.model_validate(inp), RunContext(strict=strict))
    system, user = agent.messages(agent.input_cls.model_validate(inp))
    assert model.calls[0][0].content == system and model.calls[0][1].content == user
    return out


def step(step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", step_id, "step").run(payload))


def dump(model: Any) -> Any:
    return stages._dump(model)


def without_words(t: Treatment) -> Treatment:
    """A treatment with the director's WORDS for the plant and the break cleared: the master never had them."""
    plant = t.plant.model_copy(update={"plant_when": "", "payoff_when": ""}) if t.plant else None
    brk = t.rhythm_break.model_copy(update={"when": ""}) if t.rhythm_break else None
    return t.model_copy(update={"plant": plant, "rhythm_break": brk, "stance": ""})


@pytest.mark.parametrize("name", NAMES)
def test_the_six_agents_in_order_rebuild_the_master_and_pass_every_code_rule(name: str):
    master = stages.master_with_stance(name)
    scene = gold.scene(name)
    strict = name != stages.EXAMPLE_SCENE  # that scene IS the prompt's worked example: `static_first` rightly objects

    # ① analyse
    out = ask("adam_dramaturg", stages.inputs("adam_dramaturg", name), stages.replies("adam_dramaturg", name),
              strict=strict)
    analysis = out.analysis()
    expect_analysis, expect_treatment = stages.unbound(master)
    assert analysis == expect_analysis

    # ② conceive: three treatments that differ on purpose
    out = ask("adam_director", {"scene": scene, "analysis": dump(analysis)}, stages.replies("adam_director", name),
              strict=strict)
    treatments = out.all()
    assert [t.stance for t in treatments] == list(w.STANCES)
    distinct = step("adam_distinct", {"treatments": [dump(t) for t in treatments]})
    assert distinct["ok"], distinct["issues"]
    chosen = next(t for t in treatments if t.stance == stages.stance_of(name))
    assert chosen == expect_treatment

    # ③ imagine: the moments pass fidelity and bind the ids the director could only describe
    out = ask("adam_moment_writer", {"scene": scene, "analysis": dump(analysis), "treatment": dump(chosen)},
              stages.replies("adam_moment_writer", name), strict=strict)
    moments = out.moment_list()
    assert moments == master.moments
    fidelity = step("adam_fidelity", {"scene": scene, "moments": dump(moments)})
    assert fidelity["ok"], fidelity["breaks"]
    analysis, bound = out.bind(analysis, chosen)
    assert analysis == master.analysis and without_words(bound) == without_words(master.treatment)

    # ④ stage
    out = ask("adam_blocker", {"scene": scene, "analysis": dump(analysis), "treatment": dump(bound),
                               "moments": dump(moments)}, stages.replies("adam_blocker", name), strict=strict)
    staging = out.staging()
    assert staging == master.staging

    # ⑤ design: the cards use every script moment once and bind every line, fit the clock and the continuity rules
    out = ask("adam_shot_designer", {"scene": scene, "analysis": dump(analysis), "treatment": dump(bound),
                                     "moments": dump(moments), "staging": dump(staging)},
              stages.replies("adam_shot_designer", name), strict=strict)
    cards = out.card_list()
    assert cards == master.cards
    plan = {"analysis": dump(analysis), "treatment": dump(bound), "moments": dump(moments),
            "staging": dump(staging), "cards": dump(cards)}
    assert step("adam_fidelity", {"scene": scene, "plan": plan})["ok"]
    fit = step("adam_fit", {"scene": scene, "plan": plan})
    assert fit["ok"] and fit["overruns"] == 0, fit["issues"]
    assert step("adam_continuity", {"scene": scene, "plan": plan})["ok"]
    assert step("adam_feasibility", {"scene": scene, "plan": plan})["ok"]

    # ⑥ sound: the cards keep their picture and gain their sound; the whole plan scores as the master does
    out = ask("adam_sound_designer", {"scene": scene, "treatment": dump(bound), "moments": dump(moments),
                                      "cards": dump(cards)}, stages.replies("adam_sound_designer", name),
              strict=strict)
    final = AdamPlan(analysis=analysis, treatment=bound, moments=moments, staging=staging,
                     cards=out.apply(cards), sound_map=out.sound_map())
    assert final.cards == master.cards and final.sound_map == master.sound_map
    score = step("adam_score", {"scene": scene, "plan": dump(final)})
    assert not score["loss"] and score["percent"] == 100.0, score["loss_reasons"]


@pytest.mark.parametrize("name", NAMES)
def test_the_three_treatments_of_every_gold_scene_differ_on_purpose(name: str):
    treatments = [dump(t) for t in stages.director_wire(name).all()]
    out = step("adam_distinct", {"treatments": treatments})
    assert out["ok"], out["issues"]
    assert all(len(p["differs"]) >= 2 for p in out["pairs"])


def test_three_copies_of_one_treatment_are_refused():
    one = dump(stages.director_wire("phone_call").all()[0])
    out = step("adam_distinct", {"treatments": [{**one, "name": f"copy {n}", "stance": s}
                                                for n, s in enumerate(w.STANCES)]})
    assert not out["ok"] and {i["code"] for i in out["issues"]} == {"alike"}


# ── the wire shapes lose nothing ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", NAMES)
def test_every_wire_shape_round_trips_the_master(name: str):
    p = stages.master_with_stance(name)
    assert stages.analysis_wire(p.analysis).analysis() == stages.unbound(p)[0]
    assert stages.moments_wire(p).moment_list() == p.moments
    assert stages.staging_wire(p).staging() == p.staging
    assert stages.cards_wire(p).card_list() == p.cards
    sound = stages.sound_wire(p)
    assert sound.sound_map() == p.sound_map and sound.apply(p.cards) == p.cards


def test_a_wire_shape_has_no_defaulted_field_and_refuses_an_extra_one():
    """OpenAI strict mode needs every property required; the generic agent contract test checks it on the wire, this
    checks it on the source: no wire class declares a default."""
    for cls in vars(w).values():
        if isinstance(cls, type) and issubclass(cls, w._Wire) and cls is not w._Wire:
            assert all(f.is_required() for f in cls.model_fields.values()), cls.__name__
    with pytest.raises(ValueError):
        w.PovW.model_validate({"start": "a", "end": "b", "why": "c", "extra": 1})


# ── the prompts' worked examples and the eval cases are generated, never hand-copied ─────────────


@pytest.mark.parametrize("agent", stages.AGENTS)
def test_a_prompts_worked_example_is_the_current_gold_scene(agent: str):
    text = stages.prompt_path(agent).read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert stages.with_example(text, stages.example(agent)) == text, (
        "regenerate: python -c \"from tests.adam.stages import write_all; write_all()\"")


@pytest.mark.parametrize("agent", stages.AGENTS)
def test_the_eval_cases_are_the_current_gold_set_without_the_prompts_own_example(agent: str):
    path = stages.AGENT_DIR / agent / "evals" / "cases.yaml"
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert body == yaml.safe_load(yaml.safe_dump(stages.cases(agent), allow_unicode=True, sort_keys=False))
    scenes = [c["name"] for c in body if "reply" in c]
    assert scenes == [n for n in NAMES if n != stages.EXAMPLE_SCENE] and len(scenes) >= 4
    assert not any(c.get("model") == "unavailable" for c in body)  # no fallback: the contract test says it raises


def test_the_example_scene_is_a_real_master_and_is_the_only_one_without_a_case():
    assert AdamPlan.model_validate(gold.master(stages.EXAMPLE_SCENE))
    assert stages.EXAMPLE_SCENE in NAMES and stages.EXAMPLE_SCENE not in stages.case_scenes()
