# One AI package: what is built

Plan: [PLAN.md](PLAN.md). Updated at the end of each phase.

## Phase 0: groundwork and safety net (done 2026-11-03)

No behaviour changed: nothing under `src/` was edited. All new files are requirements, config, tests, docs and one
script.

### Exit checks

| Exit condition | State |
|---|---|
| spike decision recorded | fallback to `ChatOpenAI`, decided by the product owner ([ADR 0003](../../docs/adr/0003-litellm-in-process.md)) |
| parity fixtures exist for all 8 services | 44 fixtures, 8 services, replayed in 2 s |
| CI runs `lint-imports` | `python scripts/lint_imports.py` runs in the `python` job, after `mypy` |

### 1. Pinned versions (read from PyPI on 2026-11-03)

Latest on PyPI that day: `langchain` 1.4.8, `langchain-core` 1.7.4, `langchain-litellm` 0.11.2, `litellm` 1.106.6,
`langgraph` 1.2.19, `langgraph-checkpoint-postgres` 3.2.0. LiteLLM ships almost daily, so the pins are not the
newest: the sets are resolved with `--exclude-newer 2026-10-27` (a week old), and every pin is a release that has
had time to be pulled if it was bad.

| Package | Pin | Why not the newest |
|---|---|---|
| `langchain` | 1.4.4 | 1.4.8 is one day old |
| `langchain-core` | 1.7.0 | the version already installed with `langgraph` here; 1.7.1–1.7.4 are under a week old |
| `langchain-litellm` | 0.11.2 | newest |
| `litellm` | 1.106.2 | 1.106.3–1.106.6 are under a week old |
| `langgraph` | 1.2.16 | what the services run today; 1.2.19 is a bump to take on purpose |
| `langgraph-checkpoint-postgres` | 3.2.0 | newest, and what the services run |

- [requirements/hiru_ai.in](../../requirements/hiru_ai.in) → [hiru_ai.txt](../../requirements/hiru_ai.txt): the plan's set
  (LiteLLM), 98 packages with hashes.
- [requirements/hiru_ai_openai.in](../../requirements/hiru_ai_openai.in) → [hiru_ai_openai.txt](../../requirements/hiru_ai_openai.txt):
  the fallback set (`langchain-openai` 1.7.2 instead of LiteLLM), 51 packages with hashes.
- `scripts/lock_hiru_ai.ps1` re-resolves both (`-Cutoff <date>` for a reproducible run). Nothing installs them yet:
  Phase 1 wires the package that does.
- `hiru_ai.txt` was installed with `--require-hashes` into a clean Python 3.12 venv and imported.

### 2. Spike: LiteLLM or `langchain-openai`

Scripts: [spike/litellm_spike.py](spike/litellm_spike.py) (behaviour) and
[spike/measure_imports.py](spike/measure_imports.py) (cold start). It ran against a local fake of the OpenAI chat
endpoint: no key, no network call to OpenAI, no cost. 11 of 11 checks pass.

Works the same through `ChatLiteLLMRouter` and through `ChatOpenAI`: strict `json_schema` structured output with
the schema intact; the messages sent byte-identical to what `runtime/llm.py` sends today (the OpenAI prompt-cache
key); `reasoning_effort`; usage numbers equal to today's `token_usage` row (`input_tokens`, `cached_input_tokens`,
`output_tokens`); retry then fallback to the next tier; embeddings with `dimensions`.

Two things to remember when `core/llm.py` is written:
- `ChatLiteLLMRouter(reasoning_effort=...)` is silently dropped; it must go in `model_kwargs`.
- `dimensions` is a field of the embeddings object, not of the router entry.

| | today | `langchain-openai` | `langchain-litellm` |
|---|---|---|---|
| installed / zip (Linux wheels, largest service set) | 85 MB / 23 MB | 95 MB / 26 MB | **287 MB / 97 MB** |
| packages | 60 | 63 | 105 |
| import time (laptop, median of 7) | 3.7 s | 3.6 s | **8.7 s** |
| peak memory after import | 97 MB | 100 MB | **204 MB** |

Not proven: real prompt-cache hits (the bytes that decide them match, but OpenAI was not called) and Cloud Run cold
start (the laptop's antivirus inflates absolute seconds). Both need a real call, which tests must not make.

**Decision (2026-11-03, the product owner, after this result): fall back.** `get_llm` returns `ChatOpenAI`;
LiteLLM stays the documented swap for the day a second provider is approved. Recorded in
[ADR 0003](../../docs/adr/0003-litellm-in-process.md). Nothing else in the plan changes.

### 3. Parity harness: `tests/parity/`

- [cases.py](../../tests/parity/cases.py): the scenarios (input + scripted model replies), 44 across the 8 services.
- [adapters.py](../../tests/parity/adapters.py): one adapter per service builds the same fakes the service tests use,
  runs today's engine (`legacy`) and returns the whole outcome: the pipeline's result, the job's status and events,
  the rows the fake store ended up holding, and the model calls made (schema, tier, phase, a hash of the system
  prompt). `director_chat` records its event stream.
- [harness.py](../../tests/parity/harness.py): normalises an outcome (ids and content digests renamed by first
  appearance, timestamps blanked, bytes hashed) and makes `uuid4()` repeat itself for the length of a run.
- [record.py](../../tests/parity/record.py): `python -m tests.parity.record [service [case]]` writes
  `fixtures/<service>/<case>.json` and refuses a case whose outcome differs between three runs.
- [test_parity.py](../../tests/parity/test_parity.py): replays every fixture, and checks the fixtures match the case
  definitions. `PARITY_UPDATE=1 pytest tests/parity` re-records the ones that differ; the diff is a behaviour change.

Coverage per service: echo 2, doc_ingest 5 (rules, model + embeddings + rerun, embedding down, scanned PDF,
confirmed role), canon_extract 4, structure_build 6 (questions, resume, no checkpoints, outline only, scenes off,
model names), frame_render 7, script_split 8 (rules, fixed length, approved, model plan, critic replan, model down,
build hop, stale hop), shot_producer 4 (rules, model, prompts, chain), director_chat 8 (edits, permissions, refusals,
memory, the craft board with ownership collision and advisor).

Checked that it bites and is stable: re-recorded three times in one process and replayed in three fresh processes
with identical results; mutating `WORDS_PER_SECOND` changes 13 of the 44 fixtures.

How the new graphs use it: Phase 6 adds a `graph` branch to a service's adapter (it raises `NotImplementedError`
for any engine but `legacy` today) and adds `"graph"` to `ENGINES` in `test_parity.py`.

Limits, on purpose: the fakes are the ones the service tests use, so a fixture pins the same ground those tests
cover, but as a whole outcome and not one assertion at a time. Input rows are rebuilt from the Harbour Lights
corpus (`tests/fixtures/corpus/`), so changing that corpus is a re-record. Content digests are compared as equal or
different, not by value (some are hashes of ids drawn once per test process). The real `Rest`/`Store` classes and
`handler.handle` are not in the fixtures; the fakes stand where they would.

### 4. import-linter

`[tool.importlinter]` in `pyproject.toml`, run by [scripts/lint_imports.py](../../scripts/lint_imports.py) (it puts
each service folder on the path, as Cloud Run does). Four contracts, all kept on today's code:
`contracts` is a leaf (no `api`, no service, no `fastapi`/`httpx`/`openai`/`supabase`/`langgraph`/`psycopg`);
services never import `api`; `api` never imports a service; services are independent of each other.
Checked that it fails when broken (a probe import in `contracts` → exit 1). `tests/test_isolation.py` stays until
Phase 8 because it also holds the allow-list of third-party imports. `import-linter==2.15` is a dev dependency.

### 5. Docs

[docs/AI_ARCHITECTURE.md](../../docs/AI_ARCHITECTURE.md) and one ADR per decision of §10 in
[docs/adr/](../../docs/adr/README.md). ADR 0003 is the one waiting on you; ADR 0008 (tracing) is open by design.

## Deviations from the plan

