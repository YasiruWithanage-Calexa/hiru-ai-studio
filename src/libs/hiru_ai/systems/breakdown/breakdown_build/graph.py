"""breakdown_build: the documents read once into the two memories, and today's columns filled from them
(plan/2026-11-11 §4, phases 2, 3 and 5).

    read      the production's documents (a 'pages' document by its reader's clean transcription)
    breakdown `contracts.breakdown.run.create`: the split per document, the build, ONE continuity call, the episode
    calls
              four at a time, the checks and the repair; progress on the job's events
    store     the source memory of each document (once) and the breakdown memory
    fill      D1: canon cards, `episodes` / `scenes` / `dialogue_lines` through `structure_write`'s plan, the direction
              rules as `production_memory` drafts, and the creation questions (defaulted: the earlier document wins)
    packets   each scene's packet, assembled by code, kept beside the scene with what it waits for

The structure_build function runs this instead of its own build when `BREAKDOWN__ENABLED` (the absorbed steps retire
behind that switch; the old path stays until the live check). A delivery whose state names `breakdown_refresh` (a scene
id) runs the one-scene refresh instead (phase 5): the person's edited words are broken down again, the stager's map is
cleared, and the hand-over to the next scene in the story is checked.

`packet_for(ctx, scene_row)` is what a planner calls before planning (step 6): the scene's stored packet, staged first
(ONE `breakdown_stager` call) when it has no map yet. Planners reach it by id (`parts.module`), never by import.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.breakdown import fill, memory, packet, stage
from contracts.breakdown import run as brun
from contracts.breakdown.schema import Breakdown, SourceMemory
from contracts.build import Agent, QuestionStatus, Stage
from contracts.canon import (
    CanonCard,
    CanonKind,
    name_key,
    next_code,
    reference_sheet_prompt,
    voice_pin,
    wardrobe_anchor,
)
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import agents, doc_reader, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.breakdown.breakdown_build.state import State

_log = logging.getLogger(__name__)
_SAVING = threading.Lock()  # one memory save at a time in this process (the stager runs in a planner's workers)
AGENT = Agent.ARCHITECT.value
Row = dict[str, Any]
STORY_ROLES = ("script", "outline", "bible", "canon_index", "notes")  # every document a person uploaded for the story
NO_MODEL = (
    "The scene breakdown needs the AI model, which is not available. Turn BREAKDOWN__ENABLED off to build as before."
)


def _ask(agent_id: str, ctx: RunContext) -> Any:
    agent = agents.build(agent_id)
    return lambda message: agent.run({"message": message}, ctx)


def calls(ctx: RunContext) -> brun.Calls:
    return brun.Calls(
        split=_ask("breakdown_split", ctx),
        continuity=_ask("breakdown_continuity", ctx),
        episode=_ask("breakdown_episode", ctx),
        repair=_ask("breakdown_repair", ctx),
    )


# ── loading and saving the memories ─────────────────────────────────────────────────────────────────────────────


def load(ctx: RunContext, production_id: UUID) -> tuple[Breakdown | None, list[SourceMemory], int]:
    store = ctx.need("breakdown")
    row = store.memory(production_id)
    if not row:
        return None, [], 0
    sources = [SourceMemory.model_validate(r["body"]) for r in store.sources(production_id)]
    return Breakdown.model_validate(row["body"]), sources, int(row.get("version") or 1)


def save(ctx: RunContext, production_id: UUID, bd: Breakdown) -> None:
    ctx.need("breakdown").save_memory(production_id, bd.model_dump(mode="json"), bd.version)


def packet_rows(bd: Breakdown, scene_ids: list[str] | None = None) -> list[Row]:
    """Each scene's packet (or why it has none) for the scenes that have a row; `scene_ids` narrows to memory ids."""
    rows = []
    for sc in bd.scenes:
        if not sc.row_id or (scene_ids is not None and sc.id not in scene_ids):
            continue
        if sc.brief is None:
            got: Row = {}
            waits = ["the scene has no breakdown yet"]
        else:
            got = packet.assemble(bd, sc.id)
            waits = packet.incomplete(bd, got)
        rows.append(
            {
                "scene_id": sc.row_id,
                "scene_key": sc.id,
                "packet": got,
                "waits": waits,
                "script_version": sc.script_version,
                "memory_version": bd.version,
            }
        )
    return rows


# ── filling today's columns (D1) ────────────────────────────────────────────────────────────────────────────────


