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
from contracts.adam.plan import AdamPlan, Moment, SceneAnalysis, SceneScript, ShotCard, Treatment
from contracts.adam.screening import LENSES

EXAMPLE_SCENE = "refuses_money"
AGENTS = ("adam_dramaturg", "adam_director", "adam_moment_writer", "adam_blocker", "adam_shot_designer",
          "adam_sound_designer")
# Plan/2026-11-05: the one-take planner. `adam_take` writes stages ①, ②'s chosen treatment, ③, ④ and ⑤ (without the
# sound) in one answer and carries the worked example; `adam_critic` reads a plan once in four lenses; `adam_fixer`
# answers one problem with the reviser's operations. The last two read a whole plan, so they carry no example.
TAKE_AGENT = "adam_take"
# Phase 5: the four screening critics and the reviser. They read a whole plan, so their prompts carry no worked example
# (a critic judges what it is given) and their eval cases are generated here from the masters too.
SCREEN_AGENTS = ("adam_critic_audience", "adam_critic_editor", "adam_critic_opportunity", "adam_critic_fidelity",
                 "adam_reviser", "adam_critic", "adam_fixer")
LENS_NOTE = {  # what a scripted critic says about a master: one low note on card 1, in its own lens
    "adam_critic_audience": "Hold the face a beat longer before the cut so the feeling can land.",
    "adam_critic_editor": "The cut into this card could be motivated by the look, not only the line.",
    "adam_critic_opportunity": "A hands insert (kind hands) before this card would give the moment room.",
    "adam_critic_fidelity": "Nothing drifts from the script; keep veo_notes current if the picture changes."}
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
        "break_block": a.break_.block, "aftermath": a.aftermath.state, "key_moment": a.key_moment.model_dump(),
        "questions": [{"question": q.question, "blocks": q.blocks} for q in a.questions]})


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


def take_wire(name: str) -> w.TakeWire:
    """The master as ONE answer: the analysis, the chosen treatment and the two pitches, the moments with their
    bindings, the staging and the cards without their sound."""
    p = master_with_stance(name)
    pitches = [w.PitchW.model_validate({k: alt[k] for k in ("stance", "name", "concept")})
               for alt in _yaml("treatments", name)["alternates"]]
    cards = [w.TakeCardW.model_validate(card_wire(c).model_dump(exclude={"sound"})) for c in p.cards]
    return w.TakeWire(analysis=analysis_wire(p.analysis), treatment=treatment_wire(p.treatment, p.moments,
                                                                                   stance_of(name)),
                      pitches=pitches, moments=moments_wire(p), staging=staging_wire(p),
                      cards=w.TakeCardsW(cards=cards))


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
    if agent == TAKE_AGENT:
        return take_inputs(name)
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


def take_inputs(name: str) -> dict[str, Any]:
    """What `adam_take` is given: the scene, its context and the facts code knows. The retrieved passages are the
    system's to add (the agent cannot search), so a case has none."""
    from hiru_ai.systems.adam.adam_shot_planner import scene as planner

    script = gold.scene(name)
    return {"scene": script, "context": {"heading": title(name)},
            "facts": planner.facts_of(SceneScript.model_validate(script))}


def replies(agent: str, name: str) -> dict[str, Any]:
    p = master_with_stance(name)
    wire: BaseModel
    if agent == TAKE_AGENT:
        wire = take_wire(name)
    elif agent == "adam_dramaturg":
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


def screen_input(name: str, agent: str = "") -> dict[str, Any]:
    """The whole master as a critic (or the reviser) is given it: the fidelity critic and the reviser also get the
    code's report, which is how they read what code found."""
    from hiru_ai.core import parts

    p = master_with_stance(name)
    scene = gold.scene(name)
    out: dict[str, Any] = {"scene": scene, "analysis": _dump(p.analysis), "treatment": _dump(p.treatment),
                           "moments": _dump(p.moments), "staging": _dump(p.staging), "cards": _dump(p.cards),
                           "sound_map": _dump(p.sound_map)}
    if agent == "adam_fixer":
        return fixer_input(name, out)
    if agent in ("adam_critic_fidelity", "adam_reviser", "adam_critic"):
        base = {"scene": scene, "plan": p.model_dump(mode="json", by_alias=True)}
        found = {n: dict(parts.module("step", f"adam_{n}", "step").run(base))
                 for n in ("fidelity", "fit", "continuity", "feasibility", "coverage")}
        score = dict(parts.module("step", "adam_score", "step").run({**base, **found}))
        out["report"] = parts.module("step", "adam_notes", "step").run({**found, "score": score})["text"]
    if agent == "adam_reviser":
        out["notes"] = ["n1 [opportunity, low, change] card 1: " + LENS_NOTE["adam_critic_opportunity"]]
    return out


