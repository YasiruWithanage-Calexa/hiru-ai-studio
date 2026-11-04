# One AI package, built from parts you can add and remove: plan

Status: proposed (2026-11-03). Nothing in this plan is built yet. Decisions marked **(default)** in §10 are
the assumptions this plan is written on; change them before Phase 0 starts.

## 1. The goal

Agents, tools, knowledge bases, panels and whole systems must be **independent parts** that a person can add,
remove, swap or rewire without touching any other part. The stack is the current industry standard:
**LangChain 1.x** (models, prompts, tools, `create_agent`, middleware), **LangGraph 1.x** (graphs, subgraphs,
checkpoints, interrupts, streaming) and **LiteLLM** (one model gateway: tiers, retries, fallbacks, usage).

Success means:

| I want to… | It takes… |
|---|---|
| add an agent | one new folder (`hiru-ai new agent <id>` writes it), no edits elsewhere |
| put an agent on a panel | one line in the panel's `component.yaml` |
| remove an agent | delete its folder; `hiru-ai validate` lists every reference that must go |
| switch an agent off for a while | `status: disabled` in its manifest (or an env overlay) |
| add or remove a tool | one folder; agents list tools by id |
| give an agent a different model | `model: smart` → `model: fast` in its manifest, or edit `models.yaml` |
| add a new flow (system) | one folder under `systems/` plus a 20-line Cloud Run handler |
| test one part alone | `hiru-ai run agent translator --input case.json`, and its own tests in its folder |

## 2. What the code does today

- 8 Cloud Run functions under `src/services/` (≈10.5k lines of engine code). Each one is a closed box:
  `engine/` (logic), `runtime/` (LLM wrapper, config, REST store, checkpoint), `app/handler.py` (HTTP).
- The isolation rule (`tests/test_isolation.py`, `deploy-functions.yml` "service + contracts only") forbids
  sharing anything except `contracts`. So `runtime/llm.py`, `config.py`, `store.py`, `rest.py` and
  `checkpoint.py` exist **once per service** (up to 8 copies each).
- Agents are not units. Their charters, prompts, schemas and call code are spread across engine files:
  `director_chat/engine/agents.py` holds four crafts as dict entries (`ALLOWED`, `CHARTER`), the 1,092-line
  `turn.py` mixes orchestration, persistence and rules, and the critics in `script_split/engine/critic.py` share one file.
- LangGraph 1.2.16 is already used in `structure_build` and `canon_extract` (StateGraph, Postgres checkpoint,
  `interrupt()` for questions). The other five call OpenAI directly through their own wrapper.
- The API has its own model wrapper (`api/services/ai.py`) and retrieval (`api/services/retrieval.py`).
- The knowledge is files in `src/knowledge_base/` (craft, rules, guides, cinematography CSVs, techniques),
  ingested by `scripts/ingest_knowledge.py`, which borrows `doc_ingest`'s chunker.

Why parts can't be added or removed today: there is no unit called "agent" or "tool" with an id, so the only
way to wire something is to import it, and the import rule stops sharing.

## 3. What the industry does now (and what we take)

