"""Phase 4 parity: each ported agent against the engine function it came from, on the same inputs (plan §7, Phase 4).

For every agent the legacy engine runs with a recording `ask`, and the agent is held to what the engine sent: the system
prompt byte for byte (it is the prompt cache's key), the user message byte for byte, the tier and the phase (the
subscription meter's key), and the shape of the strict JSON schema (names, types, enums, which fields are required).
Where the engine cleaned the model's answer, the agent's `finish` is held to the same cleaning.

The legacy modules are imported through the service folders on the path (`tests/hiru_ai/conftest.py`). They are deleted
in Phase 8, and this file goes with them.
"""
from __future__ import annotations

import contextlib
from typing import Any, ClassVar

import pytest
from langchain_core.utils.function_calling import convert_to_openai_function

from contracts import sceneplan
from contracts.shotplan import fit
from hiru_ai.core import agents, parts
from tests.services.production_fixture import fixture_scene

REG = parts._registry()


class Stop(Exception):
    """Raised by the recording ask once it has seen the call, so the engine stops before it needs an answer."""


class Rec:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> dict[str, Any]:
        self.calls.append(args)
        raise Stop


def sent(run: Any) -> list[tuple[str, ...]]:
    rec = Rec()
    with contextlib.suppress(Exception):
        run(rec)
    assert rec.calls, "the engine never asked the model"
    return rec.calls


def canon(node: Any) -> Any:
    """A strict schema reduced to what matters on the wire: field names, types, enum values, nullability, required."""
    if not isinstance(node, dict):
        return node
    if "anyOf" in node:
        options = [canon(o) for o in node["anyOf"]]
        rest = [o for o in options if o != "null"]
        return ("nullable", rest[0]) if len(rest) == 1 and "null" in options else ("any", tuple(map(repr, options)))
    kind = node.get("type")
    if isinstance(kind, list):
        rest = [k for k in kind if k != "null"]
        return ("nullable", canon({**node, "type": rest[0]}))
    if "enum" in node:
        return ("enum", tuple(sorted(map(str, node["enum"]))))
    if kind == "object":
        props = {k: canon(v) for k, v in node.get("properties", {}).items()}
        return ("object", props, tuple(sorted(node.get("required", []))))
    if kind == "array":
        return ("array", canon(node.get("items", {})))
    return kind


def new_schema(agent: agents.Agent) -> Any:
    wire = agent.wire_schema()
    return canon(wire if isinstance(wire, dict) else convert_to_openai_function(wire, strict=True)["parameters"])


def check(ident: str, legacy_system: str, legacy_user: str, legacy_schema: dict[str, Any], inp: Any, *, tier: str,
          phase: str) -> agents.Agent:
    agent = agents.Agent(REG, ident)
    system, user = agent.messages(inp)
    assert agent.prompt.text == legacy_system, f"{ident}: the system prompt drifted from the engine's"
    assert system == legacy_system
    assert user == legacy_user, f"{ident}: the user message differs from the engine's"
    assert (agent.manifest.model, agent.phase) == (tier, phase)
    assert new_schema(agent) == canon(legacy_schema), f"{ident}: the strict schema differs from the engine's"
    return agent


# ── doc_ingest ─────────────────────────────────────────────────────────────────────────────────


def test_role_classifier():
    from doc_ingest.engine import roles

    text = "plain words " * 700  # no scene headings, no cues: the rules are unsure, so the model is asked
    ((system, user),) = sent(lambda ask: roles.detect("notes.txt", text, ask))
    agent = check("role_classifier", system, user, roles.ROLE_SCHEMA, {"filename": "notes.txt", "text": text},
                  tier="medium", phase="doc_ingest.role")
    raw = {"role": "script", "confidence": 1.4, "reason": "x" * 400}
    legacy = roles.detect("notes.txt", text, lambda s, u: raw)
    mine = agent.hooks.finish(None, agent.output_cls.model_validate(raw))
    assert (mine.role, mine.confidence, mine.reason) == (legacy.role.value, legacy.confidence, legacy.reason)