- Latest-version pins are a week behind PyPI on purpose (see §1).
- A second hashed set (`hiru_ai_openai`) exists so either spike outcome can start Phase 1 without more work.
- The spike did not call OpenAI, so cache hits and Cloud Run cold start are unmeasured (§2).
- Parity fixtures record scenario parameters plus scripted model replies, and rebuild store rows from the corpus,
  rather than dumping every input row; the fixtures stay small and readable.

## State of the repo when Phase 0 was done

- `pytest -q`: 1083 passed, 6 failed. The 6 failures are in `tests/api/` (`test_handoff.py` ×2, `test_looks.py`,
  `test_production.py` ×3) and fail the same way without any Phase 0 file; they come from the uncommitted work
  already in the tree and are not touched here.
- `ruff check src tests scripts infra/assemble`: clean. `python scripts/lint_imports.py`: 4 kept, 0 broken.

## Open items

- ADR 0008 (tracing tool), needed before Phase 8.
- Renovate PRs for the hashed sets, as the plan's risk table asks, are not configured.

## Phase 1: the core kernel (done 2026-11-03)

`src/libs/hiru_ai/`, installed next to `contracts` (`pip install -e .`; a `hiru-ai` command is installed with it).
No service imports it yet, and an import-linter contract keeps it that way until Phase 6, because the function zips
do not bundle it. Nothing under `src/services/` or `src/api/` changed.

### Exit checks

| Exit condition | State |
|---|---|
| core unit tests | `tests/hiru_ai/`: 73 passed, 3 skipped (the per-part checks, which have no parts to run on yet) |
| `hiru-ai new agent demo` + `validate` + generated contract test pass, then the demo is deleted | done; the scaffold's own 3 tests and the 4 contract tests passed, then breaking the demo's tier failed its contract test, then it was deleted |
| gates | `ruff check src tests scripts infra/assemble` clean; `mypy` clean (now includes `hiru_ai`); `python scripts/lint_imports.py` 14 kept; `pytest -q` 1156 passed, 3 skipped, 6 failed (the same 6 `tests/api` failures as before Phase 0) |

### What exists

| File | What it does |
|---|---|
| `core/settings.py` | `get_settings()`; reads the names the functions already deploy (`OPENAI__*`, `SUPABASE__*`) |
| `core/models.yaml`, `models.py` | tiers → which setting holds the model id and effort, plus timeout, retries, fallback tiers |
| `core/llm.py` | `get_llm(tier)`, `get_structured(tier, Schema)`, `get_embeddings(phase, sink)`, `use_models()` for tests; the only module that imports OpenAI |
| `core/usage.py` | `UsageCallback`: one `token_usage` row per call, with exactly the table's columns |
| `core/telemetry.py` | logger and run tags (component, version, prompt hash, phase) |
| `core/context.py`, `ports.py` | `RunContext` (scope, actor, job, usage sink, ports) and the port protocols |
| `core/checkpoint.py` | the Postgres / in-memory saver, moved from `structure_build`, plus `thread_config(job_id)` |
| `core/prompts.py` | a prompt is a file: static text and a hash |
| `core/manifest.py`, `registry.py` | `component.yaml` schema per kind; discover, lazy import, `refs_to`, `validate` |
| `core/middleware/` | `usage`, `untrusted_text`, `absent_safe`, `language_guard`, `static_first` and the chain runner |
| `core/testing.py` | `ScriptedChatModel`: a real LangChain chat model that answers from a script |
| `cli/` | `hiru-ai list`, `validate`, `new <kind> <id>` |
| layer folders | `rag/ knowledge_bases/ tools/ steps/ agents/ panels/ systems/`, empty until Phases 2 to 6 |

### What was checked, and how

- **The model door, on the real `ChatOpenAI` over a mocked HTTP transport** (no socket, no key): strict
  `json_schema` and the schema's fields on the wire; the system and user messages sent byte for byte as given (the
  prompt-cache key); each tier's model and `reasoning_effort`; model ids read from settings; a 500 is retried once and
  then succeeds; a tier with `fallbacks` tries the next tier; no key raises `ModelUnavailable`.