def fixer_input(name: str, whole: dict[str, Any]) -> dict[str, Any]:
    """What the fixer is given for a master: one local problem about its first card, with the cards around it."""
    p = master_with_stance(name)
    cards = [c for c in p.cards if abs(c.number - 1) <= 2]
    shown = {m for c in cards for m in c.moments}
    problem = {"id": "p1", "kind": "local", "source": "note", "card": 1, "severity": "high", "note_id": "n1",
               "note_kind": "change", "text": LENS_NOTE["adam_critic_opportunity"]}
    return {"scene": whole["scene"], "concept": p.treatment.concept, "problem": problem,
            "moments": [m for m in whole["moments"] if m["id"] in shown], "cards": [c for c in whole["cards"]
                                                                                    if c["number"] in
                                                                                    {x.number for x in cards}]}


def screen_reply(agent: str, name: str) -> dict[str, Any]:
    """What a scripted critic answers about a master (one low note, a 4), and the reviser: it writes the first card
    again exactly as it is, an operation that changes nothing."""
    if agent in ("adam_reviser", "adam_fixer"):
        first = master_with_stance(name).cards[0]
        return {"operations": [{"op": "replace_card", "why": "the note on card 1", "number": 1, "after": "", "id": "",
                                "card": card_wire(first).model_dump(mode="json"), "moment": None}],
                "dispositions": [{"note_id": "n1" if agent == "adam_reviser" else "p1", "done": [1], "declined": ""}]}
    if agent == "adam_critic":
        return {"notes": [{"lens": lens, "card": 1, "severity": "low", "kind": "change", "cell": "",
                           "note": LENS_NOTE[f"adam_critic_{lens}"]} for lens in LENSES],
                "scores": [{"lens": lens, "score": 4} for lens in LENSES]}
    return {"notes": [{"card": 1, "severity": "low", "kind": "change", "cell": "", "note": LENS_NOTE[agent]}],
            "score": 4}


# What a case holds the answer to. Scripted, the answer is the case's own reply; LIVE, a creative agent's words are its
# own, so only what any good answer shares is expected: the block the scene breaks on, and the order of the stances.
def expectation(agent: str, name: str) -> dict[str, Any]:
    reply = replies(agent, name)
    if agent == "adam_dramaturg":
        return {"break_block": reply["break_block"]}
    if agent == TAKE_AGENT:
        return {"analysis": {"break_block": reply["analysis"]["break_block"]}}
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
    for agent in (*AGENTS, TAKE_AGENT):
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


SCREEN_HEADER = "\n".join([
    "# Generated by tests/adam/stages.py from the gold masters (tests/eval/adam/masters): do not edit by hand.",
    "# Scripted, each case answers with a stock reply (a critic: one low note and a 4; the reviser: the first card",
    "# written again, a change of nothing), so a pass says the agent builds, sends the whole plan and cleans the",
    "# answer as it should. LIVE (`hiru-ai eval <agent> --live`) the model answers the INPUT and the case holds it",
    "# only to the shape of an answer; whether its notes are GOOD is a Hiru director's judgement (plan/2026-11-04b",
    "# section 10).",
    "# These prompts hold no worked example, so every gold scene is a case.",
    ""])


def case_scenes() -> list[str]:
    """The gold scenes with an eval case: all but the one the prompts' worked example shows."""
    return [n for n in gold.names() if n != EXAMPLE_SCENE]


def cases(agent: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"name": name, "input": inputs(agent, name), "reply": replies(agent, name),
         "expect": expectation(agent, name)} for name in case_scenes()]
    return out


def screen_cases(agent: str) -> list[dict[str, Any]]:
    """Every gold scene is a case: these prompts hold no worked example, so none is left out."""
    return [{"name": name, "input": screen_input(name, agent), "reply": screen_reply(agent, name),
             "expect": {"score": 4} if agent.startswith("adam_critic_") else {}} for name in gold.names()]


def write_cases() -> None:
    for agent in (*AGENTS, TAKE_AGENT):
        body = yaml.safe_dump(cases(agent), allow_unicode=True, sort_keys=False, width=100000,
                              default_flow_style=None)
        (AGENT_DIR / agent / "evals" / "cases.yaml").write_bytes((CASE_HEADER + body).encode("utf-8"))
    for agent in SCREEN_AGENTS:
        body = yaml.safe_dump(screen_cases(agent), allow_unicode=True, sort_keys=False, width=100000,
                              default_flow_style=None)
        (AGENT_DIR / agent / "evals" / "cases.yaml").write_bytes((SCREEN_HEADER + body).encode("utf-8"))


def write_all() -> None:
    write_examples()
    write_cases()