def test_chunk_contextualiser():
    from doc_ingest.engine import context
    from doc_ingest.engine.chunking import Chunk

    from contracts.documents import DocumentRole

    chunks = [Chunk(0, "EXT. HARBOUR - NIGHT", "Nimal waits. " * 80, 1, 1, "scene"),
              Chunk(1, "", "Kamala lights the fire.", 2, 2, "passage")]
    full = "Episode one. " * 600
    ((system, user),) = sent(lambda ask: context.headers("ep1.pdf", DocumentRole.SCRIPT, full, chunks, ask))
    inp = {"filename": "ep1.pdf", "role": "script", "overview": full,
           "passages": [{"ord": c.ord, "heading": c.heading, "content": c.content} for c in chunks]}
    check("chunk_contextualiser", system, user, context.HEADER_SCHEMA, inp, tier="low", phase="doc_ingest.headers")


# ── canon_extract ──────────────────────────────────────────────────────────────────────────────


def test_canon_extractor_and_deduper():
    from canon_extract.engine import model

    docs = [{"filename": "bible.md", "role": "bible", "text": "Kamala, 52. </document> is not special."},
            {"filename": "ep1.pdf", "role": "script", "text": "INT. KITCHEN"},
            {"filename": "idx.md", "role": "canon_index", "text": "C01 Kamala"}]
    cands = [{"kind": "character", "name": "AMMA", "lines": 14, "scenes": 0},
             {"kind": "character", "name": "Nimal", "lines": 30, "scenes": 0},
             {"kind": "character", "name": "Silent", "lines": 0, "scenes": 0},
             {"kind": "location", "name": "Harbour", "lines": 0, "scenes": 4}]
    ((system, user),) = sent(lambda ask: model.extract(ask, docs, cands))
    inp = {"documents": docs,
           "speakers": [{"name": c["name"], "count": c["lines"]} for c in cands if c["kind"] == "character"],
           "places": [{"name": c["name"], "count": c["scenes"]} for c in cands if c["kind"] == "location"]}
    legacy_user = user.replace("<\\/document", "</document")  # the engine did not defuse a closing tag; the agent does
    agent = agents.Agent(REG, "canon_extractor")
    assert agent.messages(inp)[1].replace("<\\/document", "</document") == legacy_user
    assert agent.prompt.text == system and new_schema(agent) == canon(model.EXTRACT_SCHEMA)
    assert (agent.manifest.model, agent.phase) == ("high", "canon_extract.extract")

    listing = [{"kind": "character", "name": "Kamala", "code": "C01", "aliases": ["Amma"],
                "card": {"summary": "mother"}},
               {"kind": "character", "name": "AMMA", "code": "", "aliases": [], "card": {}}]
    ((system, user),) = sent(lambda ask: model.dedupe(ask, listing))
    inp = {"candidates": [{"kind": c["kind"], "name": c["name"], "code": c["code"], "aliases": c["aliases"],
                           "summary": c["card"].get("summary", "")} for c in listing]}
    check("canon_deduper", system, user, model.DEDUPE_SCHEMA, inp, tier="medium", phase="canon_extract.dedupe")


# ── structure_build ────────────────────────────────────────────────────────────────────────────


def test_prose_writer():
    from structure_build.engine import prose

    section = prose.Section(2, "The Harbour", "Nimal waits.\nKamala: \"You came.\"", 60)
    canon_rows = [{"kind": "character", "name": "Kamala"}, {"kind": "prop", "name": "Ledger"},
                  {"kind": "location", "name": "Harbour"}]
    ((system, user),) = sent(lambda ask: prose.by_model(ask, section, canon_rows))
    inp = {"number": 2, "title": "The Harbour", "duration_s": 60, "body": section.body, "canon": canon_rows}
    check("prose_writer", system, user, prose.SCHEMA, inp, tier="high", phase="structure_build.prose")
    ((_, user2),) = sent(lambda ask: prose.by_model(ask, prose.Section(3, "", "x", None), []))
    assert agents.Agent(REG, "prose_writer").messages({"number": 3, "title": "", "body": "x"})[1] == user2