def canon_rows(
    cards: list[Row], canon: list[Row], *, production_id: str, actor: str | None, aspect_ratio: str
) -> list[tuple[Row, Row]]:
    """A canon entity (and its first version) for every card the canon does not have by name yet. An entity a person
    already has keeps its card: the memory never overwrites the canon library's edits."""
    taken = {str(c.get("code") or "") for c in canon}
    known = {(str(c["kind"]), name_key(n)) for c in canon for n in [c["name"], *(c.get("aliases") or [])]}
    out = []
    for c in cards:
        kind = CanonKind(c["kind"])
        if not c["name"] or (kind.value, name_key(c["name"])) in known:
            continue
        known.add((kind.value, name_key(c["name"])))
        code = next_code(kind, taken)
        taken.add(code)
        card = CanonCard.model_validate(c["card"])
        entity_id = str(uuid4())
        character = kind is CanonKind.CHARACTER
        version = {
            "id": str(uuid4()),
            "entity_id": entity_id,
            "production_id": production_id,
            "version": 1,
            "card": card.model_dump(),
            "card_hash": hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True).encode()).hexdigest(),
            "wardrobe_anchor": wardrobe_anchor(card) if character else "",
            "voice_pin": voice_pin(card) if character else "",
            "reference_prompt": reference_sheet_prompt(kind, c["name"], card, aspect_ratio=aspect_ratio),
            # plan/2026-11-12 (schema v22): a thing the script implies is `inferred`, so a person can tell it apart
            "source": "inferred" if c.get("inferred") else "extract",
            "created_by": actor,
        }
        out.append(
            (
                {
                    "id": entity_id,
                    "production_id": production_id,
                    "kind": kind.value,
                    "code": code,
                    "name": c["name"][:120],
                    "aliases": [],
                    "core": False,
                },
                version,
            )
        )
    return out


def question_rows(job_id: UUID, production_id: UUID, questions: list[str]) -> list[Row]:
    """The merge's questions (§4.2) on the build's question channel, defaulted to the earlier document."""
    rows = []
    for q in questions:
        key = "breakdown:" + hashlib.sha256(q.encode()).hexdigest()[:16]
        rows.append(
            {
                "id": str(UUID(hashlib.md5(f"{job_id}:{key}".encode()).hexdigest())),  # noqa: S324 (an id)
                "production_id": str(production_id),
                "job_id": str(job_id),
                "key": key,
                "agent": Agent.CANON.value,
                "scope": "documents",
                "title": q.split(":", 1)[0][:200],
                "body": q[:2000],
                "options": [
                    {"value": "earlier", "label": "Keep the earlier document's"},
                    {"value": "later", "label": "Use the later document's"},
                ],
                "allow_text": True,
                "status": QuestionStatus.DEFAULTED.value,
                "answer": {"value": "earlier"},
            }
        )
    return rows


