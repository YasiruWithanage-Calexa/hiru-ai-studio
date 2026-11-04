"""The gold set seen through the six agents of Phases 3 and 4 (plan/2026-11-04b §10).

A gold master is the whole plan. This module cuts it into what each agent is GIVEN (`inputs`) and what a good agent
would ANSWER (`replies`, in the agent's wire shape), so that:

* the agents' eval cases are generated from the masters, never hand-copied (`write_cases`);
* the worked example in each system prompt is one gold scene, shown exactly as the agent will see a scene
  (`write_examples`; `tests/adam/test_stages.py` fails when a prompt's example is out of date);
* a test can run the real agents, with scripted replies, from the first stage to the last and check the result is
  the master (`tests/adam/test_stages.py`).

The prompts' worked example is `EXAMPLE_SCENE`. Few-shot examples come from the gold set and never from the scene being
planned: when `EXAMPLE_SCENE` itself is planned, the model has seen its answer, so a live eval of that scene proves
nothing (its eval case says so).

Regenerate after a master or a prompt changes:

    .venv\\Scripts\\python -c "from tests.adam.stages import write_all; write_all()"
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from tests.adam import gold

from contracts.adam import wire as w
from contracts.adam.plan import AdamPlan, Moment, SceneAnalysis, ShotCard, Treatment

EXAMPLE_SCENE = "refuses_money"
AGENTS = ("adam_dramaturg", "adam_director", "adam_moment_writer", "adam_blocker", "adam_shot_designer",
          "adam_sound_designer")
AGENT_DIR = Path(__file__).resolve().parents[2] / "src" / "libs" / "hiru_ai" / "agents" / "adam"
START, END = "<!-- example:start -->", "<!-- example:end -->"


def plan(name: str) -> AdamPlan:
    return AdamPlan.model_validate(gold.master(name))


def _yaml(kind: str, name: str) -> dict[str, Any]:
    data = yaml.safe_load((gold.GOLD / kind / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def title(name: str) -> str:
    return str(_yaml("scenes", name)["title"])


def _dump(value: Any) -> Any:
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value.model_dump(mode="json", by_alias=True, exclude_defaults=True)


# ── the plan, turned back into what a model writes ───────────────────────────────────────────────


def analysis_wire(a: SceneAnalysis) -> w.AnalysisWire:
    return w.AnalysisWire.model_validate({
        "about": a.about, "dramatic_question": a.dramatic_question, "value": a.value.model_dump(), "tone": a.tone,
        "beats": [b.model_dump() for b in a.beats], "wants": [{"who": k, "verb": v} for k, v in a.wants.items()],
        "obstacles": a.obstacles, "subtext": [s.model_dump() for s in a.subtext],
        "pov_owner": {"start": a.pov_owner.start, "end": a.pov_owner.end or a.pov_owner.start,
                      "why": a.pov_owner.why},
        "audience_knows": [k.model_dump() for k in a.audience_knows], "baseline": a.baseline.model_dump(),
        "break_block": a.break_.block, "aftermath": a.aftermath.state, "key_moment": a.key_moment.model_dump()})


def treatment_wire(t: Treatment, moments: list[Moment], stance: str) -> w.TreatmentW:
    """The master's treatment as the director would write it: where the plant, the break and the ending are said in
    WORDS (what the moment shows), because the moments are not written yet."""
    seen = {m.id: m.seen for m in moments}
    plant = ({"object": t.plant.object, "plant_when": t.plant.plant_when or seen.get(t.plant.plant_moment, ""),
              "payoff_when": t.plant.payoff_when or seen.get(t.plant.payoff_moment, ""),
              "payoff_scene": t.plant.payoff_scene} if t.plant else None)
    brk = ({"when": t.rhythm_break.when or seen.get(t.rhythm_break.moment, ""), "kind": t.rhythm_break.kind}
           if t.rhythm_break else None)
    return w.TreatmentW.model_validate({
        "stance": stance, "name": t.name, "concept": t.concept, "pov": t.pov, "sound_concept": t.sound_concept,
        "sections": [s.model_dump() for s in t.sections], "size_arc": t.size_arc, "motif": t.motif, "plant": plant,
        "rhythm": t.rhythm, "rhythm_break": brk, "entry": t.entry, "exit": t.exit, "ending_image": t.ending_image,
        "transition_in": t.transition_in, "transition_out": t.transition_out, "off_speaker": t.off_speaker})


def card_wire(c: ShotCard) -> w.CardW:
    return w.CardW.model_validate({
        "moments": c.moments, "title": c.title, "size": c.size, "arrangement": c.arrangement, "subject": c.subject,
        "angle": c.angle, "height": c.height, "lens_feel": c.lens_feel, "movement": c.movement,
        "focus": {"kind": c.focus.kind, "rack_from": c.focus.from_, "rack_to": c.focus.to},
        "composition": c.composition.model_dump(), "eyeline": c.eyeline, "axis": c.axis,
        "blocking_in_shot": c.blocking_in_shot, "beats": [b.model_dump() for b in c.beats],
        "lines": [ln.model_dump() for ln in c.lines], "sound": c.sound.model_dump(), "cut_in": c.cut_in.model_dump(),
        "purpose": c.purpose, "emotional_beat": c.emotional_beat, "rhythm_break": c.rhythm_break,
        "veo_notes": c.veo_notes, "take_s": c.take_s})


def stance_of(name: str) -> str:
    return str(_yaml("treatments", name)["master_stance"])


def director_wire(name: str) -> w.TreatmentsWire:
    """Three treatments in the order of the stances: the master's own, and the two drafted beside it."""
    p = plan(name)
    found = {stance_of(name): treatment_wire(p.treatment, p.moments, stance_of(name))}
    for alt in _yaml("treatments", name)["alternates"]:
        found[alt["stance"]] = w.TreatmentW.model_validate(alt)
    return w.TreatmentsWire(treatments=[found[s] for s in w.STANCES])


