"""One adapter per service: build the fakes a case describes, run the engine, return what happened.

Each adapter takes the fixture's `input` and `model` and returns a raw outcome (the harness
normalises it). `engine` names which implementation runs: only `legacy` exists today. When a
system is migrated (Phase 6) its adapter gains a `graph` branch that builds the same fakes and
runs the new graph, and the same fixtures must give the same outcome.

The fakes are the ones the service tests already use, so a fixture pins what those tests
exercise, but with the whole outcome recorded and not one assertion at a time.
"""
from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any
from uuid import UUID, uuid4

from tests.parity.harness import jobs_outcome, model_calls, replies, seeded_ids, state

Adapter = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


def _legacy(engine: str) -> None:
    if engine != "legacy":
        raise NotImplementedError(f"engine {engine!r} is not built yet (plan/2026-11-03 Phase 6)")


def prose_text(episode: int | None = None) -> str:
    """The three-episode prose drama; `episode` keeps only that episode (the model cases make one call, so the order the
    parallel calls arrive in cannot matter)."""
    from tests.parity.harness import ROOT

    text = (ROOT / "tests" / "fixtures" / "prose" / "three-episode-drama.txt").read_text(encoding="utf-8")
    if episode is None:
        return text
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.upper().startswith(f"EPISODE {episode} "))
    end = next((i for i, ln in enumerate(lines) if i > start and ln.upper().startswith(f"EPISODE {episode + 1} ")),
               len(lines))
    return "\n".join(lines[start:end])


def _corpus_text(name: str) -> str:
    from tests.services.doc_ingest.conftest import CORPUS

    return (CORPUS / name).read_text(encoding="utf-8")


# ── echo ───────────────────────────────────────────────────────────────────────────────────