def fill_columns(
    ctx: RunContext, payload: DispatchPayload, bd: Breakdown, *, envelope_s: int, aspect_ratio: str
) -> Row:
    """Writes today's columns from the memory and records on each memory scene which row and lines it filled."""
    production_id = payload.production_id
    assert production_id is not None
    canon_port, structure = ctx.need("canon"), ctx.need("structure")
    actor = str(payload.actor_user_id) if payload.actor_user_id else None
    made = canon_rows(
        fill.canon_cards(bd),
        canon_port.entities(production_id),
        production_id=str(production_id),
        actor=actor,
        aspect_ratio=aspect_ratio,
    )
    for entity, version in made:
        canon_port.create_entity(entity, version)
    p = parts.module("tool", "structure_write", "plan").plan(
        fill.structure(bd),
        production_id=str(production_id),
        canon=canon_port.entities(production_id),
        existing_episodes=structure.episodes(production_id),
        existing_scenes=structure.scene_headers(production_id),
        envelope_s=envelope_s,
        aspect_ratio=aspect_ratio,
        actor=actor,
    )
    for entity, version in p.entities:
        canon_port.create_entity(entity, version)
    if p.episodes:
        structure.upsert_episodes(p.episodes)
    numbers = {str(e["id"]): int(e["number"]) for e in p.episodes}
    by_key = {(sc.episode, sc.number): sc for sc in bd.scenes}
    for row, lines in p.scenes:
        structure.write_scene(row, lines)
        sc = by_key.get((numbers.get(str(row["episode_id"]), 0), int(row["number"])))
        if sc is not None:
            sc.row_id, sc.script_version = str(row["id"]), int(row["script_version"])
            sc.line_map = fill.line_map(sc, lines)
    structure.delete_scenes(p.delete_scene_ids)
    written = {str(r["id"]) for r, _ in p.scenes}
    for h in structure.scene_headers(production_id):  # an approved scene was kept: its row is still the scene's
        sc = by_key.get(
            (
                next(
                    (
                        int(e["number"])
                        for e in structure.episodes(production_id)
                        if str(e["id"]) == str(h["episode_id"])
                    ),
                    0,
                ),
                int(h["number"]),
            )
        )
        if sc is not None and not sc.row_id and str(h["id"]) not in written:
            sc.row_id, sc.script_version = str(h["id"]), int(h.get("script_version") or 1)
    mem = ctx.ports.memory
    rules = fill.memory_rows(bd)
    if mem is not None:
        for doc_id, entries in rules.items():
            try:
                mem.replace_from(production_id, UUID(doc_id), entries)
            except Exception:  # the production memory is an extra (schema v12): a missing table is not a failed build
                _log.warning("direction entries could not be written", exc_info=True)
    if bd.questions and payload.job_id:
        structure.upsert_questions(question_rows(payload.job_id, production_id, bd.questions))
    return {
        "canon": len(made) + len(p.entities),
        "episodes": len(p.episodes),
        "scenes": len(p.scenes),
        "scene_ids": p.scene_ids,
        "kept_approved": p.kept_approved,
        "deleted_scenes": p.delete_scene_ids,
        "direction": sum(len(v) for v in rules.values()),
        "questions": len(bd.questions),
    }


# ── the graph ──────────────────────────────────────────────────────────────────────────────────────────────────


def _text_of(ctx: RunContext, d: Row) -> tuple[str, str]:
    """The document's text and how it was read: a 'pages' reading's clean transcription, else its text layer."""
    docs = ctx.need("docs")
    if d.get("read_from") == "pages":
        read = doc_reader.load(ctx, d)
        if read is not None and read.transcription:
            from contracts.doc_read_run import transcribed_text

            return transcribed_text(read, int(d.get("page_count") or 0)), "pages"
    return docs.text(str(d["text_path"])), "text"


def build(
    ctx: RunContext, payload: DispatchPayload, *, envelope_s: int = 45, aspect_ratio: str = "16:9"
) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs = ctx.need("jobs")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    workers = get_settings().breakdown.workers

    def say(text: str) -> None:
        jobs.event(job_id, JobEventType.PROGRESS, {"text": text}, agent=AGENT)

    def read(state: State) -> State:
        jobs.stage(job_id, Stage.READ.value, "active")
        uploads = []
        for d in ctx.need("docs").documents(production_id):
            role = d.get("confirmed_role") or d.get("detected_role") or "other"
            if role not in STORY_ROLES or not d.get("text_path"):
                continue
            text, how = _text_of(ctx, d)
            uploads.append(
                {"document_id": str(d["id"]), "filename": str(d["filename"]), "text": text, "read_from": how}
            )
        jobs.stage(job_id, Stage.READ.value, "done", f"{len(uploads)} documents")
        return {"uploads": uploads}

    def breakdown(state: State) -> State:
        jobs.stage(job_id, Stage.EPISODES.value, "active")
        res = brun.create(
            [brun.Upload(**u) for u in state["uploads"]],
            calls(ctx),
            production=str(production_id),
            workers=workers,
            progress=say,
        )
        for note in res.notes:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT)
        if res.memory is None:
            return {"failed": f"The documents could not be broken down: {res.failed}."}
        store = ctx.need("breakdown")
        for s in res.sources:
            store.save_source(production_id, s.document_id, s.filename, s.model_dump(mode="json"))
        bd = res.memory
        jobs.stage(job_id, Stage.EPISODES.value, "done", f"{len({s.episode for s in bd.scenes})} episodes")
        return {"memory": bd.model_dump(mode="json")}

    def fill_node(state: State) -> State:
        if state.get("failed"):
            return {}
        jobs.stage(job_id, Stage.SCENES.value, "active")
        bd = Breakdown.model_validate(state["memory"])
        report = fill_columns(ctx, payload, bd, envelope_s=envelope_s, aspect_ratio=aspect_ratio)
        save(ctx, production_id, bd)
        rows = packet_rows(bd)
        ctx.need("breakdown").save_packets(production_id, rows)
        ready = sum(not r["waits"] for r in rows)
        jobs.event(
            job_id,
            JobEventType.AGENT_STEP,
            {
                "text": f"{report['episodes']} episodes and {report['scenes']} scenes from the breakdown; "
                f"{ready} of {len(rows)} scenes are ready to plan."
            },
            agent=AGENT,
        )
        if report["questions"]:
            jobs.event(
                job_id,
                JobEventType.WARNING,
                {
                    "text": f"{report['questions']} things the documents say differently: the earlier document "
                    "was used. Check them in the build's questions."
                },
                agent=AGENT,
            )
        jobs.stage(job_id, Stage.SCENES.value, "done", f"{report['scenes']} scenes")
        return {"report": {**report, "ready": ready}}

    g: Any = StateGraph(State)
    for name, fn in (("read", read), ("breakdown", breakdown), ("fill", fill_node)):
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_edge("read", "breakdown")
    g.add_edge("breakdown", "fill")
    g.add_edge("fill", END)
    return g.compile()