def test_architect():
    from structure_build.engine import architect

    episode = {"number": 1, "title": "Home", "scenes": [
        {"number": 1, "heading": {"raw": "INT. KITCHEN - DAWN"},
         "blocks": [{"kind": "action", "text": "Kamala lights the fire. " * 20, "speaker": ""},
                    {"kind": "dialogue", "text": "Amma.", "speaker": "Nimal"}]},
        {"number": 2, "heading": {"raw": "EXT. ROAD - DAY"}, "blocks": []}]}
    ((system, user),) = sent(lambda ask: architect.name_episode(ask, episode))
    inp = {"number": 1, "title": "Home", "scenes": [
        {"number": s["number"], "heading": s["heading"]["raw"], "blocks": s["blocks"]} for s in episode["scenes"]]}
    check("architect", system, user, architect.SCHEMA, inp, tier="ultra", phase="structure_build.architect")


def test_look_drafter():
    from structure_build.engine import looks

    rows = [{"id": "c1", "name": "Nimal", "kind": "character",
             "current": {"card": {"wardrobe": "shirt; later smart-casual", "summary": "the son", "notes": ""}}},
            {"id": "c2", "name": "Kamala", "kind": "character", "current": {"card": {"wardrobe": "a saree"}}}]
    ((system, user),) = sent(lambda ask: looks.proposals(ask, rows, 10))
    inp = {"episodes": 10, "characters": [{"name": r["name"], "card": r["current"]["card"]} for r in rows]}
    agent = check("look_drafter", system, user, looks.SCHEMA, inp, tier="medium", phase="structure_build.looks")
    assert "from" in convert_to_openai_function(agent.output_cls, strict=True)["parameters"]["properties"]["looks"][
        "items"]["properties"], "on the wire the field is `from`"


# ── script_split ───────────────────────────────────────────────────────────────────────────────


def scene_parts() -> tuple[dict[str, Any], list[Any], dict[str, str], str]:
    scene, lines, _ = fixture_scene(0)
    items = sceneplan.scene_items(scene, lines)
    names = {ln["character_id"]: ln["speaker"] for ln in lines if ln.get("character_id")}
    return scene, items, names, scene["heading"]


def test_beat_finder():
    from script_split.engine import beats

    _, items, _, _ = scene_parts()
    ((system, user),) = sent(lambda ask: beats.classify(ask, items))
    check("beat_finder", system, user, beats.BEATS_SCHEMA, {"items": items}, tier="medium", phase="script_split.beats")


def test_stager():
    from script_split.engine import staging

    _, items, names, _ = scene_parts()
    ((system, user),) = sent(lambda ask: staging.make(ask, items, list(names.values()), version=1,
                                                      reading_text="about: a call", place="A gate, a bench",
                                                      speaker_names=names))
    inp = {"items": items, "speaker_names": names, "reading_text": "about: a call", "place": "A gate, a bench"}
    check("stager", system, user, staging.STAGING_SCHEMA, inp, tier="medium", phase="script_split.staging")
    ((_, bare),) = sent(lambda ask: staging.make(ask, items, [], version=1, speaker_names=names))
    assert agents.Agent(REG, "stager").messages({"items": items, "speaker_names": names})[1] == bare