| Source / practice | What we take |
|---|---|
| **LangChain 1.x**: `create_agent` is the one agent builder; **middleware** wraps each model and tool call (before/after model, wrap tool call, human-in-the-loop, fallback, summarisation, PII) | Cross-cutting rules (usage rows, "document text is data", absent-safe, language rule) become middleware that a manifest switches on. They are never copied into each agent. |
| **LangGraph 1.x**: durable execution (checkpoint per node), subgraphs as nodes, `Send` (fan-out), `Command` (route plus update), `interrupt()` (person in the loop), `context_schema` / `Runtime` for injected dependencies, `Store` for cross-thread memory, `stream_mode="custom"` | Panels are subgraphs, systems are top-level graphs, and dependencies come through the runtime context (no globals). Pending cards and questions become `interrupt()`, and `thread_id = job_id` makes retries resume where they stopped. |
| **LiteLLM Router** via `langchain-litellm` (`ChatLiteLLMRouter`): model groups, retries, fallbacks, timeouts, cost/usage callbacks | Tiers (`fast`, `smart`, `vision`, `embed`) are LiteLLM model groups in one `models.yaml`. One success callback writes the `token_usage` row. |
| **Anthropic, "Building effective agents"**: prefer simple, composable workflows (chain, route, parallelise, orchestrator-workers, evaluator-optimizer) over free-roaming agents | A small **pattern library** (§5.5) of those shapes. Most of our "agents" are one typed call and stay that way; tool-loop agents only where a loop earns its place. |
| **12-Factor Agents**: own your prompts, own your control flow, small focused agents, state as data, pause/resume via APIs | Prompts are files in the agent's folder, and control flow is graph code we own. Deterministic rules (kernel score, timing, staging) stay code, not model calls. |
| **Plugin architecture / ports and adapters**: components register by id; infrastructure sits behind interfaces | A registry plus `component.yaml` manifests; `ports.py` protocols with `adapters/` (Supabase REST, storage, image API) injected at the edge. |
| **Architecture fitness functions** (`import-linter` layer and independence contracts) | CI fails if a layer imports a higher one or if two siblings (two agents, two tools…) import each other. |
| **Eval-driven development**, OpenTelemetry GenAI conventions | Every agent folder carries its eval cases. Traces are tagged with component id, version and prompt hash. Existing retrieval thresholds stay the gate. |

Library versions in this repo today: `langgraph==1.2.16`, `langgraph-checkpoint-postgres==3.2.0`. The current
`langchain` (1.4.x), `langchain-core` (1.5.x), `langchain-litellm` (≥0.11) and `litellm` versions come from
secondary sources and **must be read from PyPI in Phase 0** before they are pinned.

## 4. The design in one picture

```
src/libs/
├── contracts/                    # unchanged: pydantic + stdlib, the shared data shapes
└── hiru_ai/                      # NEW: the one AI package, installed like contracts
    ├── core/                     # L0  foundation, knows no component
    │   ├── settings.py           #     pydantic-settings, get_settings()
    │   ├── models.yaml           #     tiers -> LiteLLM model groups, fallbacks, retries, timeouts
    │   ├── llm.py                #     get_llm("fast"|"smart"|"vision"), get_embeddings()
    │   ├── usage.py              #     LiteLLM callback -> token_usage row (component id, prompt hash)
    │   ├── context.py            #     RunContext: production scope, actor, job id, ports (injected)
    │   ├── ports.py              #     Protocols: SceneStore, DocStore, Files, ImageGen, Jobs…
    │   ├── checkpoint.py         #     Postgres saver (Supabase) / in-memory saver
    │   ├── registry.py           #     discover(), get(kind, id), refs(), validate()
    │   ├── manifest.py           #     pydantic schema of component.yaml
    │   ├── prompts.py            #     load prompt files, static-first, hash
    │   ├── middleware/           #     usage, untrusted_text, absent_safe, language_guard, hitl, retry
    │   ├── patterns/             #     reusable graph shapes (see §5.5)
    │   └── telemetry.py          #     logging + tracing
    ├── adapters/                 # infrastructure behind core/ports.py (only the edge imports these)
    │   ├── supabase_rest.py
    │   ├── storage.py
    │   └── images.py
    ├── rag/                      # L1  retrieval primitives
    │   ├── embeddings.py
    │   ├── retrievers/           #     match_chunks (pgvector), keyword, hybrid
    │   └── rerankers.py
    ├── knowledge_bases/          # L2  the data: one folder per corpus
    │   ├── craft/                #     sources/  ingest.py  component.yaml (chunking, embed tier, corpus)
    │   ├── cinematography/
    │   ├── rules/
    │   ├── guides/
    │   ├── techniques/
    │   └── production_docs/      #     user uploads (today's doc_ingest)
    ├── tools/                    # L3  atomic actions a model may call
    │   └── <tool_id>/            #     tool.py  component.yaml  tests/
    ├── steps/                    # L3  deterministic graph nodes, no model (kernel score, settle, ripple…)
    │   └── <step_id>/
    ├── agents/                   # L4  one focused agent per folder
    │   └── <agent_id>/           #     agent.py  schema.py  prompts/  component.yaml  evals/  tests/
    ├── panels/                   # L5  groups of agents (subgraphs)
    │   └── <panel_id>/           #     graph.py  state.py  component.yaml  tests/
    ├── systems/                  # L6  full flows (top-level graphs), one per product job
    │   └── <system_id>/          #     graph.py  state.py  routing.py  component.yaml  tests/
    └── cli/                      #     hiru-ai new | list | validate | run | graph | remove | catalog

src/services/<name>/              # Cloud Run functions become thin
├── main.py
└── app/handler.py                # job contract: idempotency, build RunContext, run system, report

src/api/                          # imports hiru_ai.core / rag / systems (no own model wrapper)
```