def refresh(ctx: RunContext, payload: DispatchPayload, scene_row: str) -> Row:
    """Phase 5: the one-scene refresh after a person edited a scene's script. The person's lines are the edit's
    (decision
    6): nothing here writes the scene's script or its lines; the memory, the line ids and the packet follow them."""
    production_id = payload.production_id
    assert production_id is not None
    bd, sources, _ = load(ctx, production_id)
    if bd is None:
        return {"skipped": "this production has no breakdown"}
    sc = next((s for s in bd.scenes if s.row_id == scene_row), None)
    if sc is None:
        return {"skipped": "the scene is not in the breakdown"}
    scenes = ctx.need("scenes")
    (row,) = scenes.scenes(production_id, [scene_row]) or [None]
    if row is None:
        return {"skipped": "scene deleted"}
    lines = scenes.lines(scene_row)
    by_id = {str(ln["id"]): ln for ln in lines}
    names = {e.id: e.name for e in bd.entities}
    blocks = []
    for b in row.get("script") or []:
        if b.get("kind") == "dialogue" and b.get("line_id") and str(b["line_id"]) in by_id:
            ln = by_id[str(b["line_id"])]
            blocks.append(
                {"kind": "dialogue", "speaker": str(ln.get("speaker") or ""), "text": str(ln.get("text") or "")}
            )
        else:
            blocks.append({"kind": str(b.get("kind") or "action"), "text": str(b.get("text") or "")})
    version = int(row.get("script_version") or 1)
    notes = brun.refresh_scene(
        bd, sources, sc.id, memory.blocks_as_lines(blocks, names), calls(ctx), script_version=version
    )
    sc.line_map = fill.line_map(sc, lines)
    save(ctx, production_id, bd)
    rows = packet_rows(bd, [sc.id])
    ctx.need("breakdown").save_packets(production_id, rows)
    made = inferred_canon(ctx, payload, bd)
    return {
        "scene": sc.id,
        "canon": made,
        "notes": notes,
        "waits": rows[0]["waits"] if rows else ["no packet"],
        "handover": [f.message for f in bd.findings if f.code == "continuity" and "after the edit" in f.message],
    }


def inferred_canon(ctx: RunContext, payload: DispatchPayload, bd: Breakdown) -> int:
    """After a refresh (plan/2026-11-12 §3.2): a thing the reader newly found implied joins the canon, `inferred`, the
    way the creation build's `fill_columns` adds every card. Only new names: a person's canon entry is never touched."""
    production_id = payload.production_id
    assert production_id is not None
    cards = [c for c in fill.canon_cards(bd) if c["inferred"]]
    if not cards:
        return 0
    canon_port = ctx.need("canon")
    production = ctx.need("scenes").production(production_id) or {}
    orientation = production.get("orientation")
    made = canon_rows(
        cards,
        canon_port.entities(production_id),
        production_id=str(production_id),
        actor=str(payload.actor_user_id) if payload.actor_user_id else None,
        aspect_ratio=ASPECT_RATIO[Orientation(orientation)] if orientation else "16:9",
    )
    for entity, version in made:
        canon_port.create_entity(entity, version)
    return len(made)