def test_scene_reader():
    from script_split.engine import reading

    _, items, names, _ = scene_parts()
    ctx = reading.SceneContext(heading="EXT. GATE - DAY", note="warm", episode_title="Home", synopsis="A return.",
                               before="INT. HOUSE", after="EXT. ROAD",
                               characters=(("Kasun", "a driver"), ("Anudi", "")))
    ((system, user),) = sent(lambda ask: reading.make(ask, items, [], version=1, context=ctx, speaker_names=names))
    inp = {"items": items, "speaker_names": names, "context": {
        "heading": ctx.heading, "note": ctx.note, "episode_title": ctx.episode_title, "synopsis": ctx.synopsis,
        "before": ctx.before, "after": ctx.after, "characters": [{"name": n, "summary": s} for n, s in ctx.characters]}}
    check("scene_reader", system, user, reading.READING_SCHEMA, inp, tier="high", phase="script_split.reading")
    ((_, bare),) = sent(lambda ask: reading.make(ask, items, [], version=1, speaker_names=names))
    assert agents.Agent(REG, "scene_reader").messages({"items": items, "speaker_names": names})[1] == bare


def test_scene_planner():
    from script_split.engine import planner

    _, items, names, heading = scene_parts()
    kwargs: dict[str, Any] = {"heading": heading, "envelope_s": 16, "allowed": (4, 6, 8), "speaker_names": names,
                              "context": "Episode: Home", "reading": "about: a call", "notes": ["S01 needs a WIDE"]}
    ((system, user),) = sent(lambda ask: planner.plan_by_model(ask, items, **kwargs))
    inp = {"items": items, "speaker_names": names, "heading": heading, "envelope_s": 16, "allowed": [4, 6, 8],
           "context": "Episode: Home", "reading": "about: a call", "notes": ["S01 needs a WIDE"]}
    check("scene_planner", system, user, planner.PLAN_SCHEMA, inp, tier="high", phase="script_split.plan")
    plain = {k: v for k, v in kwargs.items() if k not in ("context", "reading", "notes")}
    ((_, bare),) = sent(lambda ask: planner.plan_by_model(ask, items, **plain))
    assert agents.Agent(REG, "scene_planner").messages(
        {"items": items, "speaker_names": names, "heading": heading, "envelope_s": 16})[1] == bare


@pytest.mark.parametrize(("ident", "lens", "tier"), [("coverage_critic", "coverage", "high"),
                                                     ("emotion_critic", "emotion", "medium"),
                                                     ("editor_critic", "editor", "medium")])
def test_the_three_critics(ident: str, lens: str, tier: str):
    from script_split.engine import critic, planner

    _, items, names, _ = scene_parts()
    proposal = planner.plan_by_rules(items, envelope_s=16)
    result = fit(items, proposal, envelope_s=16)
    listing = planner.scene_listing(items, names)
    extras: dict[str, Any] = {"reading": "about: a call", "staging": "Kasun: gate", "found": ["Kasun teleports"]}
    seen: dict[str, tuple[str, str]] = {}

    def ask(which: str, system: str, user: str) -> dict[str, Any]:
        seen[which] = (system, user)
        raise Stop

    with contextlib.suppress(Exception):
        critic.review(ask, listing, result, items, **extras)
    system, user = seen[lens]
    inp = {"listing": listing, "shot_list": critic.describe(result, items), **extras}
    check(ident, system, user, critic.CRITIC_SCHEMA, inp, tier=tier, phase=f"script_split.critic.{lens}")
    bare: dict[str, tuple[str, str]] = {}

    def ask_bare(which: str, system: str, user: str) -> dict[str, Any]:
        bare[which] = (system, user)
        raise Stop

    with contextlib.suppress(Exception):
        critic.review(ask_bare, listing, result, items)
    assert agents.Agent(REG, ident).messages({"listing": listing, "shot_list": critic.describe(result, items)})[1] \
        == bare[lens][1]


# ── shot_producer ──────────────────────────────────────────────────────────────────────────────