def echo(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from echo_service.app import handler

    from tests.services.test_echo import FakeStore, _payload

    store = FakeStore(inp.get("status", "pending"))
    if engine == "graph":
        result = handler.run_graph(_payload(inp["message"]), store)  # type: ignore[arg-type]
    else:
        _legacy(engine)
        result = handler.run(_payload(inp["message"]), store)  # type: ignore[arg-type]
    return {"result": result, "status": store.status, "events": store.events, "error": store.error}


# ── doc_ingest ─────────────────────────────────────────────────────────────────────────────


def doc_ingest(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from doc_ingest.engine import pipeline
    from doc_ingest.runtime.llm import LLM

    from tests.services.doc_ingest.conftest import FakeOpenAI, make_pdf
    from tests.services.doc_ingest.test_pipeline import CONFIG, FakeStore, _payload

    if "pdf_pages" in inp:
        data, mime = make_pdf(inp["pdf_pages"]), "application/pdf"
    else:
        data, mime = _corpus_text(inp["corpus"]).encode("utf-8"), "text/plain"
    store = FakeStore(data, inp["filename"], mime, inp.get("confirmed_role"))
    usage: list[dict[str, Any]] = []
    client = FakeOpenAI(fail_embed=bool(model.get("fail_embed"))) if model.get("client") else None
    llm = LLM(CONFIG, usage.append, client=client)
    results = []
    for _ in range(int(inp.get("deliveries", 1))):
        if engine == "graph":
            results.append(_doc_ingest_graph(_payload(), store, client, usage))
        else:
            _legacy(engine)
            results.append(pipeline.run(_payload(), store, llm))
        store.job = {"status": "pending"}
    return {"results": results, "document": store.doc, "chunks": store.chunks, "texts": store.texts,
            "job": store.job, "events": store.events, "usage": usage,
            "embed_batches": [len(b) for b in client.embed_calls] if client else None}


def _doc_ingest_graph(payload: Any, store: Any, client: Any, usage: list[dict[str, Any]]) -> dict[str, Any]:
    """The hiru_ai doc_ingest system over the legacy fakes: the store already has the DocStore methods, its download and
    upload_text become the Files port, and the function's real JobsPort carries the job contract."""
    import re
    from dataclasses import replace

    from doc_ingest.runtime.jobs import JobsPort

    from hiru_ai.core import llm as door
    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.core.llm import UsageEmbeddings
    from hiru_ai.systems.doc_ingest import graph
    from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter

    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download(bucket, path)  # type: ignore[no-any-return]

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload_text(bucket, path, data.decode("utf-8"))

    def header_reply(messages: list[Any]) -> dict[str, Any]:  # what FakeOpenAI answers a header batch
        ords = [int(m) for m in re.findall(r'<passage ord="(\d+)">', str(messages[-1].content))]
        return {"headers": [{"ord": o, "header": f"model header {o}"} for o in ords]}

    role_reply = Endless([lambda messages: {"role": "notes", "confidence": 0.7, "reason": "x"}])
    ctx = RunContext(job_id=payload.job_id, usage_sink=usage_row_filter(usage),
                     ports=replace(Ports(), jobs=JobsPort(store), docs=store, files=Files()))
    env = {"OPENAI__API_KEY": "", "OPENAI__MODEL_MEDIUM": "m-medium", "OPENAI__MODEL_LOW": "m-low",
           "OPENAI__EMBEDDING_MODEL": "embed-model", "OPENAI__EMBEDDING_DIMENSIONS": "8"}
    if client is None:
        with environment(**env):
            return graph.run(payload, ctx)  # type: ignore[no-any-return]
    with environment(**{**env, "OPENAI__API_KEY": "test-key"}), \
            scripted_models({"doc_ingest.role": list(client.replies) + role_reply,
                             "doc_ingest.headers": Endless([header_reply])},
                            {"medium": "m-medium", "low": "m-low"}), \
            door.use_embeddings(lambda phase, sink: UsageEmbeddings(phase, sink, client=client)):
        return graph.run(payload, ctx)  # type: ignore[no-any-return]


# ── canon_extract ──────────────────────────────────────────────────────────────────────────


def canon_extract(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from canon_extract.engine import pipeline
    from langgraph.checkpoint.memory import InMemorySaver

    from tests.services.canon_extract import test_canon_extract as t
    from tests.services.fakes import FakeJobs, FakeLLM

    docs = t.documents()
    for old, new in inp.get("script_replace", []):
        docs[2]["text"] = docs[2]["text"].replace(old, new)
    store = t.FakeStore(docs)
    llm = FakeLLM(replies(model), enabled=bool(model.get("enabled", False)))
    jobs = FakeJobs()
    if engine == "graph":
        return _canon_extract_graph(inp, model, store, jobs, t.payload)
    _legacy(engine)
    results = [pipeline.run(t.payload(bool(inp.get("build"))), store, jobs, llm, InMemorySaver())
               for _ in range(int(inp.get("runs", 1)))]
    return {"results": results, "jobs": jobs_outcome(jobs), "llm": model_calls(llm),
            **state(store, "entity_rows", "version_rows")}


def _canon_extract_graph(inp: dict[str, Any], model: dict[str, Any], store: Any, jobs: Any,
                         payload: Callable[[bool], Any]) -> dict[str, Any]:
    """The hiru_ai canon_extract system over the legacy fakes: the store already has the SceneStore.production, DocStore
    and CanonStore methods the graph reads, and the fake jobs are the job contract."""
    from dataclasses import replace

    from langgraph.checkpoint.memory import InMemorySaver

    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.systems.canon_extract import graph
    from tests.parity.graph_support import environment, scripted_models, usage_row_filter
    from tests.parity.harness import jobs_outcome as outcome_of

    env = {"OPENAI__API_KEY": "test-key" if model.get("enabled") else "", "OPENAI__MODEL_HIGH": "m-high",
           "OPENAI__MODEL_MEDIUM": "m-medium"}
    replies_ = model.get("replies") or {}
    routes = {"canon_extract.extract": list(replies_.get("canon", [])),
              "canon_extract.dedupe": list(replies_.get("canon_dupes", []))}
    results: list[Any] = []
    calls: list[dict[str, Any]] = []
    with environment(**env), ExitStack() as stack:
        seen = (stack.enter_context(scripted_models(routes, {"high": "m-high", "medium": "m-medium"}))
                if model.get("enabled") else None)  # a model installed at all means "a key is set"
        for _ in range(int(inp.get("runs", 1))):
            p = payload(bool(inp.get("build")))
            ctx = RunContext(production_id=p.production_id, actor_user_id=p.actor_user_id, job_id=p.job_id,
                             usage_sink=usage_row_filter([]), ports=replace(Ports(), jobs=jobs, scenes=store,
                                                                            docs=store, canon=store))
            results.append(graph.run(p, ctx, InMemorySaver()))
        schemas = {"canon_extract.extract": "canon", "canon_extract.dedupe": "canon_dupes"}
        calls = seen.llm_calls(schemas) if seen else []
    return {"results": results, "jobs": outcome_of(jobs), "llm": calls, **state(store, "entity_rows", "version_rows")}


# ── structure_build ────────────────────────────────────────────────────────────────────────


def structure_build(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from langgraph.checkpoint.memory import InMemorySaver
    from structure_build.engine import pipeline

    from tests.services.fakes import FakeJobs, FakeLLM
    from tests.services.structure_build import test_structure_build as t

    docs = [t.doc(d["filename"], d["role"], d["text"] if "text" in d else prose_text(d.get("episode")) if "prose" in d
                  else _corpus_text(d["corpus"])) for d in inp["docs"]]
    store = t.FakeStore(docs)
    if inp.get("settings"):
        settings = inp["settings"]
        store.production = lambda pid: {"id": str(pid), "orientation": "horizontal", "settings": settings}  # type: ignore[method-assign]
    llm = FakeLLM(replies(model), enabled=bool(model.get("enabled", False)))
    saver, durable = InMemorySaver(), bool(inp.get("durable", True))
    job_id = uuid4()
    jobs = FakeJobs(status="running", cursor=1)
    with ExitStack() as stack:
        if engine == "graph":
            run, schemas, seen = _structure_build_graph(stack, model, store)
        else:
            _legacy(engine)

            def run(payload: Any, jobs_: Any) -> dict[str, Any]:
                return pipeline.run(payload, store, jobs_, llm, saver, durable=durable)  # type: ignore[no-any-return]

        def go(payload: Any, jobs_: Any) -> dict[str, Any]:
            return run(payload, jobs_) if engine != "graph" else run(payload, jobs_, saver, durable)  # type: ignore[no-any-return]

        deliveries = [go(t.build_payload(job_id), jobs)]
        if inp.get("answers"):  # a person answers the open questions, then the build resumes
            deliveries.append(go(t.build_payload(job_id), jobs))  # duplicate
            for q in store.question_rows.values():
                key = q["key"].split(":")[0]
                q.update(status="answered", answer={"value": inp["answers"][key], "text": None})
            jobs.status = "running"
            deliveries.append(go(t.build_payload(job_id, resume=True), jobs))
            again = FakeJobs(status="running", cursor=1)  # the next build reuses the answers
            deliveries.append(go(t.build_payload(uuid4()), again))
            deliveries.append({"second_build_events": again.events})
    calls = model_calls(llm) if engine != "graph" else (seen.llm_calls(schemas) if seen else [])
    return {"deliveries": deliveries, "jobs": jobs_outcome(jobs), "llm": calls,
            **state(store, "episode_rows", "scene_rows", "line_rows", "question_rows", "look_rows", "canon_rows")}


def _structure_build_graph(stack: ExitStack, model: dict[str, Any], store: Any) -> tuple[Any, dict[str, str], Any]:
    """The hiru_ai structure_build system over the legacy fakes. The store has the DocStore and SceneStore.production
    methods already; two small views give it the CanonStore and StructureStore names."""
    from dataclasses import replace

    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.systems.structure_build import graph
    from tests.parity.graph_support import environment, scripted_models, usage_row_filter

    class Canon:
        def entities(self, production_id: Any) -> Any:
            return store.canon(production_id)

        def create_entity(self, entity: Any, version: Any) -> None:
            store.create_entity(entity, version)

    class Structure:
        def __getattr__(self, name: str) -> Any:
            return getattr(store, name)

        def scene_headers(self, production_id: Any) -> Any:
            return store.scenes(production_id)

    env = {"OPENAI__API_KEY": "test-key" if model.get("enabled") else "", "OPENAI__MODEL_HIGH": "m-high",
           "OPENAI__MODEL_MEDIUM": "m-medium", "OPENAI__MODEL_ULTRA": "m-ultra"}
    stack.enter_context(environment(**env))
    replies_ = model.get("replies") or {}
    routes = {"structure_build.prose": list(replies_.get("prose_scenes", [])),
              "structure_build.architect": list(replies_.get("episode_names", [])),
              "structure_build.looks": list(replies_.get("canon_looks", []))}
    seen = (stack.enter_context(scripted_models(routes, {"high": "m-high", "medium": "m-medium", "ultra": "m-ultra"}))
            if model.get("enabled") else None)
    schemas = {"structure_build.prose": "prose_scenes", "structure_build.architect": "episode_names",
               "structure_build.looks": "canon_looks"}

    def run(payload: Any, jobs: Any, saver: Any, durable: bool) -> dict[str, Any]:
        ctx = RunContext(production_id=payload.production_id, actor_user_id=payload.actor_user_id,
                         job_id=payload.job_id, usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, docs=store, canon=Canon(),
                                       structure=Structure()))
        return graph.run(payload, ctx, saver, durable=durable)  # type: ignore[no-any-return]

    return run, schemas, seen


# ── frame_render ───────────────────────────────────────────────────────────────────────────


def frame_render(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from frame_render.engine import pipeline

    from tests.services.fakes import FakeJobs
    from tests.services.frame_render import test_frame_render as t
    from tests.services.frame_render.conftest import FakePainter, FakeStore

    store = FakeStore(orientation=inp.get("orientation", "horizontal"), design=inp.get("design", True))
    shots = t.shots(store)
    for n, overrides in (inp.get("camera_overrides") or {}).items():
        shots[int(n)]["camera_overrides"] = overrides
    store.unreadable.update(inp.get("unreadable", []))
    paint = None if inp.get("painter") is None else FakePainter(**inp["painter"])
    jobs = FakeJobs()
    if "reference_entity" in inp:
        store.canon_rows[inp["reference_entity"]]["current"].update(inp.get("current", {}))
        payload = t.payload(reference_entity_id=store.canon_rows[inp["reference_entity"]]["id"])
    else:
        frame_ids = [store.add_frame(shots[n]["id"]) for n in inp["frames"]]
        payload = t.payload(frame_ids=frame_ids)
    if engine == "legacy":
        results = [pipeline.run(payload, store, jobs, paint) for _ in range(int(inp.get("deliveries", 1)))]
    else:
        results = [_frame_render_graph(payload, store, jobs, paint) for _ in range(int(inp.get("deliveries", 1)))]
    return {"results": results, "jobs": jobs_outcome(jobs),
            "painted": [{k: v for k, v in c.items()} for c in (paint.calls if paint else [])],
            "uploads": {f"{b}/{p}": d for (b, p), d in store.uploads.items()},
            **state(store, "frame_rows", "audits", "asset_writes")}


def _frame_render_graph(payload: Any, store: Any, jobs: Any, paint: Any) -> dict[str, Any]:
    """The hiru_ai frame_render system over the legacy fakes: the store already has the FrameStore, SceneStore (reads)
    and storage methods; the painter's legacy refusal becomes the port's `ImageRefused`."""
    from dataclasses import replace

    from frame_render.engine.image import RefusedError

    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.core.ports import ImageRefused
    from hiru_ai.systems.frame_render import graph

    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_reference(path)  # type: ignore[no-any-return]

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    def images(prompt: str, aspect: str, references: list[Any]) -> Any:
        try:
            return paint(prompt, aspect, references)
        except RefusedError as exc:
            raise ImageRefused(str(exc)) from exc

    ctx = RunContext(production_id=payload.production_id, job_id=payload.job_id,
                     ports=replace(Ports(), jobs=jobs, scenes=store, frames=store, files=Files(),
                                   images=None if paint is None else images))
    return graph.run(payload, ctx)  # type: ignore[no-any-return]


# ── script_split ───────────────────────────────────────────────────────────────────────────


def script_split(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from script_split.engine import pipeline

    from contracts.jobs import JobKind
    from tests.services.fakes import FakeJobs, FakeLLM
    from tests.services.script_split import test_split as t

    scenes = [t.scene_from_fixture(n) for n in inp["scenes"]]
    for n, fields in (inp.get("scene_fields") or {}).items():
        scenes[int(n)][0].update(fields)
    store = t.FakeStore(scenes, settings=inp.get("settings"))
    llm = FakeLLM(replies(model), enabled=bool(model.get("enabled", False)))
    jobs = FakeJobs(status=inp.get("job_status", "pending"), cursor=int(inp.get("cursor", 0)))
    task_state = dict(inp.get("state") or {})
    if task_state.get("scene_ids") == "all":
        task_state["scene_ids"] = [s["id"] for s, _ in scenes]
    chain = [JobKind(k) for k in inp["pipeline"]] if inp.get("pipeline") else None
    payload = t.payload(task_state, chain, int(inp.get("cursor", 0)))
    if engine == "legacy":
        result = pipeline.run(payload, store, jobs, llm)
        calls = model_calls(llm)
    else:
        result, calls = _script_split_graph(payload, store, jobs, model)
    return {"result": result, "jobs": jobs_outcome(jobs), "llm": _critics_in_lens_order(calls),
            **state(store, "shots", "line_rows", "scene_rows", "episode_status")}


def _critics_in_lens_order(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The three critics are asked at the same time, so the order their calls arrive in means nothing: each run of
    them is put in lens order (both engines), and the rest of the calls keep theirs."""
    out: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for call in [*calls, {"schema": ""}]:
        if call["schema"] == "shot_review":
            run.append(call)
            continue
        out += sorted(run, key=lambda c: c["phase"])
        run = []
        out.append(call)
    return out[:-1]


def _script_split_graph(payload: Any, store: Any, jobs: Any, model: dict[str, Any],
                        budget_s: float | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The hiru_ai script_split system over the legacy fakes: the store has the SceneStore and SplitStore methods
    already (it has no locations, so a small view adds none)."""
    from dataclasses import replace

    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.systems.script_split import graph
    from tests.parity.graph_support import environment, scripted_models, usage_row_filter

    class Split:
        def __getattr__(self, name: str) -> Any:
            return getattr(store, name)

        def locations(self, production_id: Any) -> Any:
            return []

    replies_ = model.get("replies") or {}
    review = list(replies_.get("shot_review", []))  # one queue for the three critics, as the legacy fake had
    routes = {"script_split.beats": list(replies_.get("beat_screen", [])),
              "script_split.reading": list(replies_.get("scene_reading", [])),
              "script_split.staging": list(replies_.get("scene_staging", [])),
              "script_split.plan": list(replies_.get("shot_plan", [])),
              **{f"script_split.critic.{lens}": review for lens in ("coverage", "emotion", "editor")}}
    schemas = {"script_split.beats": "beat_screen", "script_split.reading": "scene_reading",
               "script_split.staging": "scene_staging", "script_split.plan": "shot_plan",
               **{f"script_split.critic.{lens}": "shot_review" for lens in ("coverage", "emotion", "editor")}}
    env = {"OPENAI__API_KEY": "test-key" if model.get("enabled") else "", "OPENAI__MODEL_HIGH": "m-high",
           "OPENAI__MODEL_MEDIUM": "m-medium"}
    ctx = RunContext(production_id=payload.production_id, actor_user_id=payload.actor_user_id, job_id=payload.job_id,
                     usage_sink=usage_row_filter([]), ports=replace(Ports(), jobs=jobs, scenes=store, split=Split()))
    with ExitStack() as stack:
        stack.enter_context(environment(**env))
        seen = (stack.enter_context(scripted_models(routes, {"high": "m-high", "medium": "m-medium"}))
                if model.get("enabled") else None)
        extra = {} if budget_s is None else {"budget_s": budget_s}
        result = graph.run(payload, ctx, **extra)
        calls = seen.llm_calls(schemas) if seen else []
    return result, calls


# ── shot_producer ──────────────────────────────────────────────────────────────────────────


def shot_producer(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from shot_producer.engine import pipeline

    from tests.services.fakes import FakeJobs
    from tests.services.shot_producer import test_shot_producer as t
    from tests.services.shot_producer.conftest import FakeStore, ProducerLLM, dp_answer, fixture_scene

    scene, lines, rows = fixture_scene(int(inp.get("scene", 0)))
    for number, fields in (inp.get("rows") or {}).items():  # columns to set on a shot's stored row, by shot number
        next(r for r in rows if r["number"] == int(number)).update(fields)
    store = FakeStore(scene, lines, rows)
    for number in inp.get("accepted_frames", []):  # shot numbers with an accepted first frame
        shot = next(r for r in rows if r["number"] == number)
        store.frames[shot["id"]] = {"id": str(uuid4()), "shot_id": shot["id"], "pins": {}}
    scripted = replies(model)
    dp_numbers = (model.get("dp_answer") or {}).get("scene_design")  # the DoP's answer is built by the shared helper
    if dp_numbers is not None:
        scripted["scene_design"] = lambda s, u: dp_answer(dp_numbers)
    llm = ProducerLLM(scripted, enabled=bool(model.get("enabled", False)))
    jobs = FakeJobs()
    results = []
    seen = None
    with ExitStack() as stack:
        if engine == "graph":
            run, schemas, seen = _shot_producer_graph(stack, model, store, dp_numbers)
        else:
            _legacy(engine)

            def run(payload: Any, jobs_: Any) -> dict[str, Any]:
                return pipeline.run(payload, store, jobs_, llm)  # type: ignore[no-any-return]

        for run_state in inp["runs"]:
            st = dict(run_state)
            st["shot_ids"] = [next(r["id"] for r in rows if r["number"] == n) for n in st.pop("shots", [])]
            st["scene_ids"] = [scene["id"]]
            results.append(run(t.payload(**st), jobs))
    calls = model_calls(llm) if engine != "graph" else (seen.llm_calls(schemas) if seen else [])
    return {"results": results, "jobs": jobs_outcome(jobs), "llm": calls,
            **state(store, "shot_rows", "prompts", "audits", "intents", "scene_row", "technique_queries")}


def _shot_producer_graph(stack: ExitStack, model: dict[str, Any], store: Any, dp_numbers: Any
                         ) -> tuple[Any, dict[str, str], Any]:
    """The hiru_ai shot_producer system over the legacy fakes: the store has the SceneStore, ProducerStore and Search
    (`techniques`) methods already."""
    from dataclasses import replace

    from langchain_core.embeddings import Embeddings

    from hiru_ai.core import llm as door
    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.systems.shot_producer import graph
    from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter
    from tests.services.shot_producer.conftest import dp_answer

    class Vectors(Embeddings):  # what the legacy ProducerLLM.embed answers
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 4 for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [0.1] * 4

    env = {"OPENAI__API_KEY": "test-key" if model.get("enabled") else "", "OPENAI__MODEL_HIGH": "m-high",
           "OPENAI__MODEL_MEDIUM": "m-medium"}
    stack.enter_context(environment(**env))
    replies_ = model.get("replies") or {}
    scene_replies: Any = (Endless([lambda messages: dp_answer(dp_numbers)]) if dp_numbers is not None
                          else list(replies_.get("scene_design", [])))
    routes = {"shot_producer.intent": list(replies_.get("shot_intent", [])),
              "shot_producer.craft": list(replies_.get("craft_problems", [])),
              "shot_producer.scene": scene_replies,
              "shot_producer.critique": list(replies_.get("design_review", []))}
    schemas = {"shot_producer.intent": "shot_intent", "shot_producer.craft": "craft_problems",
               "shot_producer.scene": "scene_design", "shot_producer.critique": "design_review"}
    seen = None
    if model.get("enabled"):
        seen = stack.enter_context(scripted_models(routes, {"high": "m-high", "medium": "m-medium"}))
        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))

    def run(payload: Any, jobs: Any) -> dict[str, Any]:
        ctx = RunContext(production_id=payload.production_id, actor_user_id=payload.actor_user_id,
                         job_id=payload.job_id, usage_sink=usage_row_filter([]),
                         ports=replace(Ports(), jobs=jobs, scenes=store, producer=store, search=store))
        return graph.run(payload, ctx)  # type: ignore[no-any-return]

    return run, schemas, seen


# ── director_chat ──────────────────────────────────────────────────────────────────────────


def director_chat(inp: dict[str, Any], model: dict[str, Any], engine: str) -> dict[str, Any]:
    from director_chat.engine import turn

    from contracts.director import TurnPayload
    from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore, fixture_scene, tool_call

    board = [{**b, "persona": {"id": str(uuid4()), **b["persona"]}} for b in inp.get("board", [])]
    store = FakeStore(*fixture_scene(int(inp.get("scene", 0))), board=board)
    store.scene_row.update(inp.get("scene_fields") or {})
    llm = DirectorLLM(replies(model), enabled=bool(model.get("enabled", False)),
                      tool_script=[_assistant(m, tool_call) for m in model.get("tool_script", [])],
                      reply=model.get("reply", "Done. S02 now holds on Nimal."))
    events: list[tuple[str, dict[str, Any]]] = []
    seen = None
    thread = uuid4() if inp.get("one_thread") else None  # one conversation: a later message can confirm an earlier card
    with ExitStack() as stack:
        run: Any = turn.run
        if engine == "graph":
            run, schemas, seen = _director_chat_graph(stack, model, store)
        else:
            _legacy(engine)
        for message in inp["messages"]:
            scene_id = UUID(store.scene_row["id"]) if not inp.get("gone") else uuid4()
            req = TurnPayload(production_id=PID, scene_id=scene_id, thread_id=thread or uuid4(), actor_user_id=uuid4(),
                              actor_name="Dee Director", can_edit=inp.get("can_edit", True),
                              can_edit_script=inp.get("can_edit_script", inp.get("can_edit", True)),
                              message=message, user_message_id=uuid4())
            events += [(name, data) for name, data in run(req, store, llm)]
    calls = model_calls(llm) if engine != "graph" else (seen.llm_calls(schemas) if seen else [])
    return {"events": [{"event": n, "data": d} for n, d in events], "llm": calls,
            **state(store, "saved", "message_rows", "audits", "memory_rows", "pending_rows")}


def _director_chat_graph(stack: ExitStack, model: dict[str, Any], store: Any) -> tuple[Any, dict[str, str], Any]:
    """The hiru_ai director_chat system over the legacy fakes: the store has the SceneStore and DirectorStore methods
    already."""
    from dataclasses import replace

    from langchain_core.embeddings import Embeddings
    from langchain_core.messages import AIMessage

    from hiru_ai.core import llm as door
    from hiru_ai.core.context import Ports, RunContext
    from hiru_ai.systems.director_chat import graph
    from tests.parity.graph_support import Endless, environment, scripted_models, usage_row_filter

    class Vectors(Embeddings):  # what the legacy DirectorLLM.embed answers
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 4 for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [0.1] * 4

    env = {"OPENAI__API_KEY": "test-key" if model.get("enabled") else "", "OPENAI__MODEL_HIGH": "m-high",
           "OPENAI__MODEL_MEDIUM": "m-medium"}
    stack.enter_context(environment(**env))
    replies_ = model.get("replies") or {}
    script = [_assistant_message(m) for m in model.get("tool_script", [])]
    reply = model.get("reply", "Done. S02 now holds on Nimal.")

    def answer(messages: list[Any]) -> Any:  # the scripted assistant messages in order, then the plain reply
        return script.pop(0) if script else AIMessage(content=reply)

    routes: dict[str, Any] = {
        "director.conduct": list(replies_.get("turn_plan", [])),
        "director.options": list(replies_.get("chat_options", [])),
        "director.translate": list(replies_.get("dialogue_translation", [])),
        **{f"director.{craft}": list(replies_.get(f"{craft}_ops", []))
           for craft in ("cinematography", "timing", "sound", "continuity")},
        "director.advisor": list(replies_.get("advisor_view", [])),
        "director.answer": Endless([answer]), "director.reply": Endless([reply])}
    schemas = {"director.conduct": "turn_plan", "director.options": "chat_options",
               "director.translate": "dialogue_translation", "director.advisor": "advisor_view",
               "director.answer": "tools", "director.reply": "stream",
               **{f"director.{c}": f"{c}_ops" for c in ("cinematography", "timing", "sound", "continuity")}}
    seen = None
    if model.get("enabled"):
        seen = stack.enter_context(scripted_models(routes, {"high": "m-high", "medium": "m-medium"}, chunk_at=10,
                                                 stream_phase="director.reply"))
        stack.enter_context(door.use_embeddings(lambda phase, sink: Vectors()))

    def run(req: Any) -> Any:
        ctx = RunContext(production_id=req.production_id, actor_user_id=req.actor_user_id,
                         usage_sink=usage_row_filter([]), ports=replace(Ports(), scenes=store, director=store))
        return graph.run(req, ctx)

    return (lambda req, store_, llm_: run(req)), schemas, seen


def _assistant_message(message: dict[str, Any]) -> Any:
    from langchain_core.messages import AIMessage

    calls = [{"name": c["name"], "args": json.loads(c.get("arguments", "{}")), "id": f"call_{c['name']}",
              "type": "tool_call"}
             for c in message.get("tool_calls", [])]
    return AIMessage(content=message.get("content") or "", tool_calls=calls)


def _assistant(message: dict[str, Any], tool_call: Callable[..., Any]) -> Any:
    from types import SimpleNamespace

    calls = [tool_call(c["name"], c.get("arguments", "{}")) for c in message.get("tool_calls", [])]
    return SimpleNamespace(content=message.get("content"), tool_calls=calls or None)


ADAPTERS: dict[str, Adapter] = {
    "echo": echo,
    "doc_ingest": doc_ingest,
    "canon_extract": canon_extract,
    "structure_build": structure_build,
    "frame_render": frame_render,
    "script_split": script_split,
    "shot_producer": shot_producer,
    "director_chat": director_chat,
}


# Imported before ids are seeded: the test modules draw module-level ids (a production id) when first
# imported, and that must not shift the ids a run draws.
WARM = {
    "echo": ["echo_service.app.handler", "tests.services.test_echo"],
    "doc_ingest": ["doc_ingest.engine.pipeline", "doc_ingest.runtime.llm", "tests.services.doc_ingest.conftest",
                   "tests.services.doc_ingest.test_pipeline"],
    "canon_extract": ["canon_extract.engine.pipeline", "langgraph.checkpoint.memory",
                      "tests.services.canon_extract.test_canon_extract"],
    "structure_build": ["structure_build.engine.pipeline", "langgraph.checkpoint.memory",
                        "tests.services.structure_build.test_structure_build"],
    "frame_render": ["frame_render.engine.pipeline", "tests.services.frame_render.test_frame_render"],
    "script_split": ["script_split.engine.pipeline", "tests.services.script_split.test_split"],
    "shot_producer": ["shot_producer.engine.pipeline", "tests.services.shot_producer.test_shot_producer"],
    "director_chat": ["director_chat.engine.turn", "tests.services.director_chat.conftest", "contracts.director"],
}


def run_case(service: str, inp: dict[str, Any], model: dict[str, Any], engine: str = "legacy") -> dict[str, Any]:
    """Run one case with repeatable ids. The only entry point the recorder and the replay test use."""
    for module in WARM[service]:
        importlib.import_module(module)
    with seeded_ids():
        return ADAPTERS[service](inp, model, engine)