def packet_for(ctx: RunContext, scene_row: Row) -> tuple[Row | None, str]:
    """Step 6 then step 7 for one scene, before planning: (the packet, "") or (None, why there is none). A scene with no
    map is staged once (ONE `breakdown_stager` call, about $0.02) and the map is kept in the memory and in
    `scenes.staging` (D1). A packet made for another script version is stale: it waits for the refresh."""
    production_id = ctx.production_id
    store = ctx.ports.breakdown
    if store is None or production_id is None:
        return None, "no breakdown store"
    sid = str(scene_row["id"])
    try:
        row = store.packet(sid)
    except Exception:  # schema v21 not applied: no packet path
        _log.warning("scene_packets could not be read", exc_info=True)
        return None, "the breakdown tables are not there (schema v21)"
    if not row:
        return None, "this scene has no packet"
    if int(row.get("script_version") or 0) != int(scene_row.get("script_version") or 1):
        return None, "the script changed after the breakdown: refresh the scene's breakdown"
    if row.get("waits"):
        return None, "; ".join(row["waits"])[:300]
    got = row["packet"]
    if got.get("stage"):
        return got, ""
    bd, _, _ = load(ctx, production_id)
    sc = next((s for s in (bd.scenes if bd else []) if s.row_id == sid), None)
    if bd is None or sc is None or sc.brief is None:
        return None, "the scene is not in the breakdown"
    if not llm.models_enabled():
        return got, ""  # planned without a map, as today's path does with no model
    try:
        out = agents.build("breakdown_stager").run({"message": brun.stage_message(bd, sc.id)}, ctx)
    except Exception:  # a broken map is not a broken scene
        _log.warning("the stager failed for %s", sc.id, exc_info=True)
        return got, ""
    with _SAVING:  # scenes are planned in parallel: the map joins the memory as it is NOW, never a stale copy
        bd, _, _ = load(ctx, production_id)
        sc = next((s for s in (bd.scenes if bd else []) if s.row_id == sid), None)
        if bd is None or sc is None or sc.brief is None:
            return got, ""
        found = stage.apply(bd, sc, out)
        bd.findings = [f for f in bd.findings if not (f.code == "stage" and f.scene == sc.id)] + found
        save(ctx, production_id, bd)
    staged = fill.staging(bd, sc, script_version=sc.script_version)
    if staged is not None:
        store.set_staging(sid, staged)
    (fresh,) = packet_rows(bd, [sc.id])
    store.save_packets(production_id, [fresh])
    return (fresh["packet"], "") if not fresh["waits"] else (None, "; ".join(fresh["waits"])[:300])


def run(payload: DispatchPayload, ctx: RunContext) -> Row:
    jobs = ctx.need("jobs")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    if not llm.models_enabled():
        jobs.set(job_id, JobStatus.FAILED, error=NO_MODEL)
        return {"failed": NO_MODEL}
    refresh_of = payload.state.get("breakdown_refresh")
    if refresh_of:
        result = refresh(ctx, payload, str(refresh_of))
        jobs.finish(payload, result)
        return result
    production = ctx.need("scenes").production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    carry: Row = {"build": bool(payload.state.get("build"))}
    if carry["build"] and not settings.build.scenes:
        jobs.stage(job_id, Stage.SCENES.value, "done", "Skipped: scenes are not part of this build")
        jobs.finish(payload, {"skipped": "scenes not requested"}, {**carry, "scene_ids": []})
        return {"skipped": "scenes not requested"}
    app = build(
        ctx,
        payload,
        envelope_s=settings.default_scene_envelope_s,
        aspect_ratio=ASPECT_RATIO[Orientation(production["orientation"])],
    )
    final = app.invoke(State())
    if final.get("failed"):
        jobs.set(job_id, JobStatus.FAILED, error=final["failed"])
        return {"failed": final["failed"]}
    report = dict(final.get("report") or {})
    carry["scene_ids"] = [] if not settings.build.shots else report.get("scene_ids", [])
    result = {k: v for k, v in report.items() if k not in ("scene_ids", "deleted_scenes")}
    jobs.finish(payload, result, carry)
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeBreakdown, FakeCanon, FakeDocs, FakeJobs, FakeStructure

    payload = DispatchPayload(
        job_id=uuid4(), kind=JobKind.STRUCTURE_BUILD, actor_user_id=uuid4(), production_id=uuid4()
    )
    ports = replace(
        Ports(),
        jobs=FakeJobs(),
        structure=FakeStructure(),
        canon=FakeCanon(),
        docs=FakeDocs(),
        breakdown=FakeBreakdown(),
    )
    ctx = RunContext(production_id=payload.production_id, ports=ports)
    return build(ctx, payload)