def test_shot_critic_and_craft_articulator():
    from shot_producer.engine import critique, techniques
    from shot_producer.engine.model import production_input, scene_input

    from tests.services.production_fixture import CANON, PID

    scene, lines, rows = fixture_scene(0)
    prod = production_input({"id": str(PID), "title": "Harbour Lights", "orientation": "horizontal", "settings": {},
                             "summary": ""}, CANON, None)
    si = scene_input(scene, rows, lines, CANON, prod)
    drafts = [(s, {"cinematography": {"camera": "handheld", "angle": "eye", "movement": "static"},
                   "first_frame": {"composition": "Two-shot", "subjects": ["Kamala"]}, "beats": []}, [])
              for s in si.shots[:2]]

    class Llm:
        enabled = True
        calls: ClassVar[list[tuple[str, str]]] = []

        def json(self, *, system: str, user: str, **kw: Any) -> dict[str, Any]:
            self.calls.append((system, user))
            raise Stop

    llm = Llm()
    critique.review(llm, si, drafts, ["S01 does not frame its speaker"])
    system, user = llm.calls[0]
    inp = {"scene_number": si.number, "heading": si.heading, "context": critique.context_block(si),
           "plan": si.plan.text() if si.plan and si.plan.text() else "",
           "drafts": [critique._draft(s, ir, on) for s, ir, on in drafts], "free": ["S01 does not frame its speaker"]}
    agent = check("shot_critic", system, user, critique.SCHEMA, inp, tier="high", phase="shot_producer.critique")
    raw = {"acceptable": False, "notes": ["  S01:   x ", "", "b", "c", "d", "e"]}

    class Answer(Llm):
        def json(self, **kw: Any) -> dict[str, Any]:
            return raw

    legacy = critique.review(Answer(), si, drafts, ["S01 does not frame its speaker"])
    mine = agent.hooks.finish(agent.input_cls.model_validate(inp), agent.output_cls.model_validate(raw))
    assert mine.notes == legacy
    content = {"acceptable": True, "notes": ["could be wider"]}
    assert critique.review(type("A", (Llm,), {"json": lambda self, **k: content})(), si, drafts, []) == []
    assert agent.hooks.finish(agent.input_cls.model_validate({**inp, "free": []}),
                              agent.output_cls.model_validate(content)).notes == []

    scenes = ["SCENE 1: A call\nHer phone rings.", "SCENE 2: A walk"]
    ((system, user),) = sent(lambda ask: techniques.articulate(ask, scenes))
    agent = check("craft_articulator", system, user, techniques.ARTICULATE_SCHEMA, {"scenes": scenes}, tier="medium",
                  phase="shot_producer.craft")
    raw2 = {"problems": ["  show a call  ", "show a call", "x" * 300, "a", "b", "c", "d"]}
    assert agent.hooks.finish(None, agent.output_cls.model_validate(raw2)).problems == \
        techniques.articulate(lambda s, u: raw2, scenes)


# ── frame_render ───────────────────────────────────────────────────────────────────────────────