def unbound(p: AdamPlan) -> tuple[SceneAnalysis, Treatment]:
    """The analysis and the master's treatment as they are BEFORE the moment writer: no moment id anywhere."""
    chosen = treatment_wire(p.treatment, p.moments, stance_of_plan(p)).treatment()
    pov = p.analysis.pov_owner.model_copy(update={"handover": ""})
    return p.analysis.model_copy(update={"pov_owner": pov}), chosen


def stance_of_plan(p: AdamPlan) -> str:
    return p.treatment.stance or "restrained"


def moments_wire(p: AdamPlan) -> w.MomentsWire:
    t, a = p.treatment, p.analysis
    return w.MomentsWire.model_validate({
        "moments": [m.model_dump(mode="json") for m in p.moments],
        "bindings": {"plant": t.plant.plant_moment if t.plant else "", "payoff": t.plant.payoff_moment if t.plant
                     else "", "rhythm_break": t.rhythm_break.moment if t.rhythm_break else "",
                     "ending": t.ending_moment, "handover": a.pov_owner.handover}})


def staging_wire(p: AdamPlan) -> w.StagingWire:
    return w.StagingWire.model_validate({"marks": [m.model_dump() for m in p.staging.marks],
                                         "moves": [m.model_dump() for m in p.staging.moves]})


def cards_wire(p: AdamPlan) -> w.CardsWire:
    return w.CardsWire(cards=[card_wire(c) for c in p.cards])


def sound_wire(p: AdamPlan) -> w.SoundWire:
    sm = p.sound_map
    return w.SoundWire.model_validate({
        "sections": [s.model_dump() for s in sm.sections], "subjective": [s.model_dump() for s in sm.subjective],
        "silences": sm.silences, "pre_laps": [x.model_dump() for x in sm.pre_laps],
        "music": [m.model_dump() for m in sm.music],
        "cards": [{"number": c.number, "sound": c.sound.model_dump()} for c in p.cards]})


# ── what each agent is given, and what it would answer ───────────────────────────────────────────


def master_with_stance(name: str) -> AdamPlan:
    """The master, its treatment carrying the stance the treatments file gives it."""
    p = plan(name)
    return p.model_copy(update={"treatment": p.treatment.model_copy(update={"stance": stance_of(name)})})


def inputs(agent: str, name: str) -> dict[str, Any]:
    p = master_with_stance(name)
    scene = gold.scene(name)
    if agent == "adam_dramaturg":
        return {"scene": scene, "context": {"heading": title(name)}}
    analysis, chosen = unbound(p)
    if agent == "adam_director":
        return {"scene": scene, "analysis": _dump(analysis)}
    if agent == "adam_moment_writer":
        return {"scene": scene, "analysis": _dump(analysis), "treatment": _dump(chosen)}
    base = {"scene": scene, "analysis": _dump(p.analysis), "treatment": _dump(p.treatment)}
    if agent == "adam_blocker":
        return {**base, "moments": _dump(p.moments)}
    if agent == "adam_shot_designer":
        return {**base, "moments": _dump(p.moments), "staging": _dump(p.staging)}
    if agent == "adam_sound_designer":
        return {"scene": scene, "treatment": base["treatment"], "moments": _dump(p.moments), "cards": _dump(p.cards)}
    raise KeyError(agent)