Layer order (each may import only layers below it, and `contracts`):
`core → rag → knowledge_bases → tools, steps → agents → panels → systems`. `adapters` import only `core` and
`contracts` and are imported **only** by the composition roots (`src/services/*/app`, `src/api`, `cli`).

## 5. How independence is achieved

### 5.1 Every part is a folder with a manifest

```yaml
# hiru_ai/agents/translator/component.yaml
id: translator
kind: agent
version: 2
summary: Writes a requested translation of dialogue; staged as a card the person accepts.
status: active                 # active | experimental | disabled
model: smart                   # tier name from core/models.yaml
shape: structured              # structured = one typed call | react = create_agent tool loop
input: translator.schema:Input
output: translator.schema:Output
prompts: { system: prompts/system.md }
tools: []                      # tool ids, resolved through the registry
knowledge: []                  # knowledge base ids
middleware: [usage, untrusted_text, absent_safe]
writes_dialogue: true          # language_guard: only agents with this flag may write a line
owner: director
```

```yaml
# hiru_ai/panels/director_board/component.yaml
id: director_board
kind: panel
pattern: board                 # fan-out specialists -> settle by ownership -> advisor review
members:
  - { agent: cinematographer, owns: [set, set_join, beat.set, insert, split] }
  - { agent: editor,          owns: [split, merge, regroup] }
  - { agent: sound_designer,  owns: [set] }
  - { agent: continuity,      owns: [beat.set, set_join] }
settle: step:board_settle
review: [agent:advisor]
```