def test_frame_inspector():
    from frame_render.engine import inspect

    expected = inspect.Expected(["Anudi: long dark hair"], ["Anudi's Father (heard on the phone)"],
                                "Anudi at the window")
    seen: list[tuple[str, str]] = []

    def look(data: bytes, mime: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        seen.append((system, user))
        raise Stop

    inspect.vision_checks(look, b"png", "image/png", expected)
    system, user = seen[0]
    inp = {"image_b64": "cG5n", "mime": "image/png", "seen": expected.seen, "unseen": expected.unseen,
           "frame": expected.frame}
    agent = check("frame_inspector", system, user, inspect.SCHEMA, inp, tier="vision", phase="frame_render.vision")
    assert agent.hooks.images(agent.input_cls.model_validate(inp)) == [("image/png", "cG5n")]
    bare = inspect.expectation(inspect.Expected([], [], ""))
    assert agent.messages({"image_b64": "x", "seen": []})[1] == bare


# ── director_chat ──────────────────────────────────────────────────────────────────────────────


def test_advisor():
    from director_chat.engine import agents as board

    seen: list[tuple[str, str]] = []

    def ask(system: str, user: str) -> dict[str, Any]:
        seen.append((system, user))
        raise Stop

    board.advisor_review(ask, advisor_name="Weston", advisor_charter="You cut early.", scene_text="S01 WIDE 4s",
                         summary="S02 became a CU.")
    system, user = seen[0]
    inp = {"charter": "You cut early.", "summary": "S02 became a CU.", "scene_text": "S01 WIDE 4s"}
    check("advisor", system, user, board.ADVISOR_SCHEMA, inp, tier="medium", phase="director.advisor")


@pytest.mark.parametrize(("ident", "craft"), [("cinematographer", "cinematography"), ("editor", "timing"),
                                              ("sound_designer", "sound"), ("continuity", "continuity")])
def test_the_four_specialists(ident: str, craft: str):
    from director_chat.engine import agents as board

    task = {"agent": craft, "shots": [2, 3], "instruction": "Add a reaction after S02."}
    seen: dict[str, tuple[str, str]] = {}

    def ask_for(agent: str) -> Any:
        def ask(system: str, user: str) -> dict[str, Any]:
            seen[agent] = (system, user)
            raise Stop

        return ask

    board.run_specialists(ask_for, [task], scene_text="S01 MCU 6s", lead_charter="Warm, patient.")
    system, user = seen[craft]
    inp = {"lead_charter": "Warm, patient.", "scene_text": "S01 MCU 6s", "shots": [2, 3],
           "instruction": task["instruction"]}
    check(ident, system, user, board.SCHEMA, inp, tier="high", phase=f"director.{craft}")
    seen.clear()
    board.run_specialists(ask_for, [{"agent": craft, "shots": []}], scene_text="S01", lead_charter="")
    assert agents.Agent(REG, ident).messages({"scene_text": "S01"})[1] == seen[craft][1]


def test_conductor():
    from director_chat.engine import conductor

    kwargs: dict[str, Any] = {"plan_text": "S01 MCU 6s\nS02 WIDE 4s", "message": "make S02 a close-up",
                              "history": "you: hello\nlead: hi", "memory": ["Kasun is a driver"],
                              "said": "make S02 a close-up"}
    ((system, user),) = sent(lambda ask: conductor.by_model(ask, **kwargs))
    check("conductor", system, user, conductor.SCHEMA, kwargs, tier="medium", phase="director.conduct")
    ((_, again),) = sent(lambda ask: conductor.by_model(ask, **kwargs, again=True))
    assert agents.Agent(REG, "conductor").messages({**kwargs, "again": True})[1] == again
    ((_, bare),) = sent(lambda ask: conductor.by_model(ask, plan_text="S01", message="hi", history="", memory=[]))
    assert agents.Agent(REG, "conductor").messages({"plan_text": "S01", "message": "hi"})[1] == bare


def test_options_writer():
    from types import SimpleNamespace

    from director_chat.engine import options

    kernel = SimpleNamespace(describe=lambda: "S02 MCU 6s")
    kwargs: dict[str, Any] = {"message": "how could S02 play?", "history": "you: hi", "lead_charter": "Patient, warm.",
                              "memory": ["No hand-held in the kitchen"]}
    ((system, user),) = sent(lambda ask: options.propose(ask, kernel=kernel, **kwargs))
    inp = {"lead_charter": kwargs["lead_charter"], "memory": kwargs["memory"], "history": kwargs["history"],
           "shot_list": "S02 MCU 6s", "message": kwargs["message"]}
    check("options_writer", system, user, options.SCHEMA, inp, tier="high", phase="director.options")
    ((_, bare),) = sent(lambda ask: options.propose(ask, kernel=kernel, message="m", history="", lead_charter="",
                                                    memory=[]))
    assert agents.Agent(REG, "options_writer").messages({"shot_list": "S02 MCU 6s", "message": "m"})[1] == bare


def test_translator():
    from types import SimpleNamespace

    from director_chat.engine import translate

    items = [{"kind": "dialogue", "line_id": "l1", "speaker": "Kasun", "delivery": "quietly",
              "text": "Started with five thousand rupees."},
             {"kind": "dialogue", "line_id": "l2", "speaker": "Anudi", "delivery": "", "text": "Éla — \"wow\"."}]
    kernel = SimpleNamespace(items=items)
    spec = translate.Spec("Sinhala", "si", "colloquial")
    ((system, user),) = sent(lambda ask: translate.propose(ask, kernel=kernel, spec=spec, line_blocks={},
                                                           production="Harbour Lights", memory=["Keep names"]))
    inp = {"language": spec.name, "code": "si", "style": "colloquial", "production": "Harbour Lights",
           "memory": ["Keep names"], "lines": [{"line_id": i["line_id"], "speaker": i["speaker"],
                                                 "delivery": i["delivery"], "text": i["text"]} for i in items]}
    agent = check("translator", system, user, translate.SCHEMA, inp, tier="high", phase="director.translate")
    assert agent.manifest.writes_dialogue is True
    ((_, bare),) = sent(lambda ask: translate.propose(ask, kernel=kernel, spec=translate.Spec("Tamil"),
                                                      line_blocks={}, production="", memory=[]))
    assert agent.messages({"language": "Tamil", "lines": inp["lines"]})[1] == bare


def test_shot_intent():
    from shot_producer.engine import intent
    from shot_producer.engine.model import production_input, scene_input

    from tests.services.production_fixture import CANON, PID

    scene, lines, rows = fixture_scene(0)
    prod = production_input({"id": str(PID), "title": "Harbour Lights", "orientation": "horizontal", "settings": {},
                             "summary": ""}, CANON, None)
    si = scene_input(scene, rows, lines, CANON, prod)
    seen: list[tuple[str, str]] = []

    class Llm:
        enabled = True

        def json(self, *, system: str, user: str, **kw: Any) -> dict[str, Any]:
            seen.append((system, user))
            raise Stop

    intent.write(Llm(), si, si.shots, prod, plan=True)
    system, user = seen[0]
    inp = {"production": intent.production_block(prod), "scene": intent.scene_prompt(si, si.shots)}
    check("shot_intent", system, user, intent.SCHEMA, inp, tier="high", phase="shot_producer.intent")


def test_shot_writer():
    from shot_producer.engine import shots
    from shot_producer.engine.continuity import ContinuityLedger
    from shot_producer.engine.model import production_input, scene_input
    from shot_producer.engine.schema import get_schema

    from tests.services.production_fixture import CANON, PID

    scene, lines, rows = fixture_scene(0)
    prod = production_input({"id": str(PID), "title": "Harbour Lights", "orientation": "horizontal", "settings": {},
                             "summary": ""}, CANON, None)
    si = scene_input(scene, rows, lines, CANON, prod)
    seen: list[tuple[str, str, dict[str, Any]]] = []

    class Llm:
        enabled = True

        def json(self, *, system: str, user: str, schema: dict[str, Any], **kw: Any) -> dict[str, Any]:
            seen.append((system, user, schema))
            raise Stop

    ledger = ContinuityLedger(prod.cast)
    prefix = shots.production_block(prod)
    shots.design_by_model(Llm(), prefix, si, list(si.shots), ledger, ["S01 needs a closer frame"])
    system, user, schema = seen[0]
    opening = "\n".join(b for b in (ledger.identity_block(si.shots[0]), ledger.scene_block(si.id)) if b)
    tail = shots.scene_tail(si, list(si.shots), opening=opening, others=[], notes=["S01 needs a closer frame"])
    agent = check("shot_writer", system, user, schema, {"production": prefix, "scene": tail}, tier="high",
                  phase="shot_producer.scene")
    assert agent.wire_schema()["title"] == "scene_design"
    assert {k: v for k, v in agent.wire_schema().items() if k != "title"} == get_schema().scene_schema()