def replies(agent: str, name: str) -> dict[str, Any]:
    p = master_with_stance(name)
    wire: BaseModel
    if agent == "adam_dramaturg":
        wire = analysis_wire(p.analysis)
    elif agent == "adam_director":
        wire = director_wire(name)
    elif agent == "adam_moment_writer":
        wire = moments_wire(p)
    elif agent == "adam_blocker":
        wire = staging_wire(p)
    elif agent == "adam_shot_designer":
        wire = cards_wire(p)
    elif agent == "adam_sound_designer":
        wire = sound_wire(p)
    else:
        raise KeyError(agent)
    return dict(wire.model_dump(mode="json"))


# What a case holds the answer to. Scripted, the answer is the case's own reply; LIVE, a creative agent's words are its
# own, so only what any good answer shares is expected: the block the scene breaks on, and the order of the stances.
def expectation(agent: str, name: str) -> dict[str, Any]:
    reply = replies(agent, name)
    if agent == "adam_dramaturg":
        return {"break_block": reply["break_block"]}
    if agent == "adam_director":
        return {"treatments": [{"stance": s} for s in w.STANCES]}
    return {}


# ── the worked example in each prompt ────────────────────────────────────────────────────────────


def hooks(agent: str) -> Any:
    return importlib.import_module(f"hiru_ai.agents.adam.{agent}.agent")


def schema(agent: str) -> Any:
    return importlib.import_module(f"hiru_ai.agents.adam.{agent}.schema")


def example(agent: str, name: str = EXAMPLE_SCENE) -> str:
    """One scene exactly as the agent sees it, then the answer the agent should give."""
    user = hooks(agent).user_message(schema(agent).Input.model_validate(inputs(agent, name)))
    answer = json.dumps(replies(agent, name), ensure_ascii=False, separators=(",", ":"))
    return f"<example>\n{user}\n\nYour answer:\n{answer}\n</example>"


def prompt_path(agent: str) -> Path:
    return AGENT_DIR / agent / "prompts" / "system.md"


def with_example(text: str, block: str) -> str:
    found = re.search(re.escape(START) + r".*?" + re.escape(END), text, re.S)
    assert found, "the prompt has no example markers"
    return text[:found.start()] + f"{START}\n{block}\n{END}" + text[found.end():]


def write_examples() -> None:
    for agent in AGENTS:
        path = prompt_path(agent)
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = with_example(raw.replace("\r\n", "\n"), example(agent))
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


# ── the eval cases ───────────────────────────────────────────────────────────────────────────────

CASE_HEADER = "\n".join([
    "# Generated by tests/adam/stages.py from the gold masters (tests/eval/adam/masters): do not edit by hand.",
    "# Scripted, each case answers with the master's own answer for that stage, so a pass says the agent builds, sends",
    "# what it should and cleans the answer as it should. LIVE (`hiru-ai eval <agent> --live`) the model answers the",
    "# INPUT and the case holds it only to what any good answer shares; whether it is GOOD is a Hiru director's",
    "# judgement (plan/2026-11-04b section 10). The scene the prompt's worked example uses has no case: the model has",
    "# seen that answer, so a live pass on it would prove nothing (and `static_first` refuses a prompt that holds its",
    "# own user message).",
    ""])


def case_scenes() -> list[str]:
    """The gold scenes with an eval case: all but the one the prompts' worked example shows."""
    return [n for n in gold.names() if n != EXAMPLE_SCENE]


def cases(agent: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"name": name, "input": inputs(agent, name), "reply": replies(agent, name),
         "expect": expectation(agent, name)} for name in case_scenes()]
    return out


def write_cases() -> None:
    for agent in AGENTS:
        body = yaml.safe_dump(cases(agent), allow_unicode=True, sort_keys=False, width=100000,
                              default_flow_style=None)
        (AGENT_DIR / agent / "evals" / "cases.yaml").write_bytes((CASE_HEADER + body).encode("utf-8"))


def write_all() -> None:
    write_examples()
    write_cases()