Today's `ALLOWED` and `CHARTER` dicts become this list. **Adding a "lighting" craft** = `hiru-ai new agent
lighting`, write its charter in `prompts/system.md`, add one `members:` line.

### 5.2 A registry, never a sibling import

- `registry.discover()` reads every `component.yaml` under the layer folders at start-up and imports a part's
  code **lazily**, the first time it is used (cold starts stay small).
- Code asks for parts by id: `registry.agent("translator")`, `registry.tools(["scene_read", "timing_check"])`.
  An agent never imports another agent, a panel never imports an agent module, a system never imports a panel module.
- `import-linter` makes this a hard rule (§5.8).

### 5.3 Typed inputs and outputs, mapped at the seam

- Each agent declares `Input` / `Output` pydantic models (or points at `contracts`). It knows nothing about
  the panel's state.
- The panel or system maps its state into the agent's input and the agent's output back into state
  (`input_map` / `output_map` in code, checked by `hiru-ai validate`). The same agent therefore works in any panel.
- Agent-to-agent data is always typed. No free-text hand-offs between agents.

### 5.4 Dependencies are injected, not imported

- LangGraph `context_schema=RunContext` carries the production scope, actor, job id, usage context and the
  **ports** (`SceneStore`, `DocStore`, `ImageGen`…). Tools read them from `ToolRuntime.context`.
- The composition root (function handler / API / CLI / tests) builds `RunContext` with real adapters or fakes.
  Swapping Supabase REST for something else touches `adapters/` only.
- Search scope still comes from the API's trusted data in `RunContext`, never from model output (existing rule).

### 5.5 Pattern library: the common shapes, written once

`core/patterns/` holds tested builders that panels configure instead of re-coding:

| Pattern | Shape (LangGraph) | Used by |
|---|---|---|
| `sequential` | A → B → C | doc ingest steps |
| `fanout` | `Send` to N members in parallel → reducer | specialists, critics |
| `board` | fanout → ownership settle step → review | director board |
| `critics_judge` | fanout critics write notes → **code** judge picks | script-split plan review (`kernel_score`) |
| `generate_critique` | writer ⇄ critic, max rounds, stop rule | shot critique, structure prose |
| `router` | classify → `Command(goto=…)` | conductor (which flow a chat turn needs) |
| `supervisor` | LLM supervisor delegates to member agents as tools | reserved; not needed today |
| `human_gate` | `interrupt()` → resume with the person's answer | pending cards, structure questions, translation |

A new shape that no pattern fits is written as plain LangGraph in the panel's `graph.py`. Patterns are a
convenience, not a cage.

### 5.6 Middleware: cross-cutting rules, attached by name

| Middleware | Enforces (existing CLAUDE.md rule) |
|---|---|
| `usage` | a `token_usage` row per call (via the LiteLLM callback, tagged with component id, version, prompt hash) |
| `untrusted_text` | uploaded document text is wrapped in tags and labelled as data, never instructions |
| `absent_safe` | no key or a failed call degrades (fallback value or rules-only path), never errors |
| `language_guard` | dialogue keeps its language; only parts with `writes_dialogue: true` may change a line |
| `static_first` | asserts the prompt's static prefix is byte-identical across calls (cache hits) |
| `hitl` | tool calls that change the script stop for a person (LangChain HITL middleware) |
| `retry` / `fallback` | model-level retries and fallbacks (LiteLLM Router; LangChain fallback middleware for `react` agents) |

### 5.7 Deterministic logic is a first-class part (`steps/`)

Kernel scoring, board settle, ripple, refusals screening, bridges, the staging checks, timing fit and
serialisation are **steps**: graph nodes with a manifest, typed input/output and no model. Most already lean
on `contracts` (`sceneplan`, `timing`, `bridges`, `stagemap`); the steps wrap them. The rule "model critics
write notes, the kernel score in code picks" becomes visible in every graph: critics are agents and the judge is a step.

### 5.8 Guard rails in CI

- **import-linter** contracts:
  - *layers*: `systems > panels > agents > (tools | steps) > knowledge_bases > rag > core`;
  - *independence*: each `agents.*`, `tools.*`, `steps.*`, `panels.*`, `systems.*` sibling is independent;
  - *forbidden*: nothing in `hiru_ai` (except composition roots) imports `adapters`; `contracts` stays pure;
    `src/services/*` imports only `hiru_ai`, `contracts` and its own `app`.
- `hiru-ai validate`: every id resolves, no part references a disabled or missing part, schemas line up at each
  mapping, no cycles, every agent has a prompt and at least one eval case, `writes_dialogue` limited to the approved list.
- **Generated contract tests**: pytest runs over the registry. Every agent builds and answers a fake model with a
  valid `Output`, every tool validates its schema, every panel and system compiles, and each graph's Mermaid
  drawing is snapshot-tested (a wiring change shows up in review).
- Tests live **in the part's folder**, so deleting a part deletes its tests. `tests/` keeps API, contracts,
  cross-system and eval tests.

### 5.9 Models through LiteLLM, OpenAI only

```yaml
# hiru_ai/core/models.yaml (shape)
tiers:
  fast:   { group: openai-fast,  fallbacks: [], timeout_s: 60,  retries: 2 }
  smart:  { group: openai-smart, fallbacks: [openai-fast], timeout_s: 120, retries: 2 }
  vision: { group: openai-vision }
  embed:  { group: openai-embed }
router:
  model_list:            # LiteLLM Router deployments; models read from settings, keys from env
    - { model_name: openai-fast,  litellm_params: { model: "openai/${OPENAI__FAST_MODEL}" } }
    - { model_name: openai-smart, litellm_params: { model: "openai/${OPENAI__SMART_MODEL}" } }
```

- `get_llm(tier)` returns a LangChain chat model (`ChatLiteLLMRouter`), so everything LangChain offers works
  (`with_structured_output`, tools, streaming). Strict JSON schema output is kept.
- **The whole stack talks to `get_llm`, never to LiteLLM or OpenAI directly.** If the Phase 0 spike shows
  LiteLLM costs too much cold start, `get_llm` can return `ChatOpenAI` instead and nothing else changes.
- Adding a non-OpenAI provider stays a person's decision (CLAUDE.md). It becomes a `models.yaml` edit, not a code change.

## 6. Where today's code goes

| Today | Becomes |
|---|---|
| 7× `runtime/llm.py`, `api/services/ai.py` | `core/llm.py` + `core/usage.py` |
| 7× `runtime/config.py`, `api/config.py` AI part | `core/settings.py` + `models.yaml` |
| `runtime/checkpoint.py` (2) | `core/checkpoint.py` |
| `runtime/store.py`, `runtime/rest.py`, `runtime/jobs.py` | `core/ports.py` + `adapters/` (jobs stay in each handler) |
| `api/services/retrieval.py` | `rag/retrievers/hybrid.py` + `knowledge_bases/*` |
| `src/knowledge_base/*`, `scripts/ingest_knowledge.py` | `knowledge_bases/<corpus>/sources` + `ingest.py`, `hiru-ai ingest <kb>` |
| **doc_ingest** `chunking`, `context`, `extract`, `roles`, `pipeline` | steps `chunk`, `extract_text`; agents `chunk_contextualiser`, `role_classifier`; system `doc_ingest` |
| **canon_extract** `model`, `rules`, `write`, `pipeline` | agent `canon_extractor`; step `canon_rules`; tool `canon_write`; system `canon_extract` |
| **structure_build** `analyse`, `architect`, `looks`, `prose`, `write`, `pipeline` | agents `analyst`, `architect`, `look_drafter`, `prose_writer`; tool `structure_write`; panel `structure_draft`; system `structure_build` (keeps `human_gate` questions) |
| **script_split** `beats`, `planner`, `reading`, `staging`, `critic`, `pipeline` | agents `beat_finder`, `scene_planner`, `scene_reader`, `stager`, critics `coverage_critic`, `emotion_critic`, `editor_critic`; step `kernel_score`; panel `plan_review` (`critics_judge`); system `script_split` |
| **shot_producer** `intent`, `shots`, `continuity`, `critique`, `feeling`, `techniques`, `model`, `schema`, `serialize`, `pipeline` | agents `shot_intent`, `shot_writer`, `continuity_checker`, `shot_critic`; steps `feeling`, `serialize`; tool `technique_lookup` (KB `techniques`); panel `shot_review` (`generate_critique`); system `shot_producer` |
| **frame_render** `image`, `inspect`, `pipeline` | tool `image_generate`; agent `frame_inspector`; system `frame_render` |
| **director_chat** `agents` (4 crafts, board, advisors), `conductor`, `choice`, `options`, `proposals`, `refusals`, `ripple`, `translate`, `kernel`, `loop`, `turn`, `tools`, `pending` | agents `cinematographer`, `editor`, `sound_designer`, `continuity`, `advisor`, `conductor`, `translator`, `options_writer`, `reply_writer`; steps `board_settle`, `ripple`, `refusal_screen`, `scene_kernel`, `verbatim_check`; tools from `engine/tools.py` one per folder; panel `director_board`; system `director_chat` (router + `human_gate` for pending cards, streamed with `stream_mode="custom"`) |
| **echo** | system `echo` (the template; first one migrated) |

`turn.py` (1,092 lines) is split along the seams above: orchestration → system graph, persistence → tool,
rules → steps, model calls → agents.

## 7. Phases

Each phase ends green on: `ruff check src tests scripts`, `mypy` (package plus each function), `pytest -q`,
`lint-imports`, `hiru-ai validate`, and `scripts/eval_retrieval.py --runs 3` (hybrid) when retrieval was touched.
Each phase updates `plan/2026-11-03/IMPLEMENTED.md`. Old and new code live side by side until Phase 8, with no big-bang switch.

### Phase 0: groundwork and safety net (no behaviour change)
1. Read current versions from PyPI; pin `langchain`, `langchain-core`, `langchain-litellm`, `litellm`, `langgraph`,
   `langgraph-checkpoint-postgres` exactly, with hashes, in a `hiru_ai` requirements set.
2. **Spike in one throwaway function**: cold start and zip size with LiteLLM vs `langchain-openai`; strict
   `json_schema` structured output through `ChatLiteLLMRouter`; OpenAI prompt-cache hits preserved;
   usage callback numbers equal today's `token_usage` rows. Write the result into IMPLEMENTED.md (go / fallback).
3. **Parity harness**: for each service, record inputs and fake-model responses into fixtures, and a test that
   asserts the final output. The same fixtures later run against the new graphs (`tests/parity/`).
4. Add `import-linter` with today's rules (it replaces the AST test in Phase 8).
5. Write `docs/AI_ARCHITECTURE.md` (this design, short) and an ADR per decision in §10.

**Exit:** spike decision recorded; parity fixtures exist for all 8 services; CI runs `lint-imports`.

### Phase 1: the core kernel
1. Package skeleton `src/libs/hiru_ai/`, installed by `pyproject.toml` next to `contracts`; mypy and ruff cover it.
2. `settings.py`, `models.yaml`, `llm.py` (`get_llm`, `get_embeddings`), `usage.py` callback, `telemetry.py`.
3. `manifest.py` (pydantic schema per kind), `registry.py` (discover, lazy load, `get`, `refs`, `validate`).
4. `context.py` (`RunContext`), `ports.py`, `checkpoint.py` (Postgres / in-memory), `prompts.py`.
5. Middleware: `usage`, `untrusted_text`, `absent_safe`, `language_guard`, `static_first`.
6. CLI v1: `hiru-ai list`, `validate`, `new <kind> <id>` (scaffolds a folder with manifest, code, prompt, test, eval).
7. Test fakes: LangChain `GenericFakeChatModel` plus a fake router; tests never touch the network (existing rule).

**Exit:** core unit tests; `hiru-ai new agent demo` + `validate` + generated contract test pass, then the demo is deleted.

### Phase 2: adapters, tools and steps
1. `adapters/supabase_rest.py`, `storage.py`, `images.py` implementing `ports.py` (from the services' `rest.py`/`store.py`).
2. Tools, one folder each, `@tool` with typed args and `ToolRuntime` context: scene read/write, dialogue read,
   shot write, canon write, structure write, timing check, Veo fit, technique lookup, image generate, `search_kb`.
3. Steps, one folder each: `scene_kernel`, `kernel_score`, `board_settle`, `ripple`, `refusal_screen`, `verbatim_check`,
   `feeling`, `serialize`, `chunk`, `extract_text`, `canon_rules`, `bridges`, `stage_check`.
4. Generated contract tests for every tool and step; step unit tests ported from today's engine tests.

**Exit:** every tool and step runs alone (`hiru-ai run step kernel_score --input …`) and matches parity fixtures.

### Phase 3: RAG and knowledge bases
1. `rag/embeddings.py` (via `get_embeddings`), `retrievers/match_chunks.py` (a LangChain `BaseRetriever` over the
   `match_chunks` RPC, total ordering kept), `retrievers/keyword.py`, `retrievers/hybrid.py`, `rerankers.py`
   (absent-safe: no rerank without a key).
2. `knowledge_bases/<corpus>/` for craft, cinematography, rules, guides, techniques and production_docs, each
   with `component.yaml` (chunking, header rules, embed tier, corpus id) and `ingest.py` on a shared `KnowledgeBase` base.
3. `hiru-ai ingest <kb>` replaces `scripts/ingest_knowledge.py`; `api/services/retrieval.py` calls `rag`.
4. Tool `search_kb` lets any agent list KBs by id in its manifest.

**Exit:** `eval_retrieval.py --runs 3` ≥ `tests/eval/thresholds.json` (probes untouched); API search tests green.

### Phase 4: agents
1. Two agent builders in `core`: `structured` (prompt | `get_llm(tier).with_structured_output(Output, strict)`)
   and `react` (`create_agent(model, tools, middleware, response_format=Output)`).
2. Port every agent in §6, one folder each: prompt files (static part first), `schema.py`, manifest, eval cases
   taken from today's tests and fixtures.
3. Middleware `hitl` and `retry/fallback` added for `react` agents.
4. `hiru-ai run agent <id> --input case.json` with a fake or real model (real only when a person runs it).

**Exit:** every agent passes generated contract tests and its parity fixtures in isolation; `validate` green.

### Phase 5: panels and the pattern library
1. `core/patterns/`: `sequential`, `fanout`, `board`, `critics_judge`, `generate_critique`, `router`, `human_gate`,
   each with its own tests (including max-round and empty-member cases).
2. Panels: `director_board`, `plan_review`, `shot_review`, `structure_draft`. Membership lives in the manifest;
   disabling a member in YAML removes it from the graph.
3. Mermaid snapshot test per panel.

**Exit:** each panel runs alone against parity fixtures; removing a member in a test manifest still compiles and runs.

### Phase 6: systems and the function migration (one at a time)
For each system: write `systems/<id>/` (graph, state, routing, manifest), make the function handler thin
(`thread_id = job_id`, `RunContext` with real adapters, run the system, report), bundle `hiru_ai` in
`deploy-functions.yml` and `scripts/start-functions.ps1`, and keep a per-function `AI_ENGINE=legacy|graph` switch
until the next phase. Order, simplest first:

1. `echo` (template) → 2. `doc_ingest` → 3. `canon_extract` → 4. `structure_build` (`human_gate` questions,
existing checkpoints kept compatible) → 5. `frame_render` → 6. `script_split` → 7. `shot_producer` →
8. `director_chat` (router + board + translator `human_gate` for pending cards; SSE stream from `stream_mode="custom"`;
the event shapes the frontend reads stay byte-identical) → 9. API `ai.py` `answer()` uses `get_llm`.

**Exit per system:** parity fixtures green on `graph`; `scripts/eval_staging.py` no worse; smoke script passes
(run only after the person says so, because it writes to the hosted dev DB).

### Phase 7: developer experience
1. `hiru-ai remove <kind> <id>`: lists every reference, removes manifest lines on confirm, deletes the folder.
2. `hiru-ai graph <system|panel>`: writes Mermaid; `hiru-ai catalog` writes `docs/AI_CATALOG.md` (every part,
   owner, model tier, tools, KBs, used-by) and CI checks it is current.
3. `langgraph.json` so systems open in LangGraph Studio locally for step-by-step debugging.
4. Env overlays: `HIRU_AI__DISABLE=agent:advisor,tool:x` and `models.<env>.yaml` for per-environment toggles.

**Exit:** a new teammate adds a craft agent to the board using only the recipe in §8 and the CLI.

### Phase 8: observability, evals, clean-up
1. Tracing on every run, tagged with system/panel/agent id, version and prompt hash (tool choice in §10).
2. Eval suite: per-agent cases from each `evals/` folder, per-system golden runs; CI gate thresholds like retrieval's.
   A/B by running two versions of an agent (`translator@1` vs `@2`) through the same cases.
3. Remove `legacy` engines, the `AI_ENGINE` switch, duplicated `runtime/` files and `tests/test_isolation.py`'s
   service rule (now `import-linter`). Move fork notes from each `UPSTREAM.md` into `docs/archive/`.
4. Rewrite CLAUDE.md "Boundaries", "AI and RAG" and "Jobs" for the new layout; update `docs/ARCHITECTURE.md`.

**Exit:** no service has an `engine/` or `runtime/` folder; CLAUDE.md matches the code.

### Later (separate plans)
- **MCP**: expose the tool registry as an MCP server (the same tools usable from Claude or PromptMotion) and
  load outside MCP tools into the registry through `langchain-mcp-adapters`.
- One generic "runner" function instead of eight, if deploy and cold-start numbers favour it.
- Long-term memory per production through LangGraph `Store` (a director's preferences across scenes).

## 8. Recipes (the point of all this)

**Add an agent**: `hiru-ai new agent lighting` → write `prompts/system.md`, `schema.py` and two eval cases → `hiru-ai validate`.
**Put it on a panel**: add `- { agent: lighting, owns: [set] }` to `panels/director_board/component.yaml`.
**Remove an agent**: `hiru-ai remove agent lighting` (shows and removes references), or `status: disabled` to keep it.
**Add a tool**: `hiru-ai new tool weather_lookup` → implement `tool.py` → list `weather_lookup` under an agent's `tools:`.
**Remove a tool**: `hiru-ai remove tool weather_lookup`; `validate` fails until no agent lists it.
**New panel**: `hiru-ai new panel lighting_review --pattern critics_judge` → set members and judge step.
**New system**: `hiru-ai new system trailer_cut` → write `graph.py` from panels and agents by id → add a `JobKind`,
a `FunctionSpec` in `task_manager.FUNCTIONS`, `deploy-functions.yml` and `start-functions.ps1` (existing job rule).
**Change a model**: edit the agent's `model:` tier, or the tier's group in `models.yaml`.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Cold start and zip size grow (LiteLLM and LangChain are large) | Phase 0 spike measures it; lazy registry imports; `get_llm` can fall back to `ChatOpenAI` without other changes |
| Dependency churn or supply-chain risk in fast-moving libraries | exact pins with hashes, Renovate PRs reviewed by hand, CI runs the full suite on every bump |
| Behaviour drift while moving ~10k lines | parity fixtures recorded before any move; one system at a time; `legacy` switch until Phase 8 |
| Prompt-cache hit rate drops | `static_first` middleware asserts it; the spike checks cached-token counts |
| Too much abstraction | patterns only where two or more panels share a shape; plain LangGraph allowed in any `graph.py` |
| Director chat streaming events change | event shapes snapshot-tested against today's output before migration |
| Checkpoints written by old `structure_build` / `canon_extract` | keep state keys compatible, or finish open jobs before switching that function |

## 10. Decisions for the person

1. **(default)** One shared package `hiru_ai`, bundled into every function like `contracts`. This replaces the
   "service imports only itself" rule; it is required for parts to be reusable.
2. **(default)** OpenAI only, through LiteLLM. Another provider stays a separate decision.
3. **(default)** LiteLLM **in-process** (Router library), no separate LiteLLM proxy server.
4. **(default)** Migrate one system at a time, in the order of Phase 6, with a rollback switch.
5. **(default)** Stop tracking PromptMotion upstream diffs; archive the `UPSTREAM.md` notes.
6. **(default)** Tests live in each part's folder.
7. **(default)** Keep eight Cloud Run functions (one per system); a single runner is a later option.
8. **Open:** tracing tool. Options: LangSmith (hosted, deepest LangGraph integration), Langfuse (open source,
   self-hostable), or OpenTelemetry only to Google Cloud Trace. Not needed before Phase 8.

## 11. Sources

- LangChain v1 (`create_agent`, middleware): https://pub.towardsai.net/langchain-v1-x-features-agents-middleware-streams-and-mcp-0b8bda0f49b2,
  https://www.developersdigest.tech/agent-frameworks/langchain
- LangChain + LiteLLM (`ChatLiteLLM`, `ChatLiteLLMRouter`): https://docs.langchain.com/oss/python/integrations/chat/litellm,
  https://pypi.org/project/langchain-litellm/
- LangGraph releases and features: https://releases.sh/langchain/langgraph-releases.md, https://releasebot.io/updates/langchain-ai/langgraph
- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- LiteLLM Router (fallbacks, retries): https://docs.litellm.ai/docs/routing
- Anthropic, Building effective agents: https://www.anthropic.com/research/building-effective-agents
- 12-Factor Agents: https://github.com/humanlayer/12-factor-agents
- import-linter: https://import-linter.readthedocs.io/
- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