- **Token counting, for the subscription meter**: a normal call, a **streamed** call (the request carries
  `stream_options.include_usage` and the final chunk's counts reach the row), and embeddings all produce a
  `token_usage` row with `input_tokens`, `cached_input_tokens` and `output_tokens` equal to what the services record
  today; a sink that raises never fails the call. LangChain's embeddings wrapper drops token counts, so
  `get_embeddings` uses the `openai` SDK directly, as the services do.
- **Middleware**: absent-safe degrades to a fallback and does not hide an error when there is no fallback, and always
  lets a graph `interrupt()` through; untrusted text is wrapped in the engines' own `<document name role>` form and a
  document cannot close its wrapper; `static_first` raises in strict mode and logs otherwise; `language_guard` refuses a
  changed or invented line from any part not marked `writes_dialogue`.
- **Registry**: ids, kind and folder agree; missing and disabled references; unknown tier or middleware; dialogue
  writers limited to `DIALOGUE_WRITERS` (`translator`); prompts and eval cases required; schemas must be pydantic
  models; import errors are problems, not crashes; reference cycles; a part's code is not imported until asked for;
  `refs_to` lists what removing a part would break.
- **Import rules** (`pyproject.toml`): layers, sibling independence for agents, tools, steps, panels, systems and
  knowledge bases, "only `core.llm` imports OpenAI", "hiru_ai never imports `api` or a service", "functions do not use
  hiru_ai yet". Checked that they bite by adding two agents that import each other, `core` importing `agents`, and an
  agent importing `openai`: three contracts broke, exit 1.
- Building it found one bug in the scaffold (a colon in the TODO summary made invalid YAML), caught by `validate`.

### Deviations from the plan

- **Tier names stay `ultra | high | medium | low`**, not `fast | smart | vision | embed`. The engines call these
  names and the parity fixtures record them, so keeping them keeps Phase 4 and 6 comparisons exact, and the existing
  environment variables keep working. `embed` and `image` are separate entries in `models.yaml`.
- **`fallbacks` is empty for every tier** (today's behaviour). The mechanism works and is tested; which tier backs up
  which is a product choice to make before it is turned on.
- **Timeouts** are 180 s for `ultra`/`high`, 120 s for `medium`, 60 s for `low` (today: 180 s in the chat services, 60 s in
  `doc_ingest`). Retries stay 2.
- **The trace tags (component, version, prompt hash) are not stored in `token_usage`**: the table has no such columns.
  They travel as run metadata and logs. Adding columns needs a schema change in `Database/` (the user's process), so
  it is an open item, not done.
- **`langchain` 1.4.4 is pinned and installed but not imported yet**: `create_agent` arrives with the `react` agents in
  Phase 4. `hitl` and `retry`/`fallback` middleware wait for the same phase.
- **`language_guard` is added to every part without `writes_dialogue`, listed or not**, so the "no other agent writes a
  line" rule cannot be left out of a manifest.
- **Generated contract tests** here cover manifest, folder, prompt, evals and schemas for every part found. "Builds and
  answers a fake model with a valid `Output`" needs the agent builders (Phase 4); panels and systems compiling and
  their Mermaid snapshots need Phases 5 and 6.
- **Ports** are the methods today's stores and handlers already have; they grow in Phase 2 as tools need more.
- `pytest` now also collects `src/libs/hiru_ai` (ADR 0006: tests live with the part).

### Not proven

- Real OpenAI behaviour: cached-token counts on a live call, and a live streamed call. The wire format and the parsing
  are tested, the server is not. A first live check (a person's call, one cheap request) is advisable before Phase 6.
- Cold start of `hiru_ai` on Cloud Run: nothing imports it there yet.

### Open items

- ADR 0008 (tracing tool), before Phase 8.
- `token_usage` columns for component id, version and prompt hash (a `Database/` change), if cost per agent is wanted.
- Which tiers should fall back to which (`models.yaml`).
- Renovate for the hashed requirement sets.

## Phase 2: adapters, tools and steps (done 2026-11-03)

`src/libs/hiru_ai/{adapters,tools,steps}`. Still no service imports `hiru_ai` (the import-linter contract that says so
is unchanged), and nothing under `src/services/` or `src/api/` was edited: the legacy engines stay, and each step is
held to the function it was ported from. The six failing tests below are the same six as before Phase 0.

### Exit checks

| Exit condition | State |
|---|---|
| every tool and step runs alone (`hiru-ai run step kernel_score --input …`) | all 24 have `examples/basic.json`, and a generated test runs each one through the CLI |
| matches parity fixtures | each step is compared with its legacy engine function on the same inputs: `tests/hiru_ai/test_steps_parity.py`, 86 cases (see "How matching was measured") |
| generated contract tests for every tool and step; step unit tests ported from the engine tests | `tests/hiru_ai/test_contract.py` (133 cases over the 24 parts); `scene_kernel` (30 tests) and `extract_text` (12) carry their legacy tests, ported by changing the imports; `chunk` carries the legacy chunking tests rewritten to take `extract_text`'s output; the other steps have new ones |
| gates | `ruff check src tests scripts infra/assemble` clean; `mypy` clean (196 files); `lint-imports` 17 kept (3 new); `hiru-ai validate` 24 parts, 0 errors; `pytest -q` 1555 passed, 1 skipped, 6 failed (the same 6 `tests/api` failures as before Phase 0; passed went from 1156 to 1555) |

### What exists

**Adapters** (`adapters/`, imported only by a composition root):

| File | Port | Notes |
|---|---|---|
| `supabase_rest.py` | `SceneStore`, `CanonStore`, `StructureStore`, `DocStore`, `Search` | one `Rest` client merged from the services' vendored copies (PostgREST's own error text, `claim`, `rpc`); `build_ports()` builds them all; `usage_sink()` writes `token_usage` and never fails the work |
| `storage.py` | `Files` | retries a dropped connection or a 5xx with a doubling pause (a 4xx is never retried); uploads overwrite, so a retried job leaves one object |
| `images.py` | `ImageGen` | the provider boundary of `frame_render/engine/image.py`: generate, or edit with references in the order the prompt numbers them; a decline is `ImageRefused` (never retried); the tokens go to a `frame_render.image` usage row |

`core/ports.py` grew to what the tools need (`save_plan`, `replace_shots`, `save_design`, `add_prompt`; `CanonStore`;
`StructureStore`; `Search`; `Picture`, `Reference`, `ImageRefused`, `ImageFailed`). `core/fakes.py` holds an in-memory
version of every port; `core/tooling.py` turns a tool into a LangChain `StructuredTool` that reads its scope from
`ToolRuntime.context` (checked inside a real `ToolNode`); `core/parts.py` is how one part reaches another by id
([ADR 0009](../../docs/adr/0009-parts-reach-siblings-by-id.md)).

**Steps** (13; each is `logic.py` ported from the legacy file, plus `step.py`: JSON in, JSON out):

| Step | Ported from | Notes |
|---|---|---|
| `refusal_screen` | `director_chat/engine/refusals.py` | |
| `scene_kernel` | `director_chat/engine/kernel.py` (+ `turn.kernel_for`) | uses `refusal_screen` |
| `ripple` | `director_chat/engine/ripple.py` | uses `scene_kernel`; reads a kernel through a `Protocol` |
| `board_settle` | `director_chat/engine/agents.py` (the pure half: `settle`, ownership) | the specialists themselves are agents (Phase 4) |
| `verbatim_check` | `director_chat/engine/turn.py` (`_flat`, `_words`, `_verbatim`) | |
| `kernel_score` | `script_split/engine/critic.py` (the pure half) | the model critics are agents (Phase 4) |
| `feeling` | `shot_producer/engine/feeling.py` | |
| `serialize` | `shot_producer/engine/serialize.py`, `model.py`, `schema.py` and the clip schema YAML | uses `feeling`; the shot model lives here and the Phase 4 agents will reach it by id |
| `extract_text` | `doc_ingest/engine/extract.py` | a refused file is a result, `{"rejected": …}` |
| `chunk` | `doc_ingest/engine/chunking.py` | uses `contracts.screenplay.SCENE_HEADING` (checked identical to the one in `roles.py`) |
| `canon_rules` | `canon_extract/engine/rules.py`, `pipeline.rule_candidates` and `chips`, `write.critic` | |
| `bridges` | `contracts.bridges` | a wrapper: the rule stays in `contracts` |
| `stage_check` | `contracts.stagemap` | a wrapper, as above |

**Tools** (11; `Args`, `Result`, `run(args, ctx)`, `as_tool()`; `ports:` and `writes:` in the manifest):

| Tool | Ports | Writes | Notes |
|---|---|---|---|
| `scene_read`, `dialogue_read` | scenes | no | a scene of another production is "not found"; dialogue comes back exactly as stored |
| `scene_write` | scenes | yes | `save_plan`; refuses a line that changes, appears or goes unless `by` is `person` (or `translator`, which keeps the original as `source_text`), a shot or line of another scene or production, and a scene field that moves the scene |
| `shot_write` | scenes | yes | modes `plan` (re-binds lines, never rewords one), `design`, `prompt` |
| `canon_write` | canon | yes | `plan.py` ported from `canon_extract/engine/write.py`; uses `canon_rules`; a locked entity is reported, not changed |
| `structure_write` | canon, structure | yes | `plan.py` ported from `structure_build/engine/write.py`; an approved scene is never rewritten |
| `timing_check` | scenes | no | `contracts.shotplan.fit` over the stored plan or a proposal; reports, never trims |
| `veo_fit` | none | no | which of 4/6/8 s a number of words needs, and the overrun when none does |
| `technique_lookup`, `search_kb` | search | no | absent-safe (no key = keyword-only; a failed lookup = none); `search_kb` takes its corpora and document filter from `RunContext`, never from the model |
| `image_generate` | images, files | yes | reads references from storage by path, paints, uploads; a decline is `refused=True` |

`hiru-ai run step|tool <id> --input case.json` runs one part on in-memory fakes. `--live` uses the real adapters, and a
tool that writes also needs `--allow-writes` (that is the hosted dev database: ask first).

### How matching was measured

The Phase 0 parity fixtures record whole services, which a single step cannot reproduce. So each step runs beside the
legacy function on the same inputs and the whole outcome is compared:

- `scene_kernel`: 6 operation batches × 3 actors (`conductor`, `you`, `timing`) × 2 Harbour Lights scenes, comparing
  applied, rejected, changes, shots, items, notes and the description (refusal wording goes through `refusal_screen`);
- `ripple`, `board_settle` (4 collision sets), `verbatim_check` (6 operations), `refusal_screen` (10 reasons),
  `kernel_score` and `stage_check` (a clean and a teleporting scene), `feeling` (2 scenes × 2 shots), `serialize`
  (2 scenes × 2 shots, with and without a first frame: sections and checks), `extract_text` + `chunk` (4 corpus files,
  both chunking modes), `canon_rules` (script, bible and index);
- the adapters are held to the legacy stores' **requests** (method, URL, query, body, in order) for `save_plan` and
  `replace_shots`, and to the legacy painter's refusal detection.

Checked that it bites: changing `SILENT_SHARE_MAX`, the sound owner and the refusal fallback in the steps failed 11 cases,
and restoring them made all pass again. Each new import contract was broken on purpose (a sibling step import, an adapter
imported from a tool, `httpx` in a step, a step imported by an adapter, a step imported by a tool): five probes, five
failures, then restored.

### Deviations from the plan

- **Steps and tools may name other steps in `uses:`** (ADR 0009). The plan said a part never imports a sibling and finds
  siblings through the registry; four real dependencies (kernel → refusals, ripple → kernel, serialize → feeling, canon
  writer → canon rules) needed to be visible in the manifest.
- **The shot model and the clip schema live in the `serialize` step.** `ShotInput` and `SceneInput` are built from
  stored rows and read by `serialize`; the Phase 4 shot agents will get them by id rather than from a shared module.
- **`board_settle` and `kernel_score`: only the pure half moved.** The specialists and advisors (`agents.py`) and the
  model critics (`critic.py`) are agents, so they arrive in Phase 4 with their prompts.
- **`stage_check` and `bridges` are thin wrappers** over `contracts` (the plan says the steps wrap them).
- **`scripts/ingest_knowledge.py` is untouched:** it still borrows `doc_ingest`'s chunker until Phase 3 moves it onto the
  `chunk` step.
- **`pypdf==6.19.0` was added to both hashed requirement sets** (the `extract_text` step needs it). The re-lock changed
  nothing else (compared package by package). `uv` was not installed here, so it was run from a throw-away folder.
- **Tool `ports` are validated** against the fields of `Ports`, and a generated test checks that a tool uses only the
  ports it declares and that `writes:` is true exactly when its example changes a store.
- **A part's `tests/` and `examples/` ride along** when `hiru_ai` is installed (they are inside the package, and so is
  `hiru_ai/conftest.py`). Phase 6 must leave them out of the function zips.
- The test folders of parts are excluded from `mypy` (like `tests/`). The parity tests import the legacy services through
  `tests/hiru_ai/conftest.py`, which puts each service folder on the path the way `scripts/lint_imports.py` does.
- **Every hiru_ai test runs with an empty `OPENAI__API_KEY`** (`hiru_ai/conftest.py`, `tests/hiru_ai/conftest.py`): a
  developer's `.env` holds a real key, and the search tools ask `models_enabled()`.

### Not proven

- The adapters against a real Supabase project (no test writes to the hosted dev database; the requests they send are
  compared with the legacy stores' instead) and `images.py` against the real image API.
- `search_kb` and `technique_lookup` with an embedding: the keyword-only path is tested; the embedding path goes through
  `get_embeddings`, which Phase 1 tested against a mocked transport.
- `structure_write` and `canon_write` against the legacy pipelines end to end: their `plan.py` are ports of the legacy
  `write.py` and are tested through the tools, but the legacy tests of those two files run whole pipelines and were not
  ported (Phase 6 brings the parity fixtures to them).

### Open items

- ADR 0008 (tracing tool), before Phase 8; `token_usage` columns for component id, version and prompt hash (a `Database/`
  change); which tiers fall back to which; Renovate for the hashed sets. (All unchanged since Phase 1.)
- `scripts/eval_retrieval.py` was not run: nothing in retrieval changed in this phase.

## Phase 3: RAG and knowledge bases (done 2026-11-03)

`hiru_ai/rag/` and `hiru_ai/knowledge_bases/`. Still no function imports `hiru_ai`. The API now imports three small pure
modules of it (see "The API"). Nothing else under `src/services/` changed except one path in a comment and a test.

### Exit checks

| Exit condition | State |
|---|---|
| `eval_retrieval.py --runs 3` ≥ `tests/eval/thresholds.json`, probes untouched | **not run.** It ingests the fixture corpus into the database and calls OpenAI for embeddings, so it needs the hosted dev database and a key: ask first. The probes' `source` paths (`knowledge_base/craft/...`) are unchanged, and the rows the new ingest builds are identical to the old script's (below). Run: `hiru-ai ingest --all`, then `python scripts/eval_retrieval.py --runs 3` |
| API search tests green | `tests/api/test_search.py` passes; `tests/api` has only the 6 failures it had before Phase 0 |
| gates | `ruff check src tests scripts` clean; `mypy` clean (365 files); `lint-imports` 18 kept (1 new); `hiru-ai validate` 58 parts, 0 errors |

### What exists

| Part | What it does |
|---|---|
| `rag/ranking.py`, `scope.py`, `hits.py` | the pure half of a search: candidates (30 with a reranker, else k), the rerank prompt and tie-break, which documents are searchable (ready, wanted role), a row as a cited hit. Plain Python plus `contracts`: no LangChain |
| `rag/embeddings.py` | `embed_query` (absent-safe: no model or a failed call gives `None`) and `embed_texts` (batched; a failure is raised, because a half-built index looks healthy) through `core.llm.get_embeddings` |
| `rag/retrievers/` | `MatchChunksRetriever` (a LangChain `BaseRetriever` over the `Search` port; documents come back in the database's order, nothing sorts), `KeywordRetriever` (never embeds), `HybridRetriever` (embed, fuse, optional rerank; `retrieve()` also says `mode` and `reranked`), `TechniqueRetriever` (`match_craft_techniques`, absent-safe) |
| `rag/rerankers.py` | `LLMReranker`: `medium` tier, the API's own prompt, strict schema, a usage row; no model or a failure gives `None` and the fusion order stands |
| `rag/knowledge.py` | the `KnowledgeBase` base: sources and manifest in, rows out (prose goes through the `extract_text` and `chunk` steps by id, so there is one chunker), embeddings reused when text and model are unchanged, rows replaced by source prefix |
| `knowledge_bases/{craft,guides,rules}` | prose bases: `component.yaml` lists the files and each file's `meta`; `ingest.py` is six lines |
| `knowledge_bases/cinematography` | the technique table: 6 CSVs plus `camera_shots.csv`, merged by `terms.py` (moved from `scripts/cine_terms.py`), 576 rows |
| `knowledge_bases/techniques` | the `craft_techniques` table as agents search it; `ingest: none`, `fed_by: cinematography` |
| `knowledge_bases/production_docs` | the uploads; `ingest: upload` (the doc_ingest job fills it, never `hiru-ai ingest`) |
| `core/scope.py` | `corpora_of(kb_ids)` and `scope_for(ctx, kb_ids)`: an agent's `knowledge:` becomes the corpora `search_kb` may read; a manifest can narrow a run, never widen it |
| `core/ports.py` `KnowledgeStore`, `core/fakes.py` `FakeKnowledge`, `adapters/supabase_rest.py` `SupabaseKnowledge` | where `hiru-ai ingest` writes: `embeddings`, `replace_chunks` (by corpus and source prefix), `replace_techniques` |
| CLI `hiru-ai ingest <kb>... \| --all [--dry-run] [--include-short-form]` | replaces `scripts/ingest_knowledge.py` (deleted, with `scripts/cine_terms.py`); CI, `README.md` and `Database/README.md` now say `hiru-ai ingest --all` |
| tools `search_kb`, `technique_lookup` | now call the retrievers (same behaviour, one path) |

### The API

`api/services/retrieval.py` and `api/services/ai.py` read the candidate count, the rerank prompt and message, the tie-break,
the document scope and the hit mapping from `hiru_ai.rag.{ranking,scope,hits}`: one copy, shared with the retrievers. The
API is async and keeps its own model calls until Phase 6 step 9, so it does not use the sync retrievers. A new import-linter
contract keeps its reach to those three modules (probe: importing `rag.rerankers` from `api` broke it), so the API image
needs no LangChain.

### How it was checked

- **Ingest parity with the old script** (one-off, before the script was deleted): the old script's row-building code and the
  new bases, on the same files: 94 chunks and 576 techniques, equal field for field (content hashes included, so no
  embedding is lost on the first re-ingest).
- 33 tests in `tests/hiru_ai/test_rag.py`: the rerank order and prompt, document scope, hit mapping, retriever order and
  scope, mode and rerank fallbacks, the LLM reranker's tokens and degradation, embedding batches, ingest into a fake store
  (shared corpus without deleting each other's rows, reuse of unchanged embeddings, no-key rows, dry run, a removed file
  removes its chunks, the technique table replaced whole and never emptied), the CLI, `scope_for`, `search_kb` scope.
- the API-side modules import without LangChain (a subprocess test).

### Deviations from the plan

- **`cinematography` owns the whole technique table** (the 6 CSVs and `camera_shots.csv`, now in its `sources/`), and
  `techniques` only declares it (`fed_by`). The two are merged into one row per technique, so they cannot be ingested
  apart without one base reading the other's files. `craft_techniques.source` keeps the old path strings.
- **Several bases share the `craft` corpus** (craft, guides, rules), which is why rows are replaced by `source` prefix and not
  by corpus.
- **`KnowledgeStore` is not a run port.** No agent or tool changes a knowledge base; only the ingest command does.
- **`src/knowledge_base/` moved** into `hiru_ai/knowledge_bases/<id>/sources/` (and `UPSTREAM.md` with it). `chunks.source`
  strings are unchanged, so citations and the eval probes are too. `*.csv` is now package data.
- **A structured agent cannot list `knowledge:`** (`validate` says so): it is one call and cannot search. A `react` agent that
  lists knowledge must list `search_kb`.
- The shared `KnowledgeBase` base lives in `rag/` (L1), not in `knowledge_bases/`, because bases may not import each other.

### Not proven

- `eval_retrieval.py` (above), a live ingest (only `--dry-run` was run), and embeddings against the real API.

## Phase 4: agents (done 2026-11-03)

`hiru_ai/core/agents.py` and 27 agent folders. Still no function imports `hiru_ai`; the legacy engines are untouched and
each agent is held to the engine function it came from.

### Exit checks

| Exit condition | State |
|---|---|
| every agent passes the generated contract tests | `tests/hiru_ai/test_agents_contract.py`: 192 cases over the 27 agents (builds, static prompt first, strict-schema-safe output, every eval case against a scripted model, the no-model path, only the translator writes dialogue) |
| and its parity fixtures in isolation | `tests/hiru_ai/test_agents_parity.py`: 25 tests. Each agent against the engine call it came from: the system prompt and the user message **byte for byte**, tier, `token_usage` phase, the strict schema's shape, and the cleaning of the answer where the engine did one. Checked that it bites (a changed prompt, a changed constant, a changed enum each failed) |
| `validate` green | 58 parts, 0 errors, 0 warnings |
| gates | `ruff` clean; `mypy` clean (365 files); `lint-imports` 18 kept; `pytest -q` 1995 passed, 6 failed (the same 6 `tests/api` failures as before Phase 0) |

### The builders (`core/agents.py`)

An agent is a folder: `component.yaml`, `schema.py` (`Input`, `Output`), `agent.py` (hooks), `prompts/system.md`, `evals/`,
`tests/`. The hooks are `user_message(inp)` (per-item data; the system prompt stays static), and optionally `fallback`,
`finish`, `documents`, `images`, `lines_before`/`lines_after`, `output_schema`.

- **`structured`**: `get_structured(tier, schema)` (strict JSON schema) inside the manifest's middleware, outermost first.
  Messages go out exactly as built (the prompt cache), a `token_usage` row per call with the engine's phase, the fallback when
  there is no key or the call fails.
- **`react`**: `create_agent(model, tools, system_prompt, response_format=Output, middleware, context_schema=RunContext)`.
  Tools get the run's `RunContext` (a model cannot choose the production or the corpora); `knowledge:` narrows `search_kb` to
  those bases. Middleware `hitl` (every `writes: true` tool stops for a person), `retry` (the tier's retries) and `fallback`
  (the tier's `fallbacks`) are LangChain middleware (`core/middleware/react.py`); `validate` refuses them on a structured agent.
- `hiru-ai run agent <id> --input case.json` shows the messages and, with a scripted `reply` in the case, the output (no
  network). `--live` asks the real model and costs money, so only a person runs it.
- Eval cases are `{name, input, reply | model: unavailable, expect}`; the generated test runs each against a scripted model and
  checks `expect` is contained in the output.

### The agents

| Owner | Agents (tier) |
|---|---|
| doc_ingest | `role_classifier` (medium), `chunk_contextualiser` (low) |
| canon_extract | `canon_extractor` (high), `canon_deduper` (medium) |
| structure_build | `prose_writer` (high), `architect` (ultra), `look_drafter` (medium) |
| script_split | `beat_finder` (medium), `stager` (medium), `scene_reader` (high), `scene_planner` (high), `coverage_critic` (high), `emotion_critic` (medium), `editor_critic` (medium) |
| shot_producer | `shot_intent` (high), `shot_writer` (high), `shot_critic` (high), `craft_articulator` (medium) |
| frame_render | `frame_inspector` (vision) |
| director | `conductor` (medium), `cinematographer`, `editor`, `sound_designer`, `continuity` (high), `advisor` (medium), `options_writer` (high), `translator` (high, the only `writes_dialogue`) |

Prompts were copied from the engines' constants by a script and are checked equal to them. The `Input` of each agent is typed
and knows nothing about the system that calls it; the script_split agents take `contracts.shotplan.Item` lists. New parts to
support them: step `scene_listing` (the numbered-block listing four agents read, ported from `planner.scene_listing`),
`contracts/directorops.py` (the closed `Op` shape the conductor, the four specialists and the options writer answer in),
tier `vision` in `models.yaml` (`OPENAI__MODEL_VISION`, no reasoning effort), `untrusted_text.defuse`.

### Deviations from the plan

- **Not made, because the engine has no model call there:** `analyst` (structure_build's `analyse` is rules and questions) and
  `continuity_checker` (the continuity ledger is code). **Added, because the engine has a model call the plan did not list:**
  `canon_deduper` (canon_extract's second call) and `craft_articulator` (shot_producer's `shot_producer.craft` call).
- **`reply_writer` is not ported.** The reply is plain text streamed token by token, and for the `chat` lane a tool loop over the
  director's own read tools (`get_canon`, `get_shot_timing`, `list_open_questions`, `search_production`), which are not among
  the Phase 2 tools. Both belong with the streamed `director_chat` system in Phase 6; a JSON-wrapped `text` field would change
  what the frontend receives.
- **`shot_intent` and `shot_writer` take their context as two rendered text blocks** (`production`, `scene`), not as rows. The
  rendering (about 300 lines of `ShotInput`/`SceneInput` formatting) is the producer system's job at the seam (Phase 6, with the
  `serialize` step's shot model); parity is checked with the engine's own renderers feeding both sides. `shot_writer`'s schema
  is not Python: it is the clip YAML turned into a strict schema at run time, so the agent has an `output_schema()` hook and its
  `Output` only holds `shots: list[dict]`. `shot_critic` likewise takes `context`, `plan` and `drafts` as text.
- **Agents wrap uploaded text themselves**, in the engines' exact form (`untrusted_text.wrap`/`defuse`) instead of listing the
  `untrusted_text` middleware: the middleware puts the document before the user message and may add a notice to the system
  prompt, which would change the bytes the prompt cache keys on. The one visible difference from the engines: a closing
  `</document` inside an uploaded text is now defused.
- **`finish` hooks hold only what the engine did to the answer** (the role classifier's clamp, the critic's four-note cap, the
  articulator's dedupe). The larger validation (a scene reading, a staging map, a shot plan, the `trusted` prose cut) stays with
  the system, where it already needs the stored rows.
- **No agent is a `react` agent yet.** None of the engines' structured calls is a tool loop; the builder, `hitl`, `retry` and
  `fallback` are built and tested (a scripted model calls a tool with the run's scope; `search_kb` is limited to the agent's
  bases) for the first agent that needs one.
- The four specialists are one prompt each (the engine's primer plus that craft's charter) and share the `Op` shape through
  `contracts`; which operations each may write is the director board's `owns:` list (Phase 5), as before.

### Not proven

- Real OpenAI behaviour: the wire format and parsing are tested over a mocked transport, the server is not. Strict mode accepting
  every `Output` (nested objects, `X | None`, `Literal` numbers, the `from` alias) is checked by shape, not by OpenAI.
- Prompt-cache hits and token counts on a live call (as before). A first live check is advisable before Phase 6.
- The agents inside their systems: Phase 5 and 6 wire them and rerun the Phase 0 fixtures on the `graph` engine.

### Open items

- ADR 0008 (tracing tool), `token_usage` columns for component id and prompt hash, which tiers fall back to which, Renovate for
  the hashed sets (unchanged).
- `reply_writer` and the director's read tools (Phase 6).

## Phase 5: panels and the pattern library (done 2026-11-03)

`hiru_ai/core/patterns/` and four panel folders. Still no function imports `hiru_ai`; the legacy engines are untouched, and
each panel is held to the engine code it came from.

### Exit checks

| Exit condition | State |
|---|---|
| each panel runs alone against parity fixtures | `director_board` against `agents.run_specialists` + `settle` + `advisor_review` (same outputs, same landed operations, same disagreements, byte for byte); `plan_review` against `pipeline.plan_scene` over all six ordered pairs of three plan shapes (same plan chosen, same notes); `shot_review` and `structure_draft` against the rules their engines had (bounded loop, accept rule, failure = rules). The whole-service Phase 0 fixtures run against these panels when Phase 6 migrates their systems |
| removing a member in a test manifest still compiles and runs | `tests/hiru_ai/test_panels_contract.py` takes each member out of each panel in turn (and all of them) and compiles it; the panel tests run `director_board` and `plan_review` without a member, and with a member's agent set to `status: disabled` |
| Mermaid snapshot per panel | `<panel>/tests/graph.mmd`, compared by the generated test; `HIRU_AI_UPDATE=1 pytest tests/hiru_ai/test_panels_contract.py` rewrites them |
| gates | `ruff` clean; `mypy` clean (390 files); `lint-imports` 19 kept (1 new); `hiru-ai validate` 63 parts, 0 errors; `pytest tests/hiru_ai src/libs/hiru_ai` 1013 passed |

### The pattern library (`core/patterns/`)

Each shape is a function that returns a compiled LangGraph graph with its own small state; a panel configures one with its
members. Seven patterns, 25 tests (`tests/hiru_ai/test_patterns.py`):

| Pattern | What it is | What the tests pin |
|---|---|---|
| `fanout` | one `Send` per item; results gathered **in item order** however the branches finish | order, real parallelism (a 3-party barrier), empty items = `[]` not an error |
| `sequential` | A → B → C | order; no nodes returns the input |
| `board` | fanout → `settle(outputs)` (code) → a second fanout over advisors | no tasks settles the empty set; advisors run only when given `reviews`, because they are heard AFTER the caller applied what landed |
| `critics_judge` | critics fan out → merge notes → ONE revision → the judge (code) picks | the lowest score wins and a tie keeps the first plan; a critic that fails is left out; all failing, or a failing revision, keeps the first plan (and the notes, in the second case); critics never choose |
| `generate_critique` | write → critique → (notes? revise → accept?), bounded by `max_rounds` | the ceiling holds whatever the critic says; no notes ends it; `accept` decides whether a revision replaces the draft; **the last revision is not reviewed again** (one review, one revision, as the producer did) |
| `router` | `classify` → `Command(goto=…)`, an unknown route goes to `fallback` or ends | |
| `human_gate` | `interrupt()` and resume with `Command(resume=…)`; without a checkpointer it answers by default and says which questions it defaulted | stops, resumes with the person's answers, defaults the rest |

### The panels

| Panel | Pattern | Members (agent → name) | What the manifest decides |
|---|---|---|---|
| `director_board` | `board` | cinematographer → cinematography, editor → timing, sound_designer → sound, continuity | `owns` (what a craft may write, was `ALLOWED`), `wins` (who wins a collision on a path, was `owner_of`), `settle: step:board_settle`, `review: [agent:advisor]` |
| `plan_review` | `critics_judge` | coverage_critic, emotion_critic, editor_critic | `judge: step:kernel_score`, `reviser: agent:scene_planner` |
| `shot_review` | `generate_critique` | `writer: agent:shot_writer`, `critic: agent:shot_critic`, `max_rounds: 1` | |
| `structure_draft` | `fanout` | prose_writer → prose, architect, look_drafter → looks | |

`core/panels.py` (`PanelKit`) is what a panel's `graph.py` uses: the active members (an agent with `status: disabled` is left
out of the graph and `validate` says so as a warning, not an error), agents and steps by id, and `ask()`, which returns `None`
for a member that failed so one failing member never stops the others. A panel never imports an agent, step or tool (a new
import-linter contract, checked by adding such an import: it broke).

The seams between a panel and the system that calls it are plain data or small functions the system passes in (the plan's
`input_map`/`output_map`): `plan_review` takes a brief (items, reading, staging, the listing text, the planner's input) and
returns the winning candidate's index; `shot_review` takes `write`, `critique` and `accept` functions because the shot model's
rendering belongs to the producer system; `director_board` takes tasks and returns `outputs` and `settled`.

### Other changes

- `manifest.py`: `Member` has `name` (what a task or lens calls it), `owns`, `wins`; `PanelManifest` has the roles `judge`,
  `reviser`, `writer`, `critic` and `max_rounds`; `validate` checks the pattern, the roles each pattern needs and their kinds,
  distinct member names, and that `owns`/`wins` name real operations.
- `board_settle` takes an optional `owners` table (the panel's `wins`); without it the built-in rule decides, as before. A
  test checks the manifest's table agrees with the built-in rule on ten operation shapes.
- New step `note_merge` (the critics' `_notes` and `merge_notes`, ported unchanged and tested against the legacy functions).
- New test model `RoutedChatModel` (`core/testing.py`): replies per route, chosen from the prompt, thread-safe, because parallel
  members reach the model in no fixed order.
- `hiru-ai new panel <id> --pattern <p>` writes `component.yaml`, a `graph.py` that builds the pattern with do-nothing members,
  and a test. All seven patterns are tested (each scaffold compiles).

### Deviations from the plan

- **Patterns own their state**, and a panel IS the pattern's compiled graph (so its drawing shows the real wiring), rather than
  a panel wrapping a pattern as a subgraph node. A system maps its state into the panel's at the seam.
- **`board` is run twice by its caller** (specialists + settle, then advisors) because the kernel applies what landed between
  them; the plan drew one pass.
- **The rules' plan is not a member of `plan_review`.** The splitter compares the panel's winner with the rules' plan afterwards
  (a stable minimum over [first, revision, rules] is equivalent, and tested over six plan pairs).
- **`reply_writer`, `analyst` and `continuity_checker` still do not exist** (Phase 4 deviations stand).

### Not proven

- The panels inside their systems: Phase 6 wires them and reruns the Phase 0 fixtures on the `graph` engine.
- Real model behaviour (as before): everything here runs on scripted models.

## Phase 6: systems and the function migration (done for 8 systems; the API's `answer()` is a decision, below)

One system at a time, simplest first, as the plan orders them. A system is a folder `hiru_ai/systems/<id>/` with `component.yaml`,
`state.py`, `graph.py` (`build` = the LangGraph, `run(payload, ctx)` = what the function's handler calls, `blank()` = the graph
with nothing to run, for drawing) and its own tests. The function keeps its job contract and error mapping in a **thin handler**:
it builds the run's `RunContext` and calls the system, and `AI_ENGINE=legacy|graph` (default `legacy`) picks the engine per
function until Phase 8 deletes the switch.

### Status

| # | System | Engine `graph` | Parity fixtures on `graph` | Handler switch | Bundled in the zip |
|---|---|---|---|---|---|
| 1 | `echo` | done | 2 of 2 | done | done |
| 2 | `doc_ingest` | done | 5 of 5 | done | done |
| 3 | `canon_extract` | done | 4 of 4 | done | done |
| 4 | `structure_build` | done | 9 of 9 (3 new: prose cut by rules, by a trusted model cut, by a refused one) | done | done |
| 5 | `frame_render` | done | 7 of 7 | done | done |
| 6 | `script_split` | done | 8 of 8 | done | done |
| 7 | `shot_producer` | done | 4 of 4 | done | done |
| 8 | `director_chat` | done | 8 of 8 | done | done |
| 9 | API `ai.py` `answer()` | not started | | | |

### What every migrated system shares (built once)

- **The thin handler.** `handler.run_graph(payload, store)` builds the context and calls `hiru_ai.systems.<id>.graph.run`.
  `hiru_ai.adapters.supabase_rest.build_context(payload, jobs=...)` is the composition root: the real ports, the delivery's ids
  and a `token_usage` writer (rows get `job_id`, `production_id`, `actor_user_id` from the context). The function passes its
  own job store as the `Jobs` port (it alone knows its courier hand-off): `runtime/jobs.py` `JobsPort`.
- **Ports grew.** `Jobs.stage`; `DocStore` now holds a document's row, its passages and their embeddings
  (`get_document`, `update_document`, `existing_embeddings`, `replace_chunks`), with a Supabase adapter and a fake. Chunk rows
  are written with a pgvector literal (`_with_vector`, as the knowledge bases are); the legacy store posted a JSON array. Both
  work as far as the tests can say; a live ingest on `graph` should be the first real check.
- **Test models for the `graph` engine** (`core/testing.py`, `tests/parity/graph_support.py`): `RoutedChatModel` answers by the
  call's `phase` (the usage middleware's metadata) from queues shared across tiers, a reply may be a function of the prompt, and
  it records phase and model of every call. `llm.use_embeddings(...)` replaces the embedding door as `use_models` does for chat.
- **Parity.** A system's adapter in `tests/parity/adapters.py` gets a `graph` branch that feeds the same legacy fakes to the new
  system, and `MIGRATED` in `tests/parity/test_parity.py` lists the systems whose `graph` engine is compared with the recording.
  Checked that it bites: changing the embedding batch size and a warning text in `doc_ingest` failed three fixtures, and
  restoring them passed.
- **Bundling.** `deploy-functions.yml` marks a function `"ai": true` when its system is migrated; its zip then also holds
  `hiru_ai` without each part's tests, examples, evals and the knowledge bases' source files (0.55 MB). Run from that copy alone,
  the echo graph engine works. `hiru_ai` changes redeploy only the `ai` functions. The function's `requirements.txt` carries the
  same pins as `requirements/hiru_ai_openai.in` (unhashed; see "Open items").
- **Import rules.** The contract "functions do not use hiru_ai until migrated" lost the migrated services, and a new one says a
  migrated function reaches `hiru_ai` only through its system, the core and the adapters (never an agent, step, tool, panel,
  knowledge base or the CLI directly). `hiru-ai validate` now checks a system has a `graph.py` with `run` and a real `job_kind`;
  `tests/hiru_ai/test_systems_contract.py` compiles, draws and snapshot-tests every system's wiring.

### 1. echo, 2. doc_ingest

- `echo`: one node; the template. The function's `JobsPort` over its `JobStore` is the whole adapter.
- `doc_ingest`: read → role → chunk → headers → embed → index. New steps `document_role` (the rules half of `roles.py`) and
  `chunk_headers` (the base header, the batches of 20, merging the model's line, ported from `context.py`), each checked against
  the legacy function over the whole corpus; the system's `rules.py` holds the glue (`paged_text`, `embed_hash`, the warnings,
  the chunk rows). The model is asked for the role only when the rules are unsure and a key is set, and a failing call keeps the
  rules' guess; header batches are asked against one document prefix and a failed batch keeps its base headers; embedding
  failure still indexes for keywords with the warning.

### 3. canon_extract, 4. structure_build

- `canon_extract`: read → extract → dedupe → critic → write. New step `canon_merge` (the code half of `model.py`: the extractor's
  answer into candidates, combining with the rules' canon, applying the deduper's groups; checked against the legacy functions;
  two coded entities are never merged). The write goes through the `canon_write` tool. The checkpoint thread (`<job>:canon`), the
  node names and the state keys are the legacy graph's, so a hop begun by either engine can be finished by the other; the thread
  is deleted at the end.
- `structure_build`: read → analyse → ask → architect → write → looks, thread `<job>:structure`. The question stop is the
  `human_gate` pattern's node (`ask_node`): `interrupt()` when durable, the suggested answer recorded as `defaulted` when not,
  resumed through `Command(resume=answers)`. The model's drafts (prose cut, episode names, looks) go through the
  `structure_draft` panel; every answer is checked in code and a missing or failed model falls to the rules. New steps
  `structure_analyse` (`analyse.py` unchanged), `prose_cut` (`prose.py` without the model call), `look_plan`, `episode_names`;
  new ports on `StructureStore` (`upsert_questions`, `answers`, `earlier_answers`, `entities_with_looks`, `create_looks`).
  The write goes through the `structure_write` tool. Three parity cases were added and recorded from the legacy engine, because
  the existing fixtures never reached the prose path with a model: a prose drama cut by rules, a model cut that keeps every
  spoken line, and one that drops a line (refused, rules cut it, a warning says so).
- **A bug in the legacy engine, found by porting.** `structure_build/engine/prose.py` `sections()` raises `ValueError` (a strict
  `zip`) for any text with no `Episode n` line, and `convert()` is called for every document whose role is script, outline,
  bible or other and that has no scene headings. A plain bible or notes file with neither would fail the whole build. The ported
  step returns no episodes instead (the document is left to the parser), and a test pins both behaviours. **The legacy file is
  untouched**, because `AI_ENGINE=legacy` is the default and that is a change to what runs today; the one-line fix there is
  `if not heads: return []` before the loop.

### 5. frame_render, 6. script_split, 7. shot_producer (done)

Same loop for each: code halves into steps, ports with a Supabase adapter and a fake, the system, the `graph` branch in the
parity adapter, a mutation check, the thin handler, `"ai": true` in the deploy workflow and the import contract.

- `frame_render`: step `frame_compose` (the legacy `FrameJob` with its reads handed in as a `World`: which sheets are
  attached, the prompt, the pins, what the vision check expects, the advisory chips). New port `FrameStore` (frames, claims,
  looks, reference assets, audit). The painter is the `images` port; the vision check is the `frame_inspector` agent, left out
  when there is no key or `OPENAI__MODEL_VISION=""`. Frames are painted by a pool of four, **each in a copy of the caller's
  context** (a `ContextVar` such as the test model door does not reach a pool thread by itself). The composition root
  `build_context(payload, jobs=..., images=True)` adds the painter. `tests/hiru_ai/test_frame_render_system.py` runs the
  cases the fixtures do not reach (look sheets, frames that wear a look, the vision chips) on both engines.
- `script_split`: three steps. `rules_plan` (the planner's rules half, unchanged), `scene_prep` (beats, reading, staging
  and the teleport walk: each model call is an `ask(items)` the system closes over, so the engine's own control flow and
  fallbacks are kept), `split_write` (rows, fit report, staging report, breath given up, continuity notes, build-log
  lines). New port `SplitStore`. The system is `load -> plan -> wrap`; waves of four scenes, the 420 s budget and the
  `again` hand-off are the engine's. The `plan_review` panel runs the critics and the one revision. The three critic agents
  now accept what the engine accepted (a plain string note, an out-of-range severity) through a `before` validator; the
  wire schema is unchanged. The order in which the three parallel critic calls arrive means nothing, so both engines'
  parity records put each run of them in lens order (two fixtures were re-recorded for that and nothing else).
  `tests/hiru_ai/test_script_split_system.py`: the time budget, the model's reading and staging, and each step against its
  legacy function.
- `shot_producer`: the shot model already lived in the `serialize` step, so the producer's code halves (`intent`, `shots`,
  `techniques`, `continuity`, `critique`, `design`) are modules **of that step**: a sibling step cannot import the shot model
  (ADR 0009), and a sixth step would have had to copy it. Each model call is an `ask(...)` closed over by the system (the
  four agents), so retries of missing shots, the partial answers and the rules fallbacks are the engine's. The design-and-review
  loop is the `shot_review` panel with the producer's three seams (`write`, `critique`, `accept`). New port `ProducerStore`.
  Technique lookup uses the `search` port and the embedding door. `tests/hiru_ai/test_shot_producer_system.py`.
- Job kind of the producer is `shot_produce` (`contracts.jobs`), not `shot_producer`.

### 8. director_chat (done)

A turn is a synchronous **stream**, so the system has no `JobKind` (`job_kind: ""`; the contract test allows that).

- **The graph is the turn's shape**: `read -> conduct -> [confirm | translate | reshape | edit | follow | options] -> settle ->
  remember -> advise -> reply`, with `conduct` as the router. Nodes send the engine's own events (`status | plan | delta |
  message | done | error`) through LangGraph's custom stream, so the shapes the frontend reads are the engine's, byte for byte
  (the 8 event-stream fixtures, plus `tests/hiru_ai/test_director_chat_system.py`: a question answered through the read tools,
  options then a confirmation applied in code, the choice endpoint, both engines compared).
- **Code halves** went into the `scene_kernel` step (it holds the kernel class; a sibling cannot import it): `conductor`
  (rules, backstop, `by_model(ask)`), `options`, `translate`, `pending`, `loop`, `proposals`, `tools` (the director's four read
  tools) and `turn_logic` (`kernel_for`, `describe_op`, `TurnState`, `template_reply`, pin/unpin, `persist`...). The system's
  `edits.py` is the engine's `_edit`, `_stage`, `_stage_translation`, `_follow_up`, `_confirm_pending`; their only change is
  that every model call is `models.<x>` (`models.py`: the agents by id, the specialists and advisors through the
  `director_board` panel). `choice.py` is the engine's, in the system (it needs `ripple`, which uses the kernel step).
- **New port `DirectorStore`** (`DirectorView` gives the turn's code the engine's store method names over the ports).
- **New agent shape `text`** (`core/agents.py`): `Agent.stream(...)` for a reply read as it is written and
  `Agent.tool_rounds(...)` for the read-tool loop, both inside the agent's middleware (usage rows, static prompt first).
  Agents `reply_writer` (medium, `director.reply`, streamed) and `chat_answerer` (high, `director.answer`, tool rounds) are the
  plan's `reply_writer`. A failure while streaming is answered in code by `template_reply`, as before.
- The conductor, options and specialist schemas accept what the engine accepted (an operation or answer with a field left
  out); the wire schema is unchanged.
- Test model: `RoutedChatModel` can return whole messages (tool calls), cuts a streamed reply where told, and takes the phase of
  streamed calls as a setting, because LangChain gives a streamed call no metadata.

### 9. The API's `answer()` (not done: a decision for you)

The API image carries no LangChain, and `answer()` (and `rerank`, `embed_query`) are async calls on the `openai` SDK that the API
shares with its tests. Moving them onto `get_llm` means adding LangChain to the API's dependencies and image and relaxing the
import contract "the api reaches hiru_ai only through the pure rag modules". Nothing else in the plan depends on it. Say if you
want it, and it is one more agent (`source_answerer`) and a thread-pool call from the API.

## Phase 6 state at the end of the migration

- Gates: `ruff check src tests scripts infra/assemble` clean; `mypy` clean (491 files); `lint-imports` 19 kept; `hiru-ai validate`
  84 parts, 0 errors, 0 warnings; `hiru-ai catalog --check` current.
- `pytest -q`: 2432 passed, 0 skipped, 6 failed. The 6 are the same `tests/api` failures as before Phase 0 (`test_handoff.py` x2,
  `test_looks.py`, `test_production.py` x3). There are no skips any more: every fixture runs on both engines.
- Per-service `mypy` (as CI runs it) is clean except `shot_producer/engine/feeling.py:161` (an untracked, uncommitted file
  that was in the tree before Phase 0; not touched here).

### Not proven (Phase 6)

- Nothing ran against the hosted dev database or a live OpenAI key; the `graph` engines are held to the legacy ones through the
  Phase 0 fixtures, dual-engine tests and the core fakes only. A first live run with `AI_ENGINE=graph` (one small document for
  `doc_ingest`, one frame, one chat turn: a person's call) is the check to make before relying on any of them. It would settle:
  pgvector literals in chunk rows, prompt-cache hits and token counts on a real call (unproven since Phase 1), the strict JSON
  schemas of the typed agents against OpenAI itself, streamed usage rows, and Cloud Run cold start with LangChain in the zip.
- The hashed requirement sets: `pydantic-settings` was missing from `requirements/hiru_ai*.in`; it is added to both `.in` files,
  **but the `.txt` locks were not regenerated** (`uv` is not installed here). The migrated functions' `requirements.txt` carry the
  pins unhashed in the meantime. Re-run `scripts/lock_hiru_ai.ps1`.

### Open items (Phase 6)

- The API's `answer()` (above: a decision).
- Re-lock the hashed sets, then switch the functions to them.
- ADR 0008 (tracing), `token_usage` columns for component id and prompt hash, which tiers fall back to which, Renovate for the sets
  (unchanged).
- The legacy `prose.sections` bug (above) is for you to decide on.

## Phase 7: developer experience (done 2026-11-03)

`hiru_ai/cli/tools.py`, `cli/evals.py`, `tests/hiru_ai/test_dev_tools.py` (15 tests).

| Exit item | State |
|---|---|
| `hiru-ai remove <kind> <id>` | lists every part that names it (a dry run); with `--yes` drops the references from the manifests (flow lists, block lists, panel members written over one or several lines) and deletes the folder. It refuses while a required role (`judge`, `reviser`, `writer`, `critic`, `settle`) names the part: someone must choose another first |
| `hiru-ai graph <id>` | the Mermaid of a system or panel (their `blank()` factory) |
| `hiru-ai catalog [--check]` | [docs/AI_CATALOG.md](../../docs/AI_CATALOG.md): every part, owner, tier, what it uses and who uses it. CI runs `--check` and a test does too |
| `langgraph.json` | `hiru-ai studio` writes it: every system and panel as a graph over in-memory ports, for `langgraph dev`. Checked in and checked current by a test |
| env overlays | `HIRU_AI__DISABLE=agent:advisor,tool:x` disables parts for one environment (a typo is a problem, not a no-op); `models.<env>.yaml` (`HIRU_AI__ENV`, else `ENVIRONMENT`) is laid over `models.yaml` key by key |
| "a teammate adds a craft with only §8 and the CLI" | tested on a copy of the package: `hiru-ai new agent lighting`, one `members:` line on `director_board`, and the panel's manifest validates. **One limit:** the conductor's task schema names the four crafts (`cinematography`, `timing`, `sound`, `continuity`), so a new craft joins the board but is not tasked by the conductor until that list gains it |

## Phase 8: observability, evals, clean-up (partly done)

Done:

- **Evals.** `hiru-ai eval [agent] [--live] [--prompt FILE]`: every agent's cases, scripted (the CI gate, 100 % must pass) or
  answered by the real model (costs money: only a person runs it); `--prompt` runs the same cases through another system prompt,
  which is the A/B of two versions of an agent's prompt. A case passes when its `expect` is contained in the answer.
- **Docs.** `docs/AI_ARCHITECTURE.md` and this file say what is built; `docs/AI_CATALOG.md` is generated.
- Tracing tags (component id, version, prompt hash, phase) already travel on every agent call (Phase 1); the tool is ADR 0008.

**Not done, on purpose: removing the legacy engines.** The plan's Phase 8 deletes the `legacy` engines, the `AI_ENGINE` switch, the
duplicated `runtime/` files and the service rule in `tests/test_isolation.py`, and moves the `UPSTREAM.md` notes to `docs/archive/`.
That is the plan's own rollback path, and nothing has run live (see "Not proven (Phase 6)"). It would also delete what the
parity fixtures, the step and agent parity tests and ~1,500 service tests are compared against. So it waits for you. When the
live run has been made and `AI_ENGINE=graph` is the default in dev:

1. flip the default in each handler, deploy one function at a time, watch `token_usage` and the job events;
2. then delete `src/services/*/{engine,runtime}`, `AI_ENGINE`, `tests/services/*`'s legacy tests (keep the fakes the parity adapters
   use or move them to `tests/parity/`), the `legacy` branch of `tests/parity/adapters.py` (the fixtures stay as recordings), and the
   service rule of `tests/test_isolation.py`;
3. rewrite `CLAUDE.md` "Boundaries" and "Jobs" for the new layout (it describes both today) and archive the `UPSTREAM.md` notes.

Not done either: ADR 0008 (a decision for you: LangSmith, Langfuse or OpenTelemetry to Cloud Trace), a per-system golden-run
eval gate (the parity fixtures are those runs, but are replayed only against fakes), and the API's `answer()`.
