# Hiru AI Studio backend — working rules

Read the current plan first: [plan/2026-10-23/PLAN.md](plan/2026-10-23/PLAN.md) (design, phase
order, decisions log in §14), then [plan/2026-10-23/IMPLEMENTED.md](plan/2026-10-23/IMPLEMENTED.md)
(what is built, deviations, open items). Code comments cite it as "PLAN.md §n". Implementation
goes one phase at a time; at the end of a phase, update IMPLEMENTED.md. A new plan revision goes
in a new `plan/<date>/` folder.

## Fixed decisions (ask before changing any)
- **LLMs are OpenAI only.** Ask the user before using Gemini or any other Google model. The one exception is RENDERING A TAKE
  with Gemini Omni Flash or Veo 3.1 (plan/2026-11-06c, PLAN.md Q1): the key is read by `video_render` alone and no Google model
  writes a prompt, a check or text.
- Supabase for auth, DB, storage, realtime and pgvector. **Hiru only** (single tenant).
- Proven PromptMotion engines are **forked**, not imported (PLAN.md §2.1). Each fork gets an
  `UPSTREAM.md` with the source path, commit (`1d748dc` at plan time) and every divergence.
- The UI shows **no credits or costs**, with ONE exception: a scene's total cost, for people who hold `VIEW_COSTS`
  (producer, director, admin; plan/2026-11-06d, below). `/v1/usage` returns a percentage only.
- Nothing is deployed until the user says so; everything is tested on localhost first.

## The AI package (`src/libs/hiru_ai`, plan/2026-11-03)
All eight functions have a second engine built from independent parts: agents, steps, tools, panels and systems are folders
with a `component.yaml`, found by id through the registry (`docs/AI_ARCHITECTURE.md`, `docs/AI_CATALOG.md`). A function runs it
when `AI_ENGINE=graph` (default `legacy`: the code under `src/services/*/engine` below is still the one that runs until the
plan's Phase 8 removal, which waits for a live run). `hiru-ai validate | list | new | run | graph | catalog | remove | eval`.
A change to a service's engine must be made in its part too (`tests/parity` fails when they drift). Parts never import each
other (import-linter), take models from `core.llm`, and reach the database only through ports.

A tool is a part with a contract (plan/2026-11-04, `docs/AI_ARCHITECTURE.md`): an `effect` (`read`, `stage` or `write`), a `guide`
that says when NOT to use it, small results (`response_format`, paging, a token budget), and errors that teach (`how_to_fix`,
`example`). **No agent may list a `write` tool**: a model changes data only by staging a card a person accepts
(`change_propose`, `memory_propose`). Scope (production, scene in scope, the person's own words) comes from `RunContext`,
never from a model's arguments. New tool: `hiru-ai new tool <id> --effect read --wraps <step>`.
An agent that answers in one call today can carry a `with_tools:` block in its manifest (its `react` form: tools, its own
prompt `prompts/system.tools.md`, loop caps). It runs only when `AGENT_TOOLS` names it, and an agent is named only after a
live `hiru-ai eval <agent> --ab base,tools --live` shows it at least as good. `hiru-ai mcp` serves the read and stage tools
over MCP; `hiru-ai review <log>` is the monthly look at tool errors and cut answers.

## Shot Planner Adam (`adam/` folders, plan/2026-11-04b)

A second shot planner built beside `script_split`, which it does not change. Its parts live in an `adam/` GROUP folder in
each layer (`agents/adam/`, `steps/adam/`, ...), plus `contracts/adam/`, `tests/adam/`, `tests/eval/adam/`, `docs/adam/`.
Ids start `adam_`; `hiru-ai new <kind> adam_x --group adam`; a grouped part names and imports only its own group (the
core, the rag and `contracts` aside); `hiru-ai remove --group adam` lists everything that goes. **Never invent story;
always elaborate the picture**: `adam_fidelity` refuses a new person, line, event or object (a line is named by id, its
words are the script's). Read `docs/adam/README.md` and `plan/2026-11-04b/IMPLEMENTED.md` first (what is built, what waits
for a person). Phases 0 to 10 are built offline: the agents take a wire shape from `contracts/adam/wire.py` and have no
fallback; the system is `adam_shot_planner` (job `plan_scene_adam`, function `shot_planner_adam`); a production chooses it with
`settings.shot_planner`. The live runs (`scripts/adam_live.py --yes`), the A/B and the default are a person's; the gold masters
are drafts until a Hiru director approves them. Plan/2026-11-04c made the system defend the scene
(`plan/2026-11-04c/IMPLEMENTED.md`): a score held to the masters by mutation tests, `adam_coverage` (the faces the analysis
says must be seen), `adam_split` (a crowded card is repaired, never deleted), `adam_ledger` (no moment leaves without a
record), the reviser's dispositions (every note answered), and `report.history`. Phases 1 to 6 are built offline; the live
verification (`scripts/adam_live.py --yes --runs 3`) is a person's.

Plan/2026-11-05 added a second way to plan a scene (`ADAM_MODE=take`, default `staged`): `adam_take` writes the plan in ONE call,
`adam_critic` reads it once in four lenses, and the fixer ladder (`systems/adam/adam_shot_planner/ladder.py`, tiers in
`fixer.yaml`) fixes one problem at a time, a small model first and a bigger one only when code refuses the small model's fix
(`plan/2026-11-05/IMPLEMENTED.md`). Phases 0 to 4 are built offline; the spike (`scripts/adam_take_spike.py --yes`), the live
gate, `Database/upgrade_v11_to_v12.sql` (+ `USAGE_DETAIL=true`) and the default are a person's. Costs appear in the live scripts and
`IMPLEMENTED.md` only, never in the interface.

## Production memory (plan/2026-11-05d)

What the documents say about HOW to make the drama (genre, palettes, lenses, lighting, sound, edit ...) is a list of entries,
never a form: `memory_reader` reads each document at ingest, `steps/memory_check` keeps only entries whose quote is in the text,
and the `production_memory` middleware adds the entries that concern a call to the END of an agent's user message. An agent
subscribes with `middleware: [..., production_memory]` and `memory: [camera, lighting]` (`*` = all) in its manifest; `fact` and
`must` entries reach every subscriber; an agent's `memory_scope(inp)` hook narrows `place:`, `character:` and `episode:` entries.
No entries gives a call identical byte for byte. Drafts are used and labelled `(draft)`; a rejected entry never is. Conflicts
(`steps/memory_conflicts`) are reported on the job's events, never resolved. Read `plan/2026-11-05d/IMPLEMENTED.md`: phases 0
to 4 are built offline, `production_memory` is in `Database/schema_v12.sql` and **not applied**; the live check and the
interface are a person's.

## Shot Planner David and the Hiru AI pattern (`david/` folders, plan/2026-11-05e)

A third shot planner, beside `script_split` and Adam, which it does not change, and the first system built on **the Hiru AI
pattern** (`docs/AI_PATTERN.md`, ADR 0010): ONE strong-model author call per creative unit that returns its work and an end
state; code checks facts and mends what it can; the same model repairs only the exact problems it is shown, with a patch, at
most twice, then the rest is reported; **a quality problem is fixed in the prompt, the pack or a code check, never by adding
an agent** (rule 8). Same group rules as Adam: parts in `david/` folders (`agents/david/`, `steps/david/`, `systems/david/`),
`contracts/david/`, `tests/david/`, `tests/eval/david/`, `docs/david/`, ids start `david_`, `hiru-ai remove --group david` lists
what goes. David plans a scene's shots AND their camera (the Veo clip IR) in one call, so the shot producer skips the intent
agent, the DoP and the critic for its shots (`"david"` is in `contracts.staging.AUTHORED`; `david_write` stores `ir` and a
`design` whose pins are current). The rules are code in `contracts/david/` (`checks.py`, `mend.py`, `links.py`, `seams.py`);
the closed lists, the wire shapes and `scenes.david` are `plan.py`, `wire.py`, `stored.py`. A production chooses it with
`settings.shot_planner = "david"`; scenes that carry on from the one before run in order and pass their end state and last shot
on (`settings.david_order`, D5); the system is `david_shot_planner` (job `plan_scene_david`, function `shot_planner_david`,
port 8210); the tiers are `author` and `repair` (`OPENAI__MODEL_AUTHOR`, `OPENAI__EFFORT_AUTHOR`, `OPENAI__EFFORT_REPAIR`).
Read `docs/david/README.md` and `plan/2026-11-05e/IMPLEMENTED.md` first. Phases 0 to 5 are built offline; the spike
(`scripts/david_spike.py --yes`), the blind comparison (`scripts/david_compare.py`), the decisions D2 to D7 and the default are a
person's. Costs appear in the spike's output and `IMPLEMENTED.md` only, never in the interface.

## Shot Planner Jonathan, the cinematic planner (`jonathan/` folders, plan/2026-11-06b)

A fourth shot planner, beside `script_split`, Adam and David, none of which it changes. It is the cinematic lab's result
(`lab/cinematic/`, plan/2026-11-06, `RESULTS.md`): a treatment (logline, arc, approach, colour script, geography, key image),
sequences, then shots with lens, angle, a story purpose and `use_s`, kept steady by a **stabiliser**: ONE author call, code
checks facts and measures craft, then up to TWO revise calls that give the author its own best draft back with the findings
(the best plan is kept; a worse pass is never built on). Not an agent: model calls in a fixed order, code in between. Built
the way David was built from Adam: independent groups, so Jonathan has its own copy of the parts (`agents/jonathan/`,
`steps/jonathan/`, `systems/jonathan/`, `contracts/jonathan/`, `tests/jonathan/`, `tests/eval/jonathan/`, `docs/jonathan/`),
ids start `jonathan_`, `hiru-ai remove --group jonathan` lists what goes. It never imports Adam or David. The system is
`jonathan_shot_planner` (job `plan_scene_jonathan`, function `shot_planner_jonathan`, port 8211); the tier is `jonathan`
(`OPENAI__MODEL_JONATHAN`, default `gpt-6.1-sol`, at `OPENAI__EFFORT_JONATHAN`, default high, the effort the lab proved); a production chooses it with
`settings.shot_planner = "jonathan"`. **Status: Phase 0 is built (the group, the shared lists, the migration pair); the parts
are still David's copy renamed and run David's behaviour until Phases 1 to 3 port the lab into them.** Read
`plan/2026-11-06b/PLAN.md` and `IMPLEMENTED.md` first. The migration (`Database/upgrade_v12_to_v13.sql`,
`supabase/migrations/20261106120000_jonathan.sql`) is not applied; applying it, running a live scene, the gate and the default
are a person's. Costs appear in the lab's `RESULTS.md` only, never in the interface.

## Zora, the director chat over Jonathan's plan (`zora/` folders, plan/2026-11-06e)

A new director chat beside the classic one, which it does not change. It edits the plan Jonathan stores on a scene
(`scenes.jonathan`): a small conductor transcribes the person's changes as operations and tasks, code applies them on
stable handles and works out what went stale, ONE author call (tier `zora`: Jonathan's model and prompt) does the craft,
Jonathan's own mend and checks gate it (only faults the turn introduced count, at most two repairs), and the reply is
written from a ledger of exactly what changed (`nothing_changed` explicit). Group rules as Jonathan's (`agents/zora/`,
`steps/zora/`, `systems/zora/`, `contracts/zora/`, `tests/zora/`, `docs/zora/`, `lab/zora/`); it reaches Jonathan only
by id. The system is `zora_chat` (function `hiru-zora-chat`, port 8213, streamed like the classic chat; API
`routers/zora.py`; panel `features/zora/`). Rules that must not drift: **a line's words are never written** (lines are
bound by code; overruns are reported with the way out, never trimmed); **a lock is the person's** (no model writes a
locked field; what the person sets is locked); a save goes through `jonathan_write` and keeps every shot's id; undo is
a `scene_plan_revisions` row (schema v14). It runs only when `ZORA__ENABLED` and the scene has a Jonathan plan (D3).
Read `plan/2026-11-06e/IMPLEMENTED.md` first: phases 0 to 8 are built offline; the lab's paid run, applying v14,
turning it on, the Figma frames (D8) and the live check are a person's. No costs in the interface.

## Sable, the production assistant chat (`sable/` folders, plan/2026-11-08)

A second chat beside Zora, which it does not change: ONE react agent (`sable_agent`) that answers, finds, checks and
explains across the whole production with the shared read tools (listed in `agents/sable/group.yaml` `shared:`) and its
own three (`sable_overview`, `sable_scene_find`, `sable_think_harder`). It changes nothing itself: a change is a staged card
(`change_propose`, `memory_propose`) a person with DIRECT accepts, and a scene's plan edit is a handoff card that opens the
scene with the request in its chat's draft. A turn starts on tier `sable` (average) and the generic `tiering` middleware
(`core/middleware/tiering.py`) moves it ONCE, upward, to `sable_deep` (pre-route `steps/sable/sable_route`, the model's
`sable_think_harder`, or code signals). System `sable_chat` (function `hiru-sable-chat`, port 8214; API `routers/sable.py`;
panel `features/sable/`). Rules that must not drift: **Sable imports nothing of Zora's** but `api/services/zora.routes_here`
(`tests/sable/test_zora_untouched.py`); **a quoted line no tool returned is taken out** (`guard.py`); **no tier, model or
tool id reaches a browser** (a reply's record is `chat_turn_meta`, admin-read only); **a thread is one person's own**.
Off until `SABLE__ENABLED`; it needs schema v18 (not applied). Read `plan/2026-11-08/IMPLEMENTED.md` first: phases 0–3 and
5–7 are built offline; the question set, the lab, applying v18 and the live check are a person's.

## The document reader (plan/2026-11-06f)

The model reads a whole uploaded script, bible, canon index or outline ONCE at ingest into one format
(`contracts/doc_read.py`), kept beside the text (`documents.reading_path`); the structure build and the canon extraction
then use that reading instead of the rules, and nothing after them changes. The run (pieces, calls, checks, at most two
repairs, the merge) is pure code in `contracts/doc_read_run.py` with its model calls passed in, so both engines share it:
the graph passes the `reader/` group's agents (`reader_canon`, `reader_episode`, `reader_repair`; tier `reader` =
OPENAI__MODEL_AUTHOR at OPENAI__EFFORT_READER), the doc_ingest service its own `runtime/llm.py` (prompts copied into
`engine/reader_prompts/`; a test holds them equal: change both). A PDF whose Sinhala text layer is scrambled
(`contracts/doc_read_quality.py`) is read from its page images (a Chat Completions `file` part); its scenes carry
`read_from = "pages"` and wait for a person to confirm their dialogue, and its clean transcription replaces the text for
search and memory. Rules that must not drift: **dialogue is never invented, translated or tidied** (text mode checks
every word against the source lines); **only what is written** (a canon entry whose quote is not in the text loses its
description); a failed read leaves the rules, and the job says why. Off until `READER__ENABLED` (a person turns it on
after `scripts/eval_reader.py --yes`); it needs schema v16. Read `docs/reader/README.md` and
`plan/2026-11-06f/IMPLEMENTED.md` first.

## Video generation in Hiru (plan/2026-11-06c)

A person can make a shot's take in Hiru with Omni Flash (default) or Veo 3.1, beside the upload from Flow. The pure rules are
`contracts/video_gen.py` (capabilities, the three settings layers, references with their binding and ORDER, the seed, the
request adapters, `validate_render` / `check_render`); the function is `src/services/video_render/` (a fork of PromptMotion's,
`UPSTREAM.md`, port 8212, `JobKind.VIDEO_RENDER`); the API is `routers/renders.py` + `services/renders.py`; storage is
`video_renders`, `takes.origin` / `render_id`, `shots.video_settings` (schema v14: `Database/schema_v14.sql`, `upgrade_v13_to_v14.sql`). Rules that must not drift:
**order is the list order** (never sort or de-duplicate references: Omni numbers them by position); **attached == cited** (the
citation block is built from the same list as the payload); **labels are words** (a code, id, path or hash is drawn as
lettering); **checks report, they never edit** the prose or a person's list; **every take records the seed it was sent with**
(drawn before dispatch); a browser never holds a storage path (it names a picture by kind and id; the server resolves it);
`Permission.RENDER_VIDEO` (producer, director, admin) guards spending; no costs in the interface. What each engine accepts
(`EngineCapability.seed`, `verified`) is settled by `scripts/video_probe.py`, a person's to run. Read
`plan/2026-11-06c/IMPLEMENTED.md` first.

## A scene's production cost (plan/2026-11-06d)

The scene panel's header shows ONE figure, "Scene ≈ $20.86": what the scene has cost plus what it will cost to finish. The
rules are `contracts/costs.py` (pure; money in integer micro-dollars; margins in basis points); the arithmetic's inputs are
gathered by `api/services/costs.py` and served by `routers/costs.py` (`GET .../scenes/{id}/cost`, `VIEW_COSTS`; the admin
price list `GET|PUT /v1/prices`); storage is `prices` and `token_usage.scene_id` (schema v17: `Database/schema_v17.sql`,
`upgrade_v16_to_v17.sql`). Rules that must not drift: **each margin is applied once**, in `with_margin` / `with_retry` only
(video +10%, images +5%, text 0, then +20% retry on the TO-FINISH part only); **a missing price is a note, never zero and
never a guess** (`complete: false`); **the response is the total and two flags and nothing else**, so no breakdown, rate
or margin can leak through the network tab; **nothing stores a money figure**: a cost is metered usage x the price valid
when the work was made, and prices are added with a `valid_from`, never edited; a model name is priced only if it is a listed
name or a dated snapshot of it (a bare prefix once billed gpt-5.5 as gpt-5). Read `plan/2026-11-06d/IMPLEMENTED.md` first.

## Boundaries (tested in `tests/test_isolation.py`)
- `contracts` imports only pydantic + stdlib. Every function bundles it.
- A function under `src/services/<name>/` imports only its own package and `contracts`.
  Never `api`, never another service. It vendors what it needs (e.g. its own `runtime/store.py`).
  Scripts in `scripts/` may import a service's engine (one chunker, one embedding path).
- Routers never query Supabase; all DB access goes through `api/repositories` (the `Repos`
  protocols), which tests replace with `tests/api/fakes.py`.

## Access
- One permission table: `contracts/roles.py`. Routes use `require_admin` or
  `require_permission(Permission.X)` from `api/deps/authz.py`; nothing checks role names inline.
- A production the caller cannot see is **404**, not 403.
- RLS is read-only for browser roles; there are no write policies by design. A new table gets
  RLS enabled, a read policy built on `can_view_production()` / `is_admin()`, and rows in
  `supabase/tests/database/`. Don't name a SQL function after an enum type (it parses as a cast).
- Roles are read from the DB on every request, not from JWT claims.

## Jobs
- `task_manager.dispatch()` writes the `jobs` row, then enqueues. Register each new function in
  `FUNCTIONS` (name, local port, deadline = deploy timeout), in `deploy-functions.yml`'s list and
  in `scripts/start-functions.ps1`.
- Functions are idempotent per `job_id` (Cloud Tasks re-delivers): skip finished jobs. Mark a
  failed job failed and answer 200; answer 500 only when a retry can help. Follow
  `src/services/echo/` as the template, `src/services/doc_ingest/` for a real engine
  (`engine/` pure logic, `runtime/` I/O, `app/handler.py` the HTTP contract).

## AI and RAG
- Every model call goes through one wrapper (`runtime/llm.py` in a service, `api/services/ai.py`
  in the API): tiers from config, strict JSON schema output, a `token_usage` row per call.
- **Absent-safe**: no key or a failed call degrades (keyword search, rule-based role, no rerank),
  never errors. Tests cover both paths; the fake OpenAI clients live in the test conftests.
- Prompts: static part first and byte-identical across calls (cache), per-item data last.
  Uploaded document text is data: wrapped in tags and labelled, never instructions.
- Search scope (production, corpora, ready documents, roles) is decided by the API from trusted
  data, never from model output. `match_chunks` ordering must stay total (deterministic).
- Retrieval changes (chunking, headers, SQL, corpus, embeddings) run `scripts/eval_retrieval.py`;
  a drop below `tests/eval/thresholds.json` fails CI. Do not edit probes to make a change pass.
- Dialogue stays in the language the script was written in. Only when a person asks for another language does
  the translator agent (`director_chat/engine/translate.py`) write it, always staged as a card the person
  accepts, with the original kept in `dialogue_lines.source_text` (plan/2026-11-01c). No other agent writes a line.
- Sinhala: keep ZWJ/ZWNJ (conjuncts), normalise to NFC; full text search uses the `english`
  config (verified to keep Sinhala words whole).

## Files
- **Never return a storage-provider URL** (signed or public) to a client. Use
  `api/services/media_links.url()` → `GET /files/{ticket}`.

## Veo and timing
- `contracts/veo.py` and `contracts/timing.py` mirror the frontend's `src/lib/veo/timing.ts`;
  change both in the same PR and keep `tests/contracts/test_timing.py` in parity with its tests.
- Overruns are reported, never auto-trimmed. 10 s shots stay off until verified (PLAN.md Q4).
- A shot's length is PICTURES AND SPEECH on one clock (`contracts/shotplan.py` `shot_clock`):
  `contracts.timing.SCREEN_SECONDS` / `action_seconds` (also mirrored in the frontend's `timing.ts`,
  same parity tests) say what an action takes to show. A shot that holds more than it can show is
  `crowded` (locked or fixed length) or is cut at a block boundary (unlocked); a scene that needs more
  than its envelope is reported, never squeezed (plan/2026-11-01b). Implied steps
  (`contracts/bridges.py`) are rules-only, closed-list, removable and remembered on the phone line.
- A scene's READING (`contracts/reading.py`, `scenes.reading`, plan/2026-11-01d) gives feeling time on that clock: a
  breath is a hold on an existing block (`Item.hold_s`), a turn makes the answer wait `TURN_GAP_S`. Read a scene's items
  with `sceneplan.scene_items(scene, lines)` wherever timing matters. Priority-1 breath is never dropped by code, a
  person's reading is never replaced, and model critics write notes while the kernel score in code picks the plan.
- A scene's STAGING MAP (`contracts/stagemap.py`, `scenes.staging`, plan/2026-11-01d Phase 4) says where each person is
  from a block on. Code finds teleports, crossed lines and broken eyelines; the only thing it writes is one removable
  "crosses to the gate" step per teleport (`bridges.move_block`, `bridge: "move:<who>"`), remembered when removed as
  `skip_bridges` on the block after it. Model critics (coverage, emotion, editor) write notes; `critic.kernel_score` picks.
  The shot producer reads the reading and the map through `shot_producer/engine/feeling.py` (`beats[].performance`,
  `subjects[].position`).
- `contracts/producer.py` `CAMERA_OPTIONS` mirrors the frontend's
  `src/features/production/lib/camera-options.ts`; change both together.
- Designs, frames and prompts are never redone when something upstream changes: they record
  `Pins` and the API reports them out of date (`api/services/production.py`).

## Conventions
- Settings via `get_settings()` only (`lru_cache`); nested env vars use `__`.
- **The hosted project `dwivfkavmtjzhypqswze` is the ONE dev database** (the user's decision,
  2026-10-24): the API, functions, frontend and scripts point at it. The local Supabase stack is
  only a throwaway database for `supabase test db`, schema verification and CI; never treat it as
  where dev data lives, and stop it after use. Smoke scripts write test data to the hosted
  project, so ask before running them.
- **Hosted dev DB** is managed by hand from [Database/](Database/README.md):
  each `schema_vN.sql` is the WHOLE schema at version N (the user runs it on an empty project), and
  `upgrade_v(N-1)_to_vN.sql` moves an existing project up one version. No per-change files
  (the user's rule). A structural change is a migration (local stack + tests) AND goes into the
  next version's pair, in final form (policies and indexes next to their tables); while that
  version is unreleased, fold further changes into the same pair. Verify by dumping
  `public,storage` from the migration-built DB, from vN loaded into an empty DB, and from v(N-1) +
  upgrade: all three must match. Never run SQL against the hosted project myself unless the user asks.
- Migrations: new timestamped file in `supabase/migrations/`; never edit one that has been
  applied to staging or prod (none has been yet).
- Before finishing a step: `ruff check src tests scripts`, `mypy` (and per service, as in CI),
  `pytest -q`, `npx supabase test db`, `npx supabase db advisors --local --level warn`, and for
  retrieval changes `scripts/eval_retrieval.py` (`--runs 3` in hybrid mode).
- Schema work: follow `.claude/skills/supabase*` (installed). Create migration files with
  `npx supabase migration new <name>`; never hand-pick the timestamp.
- Tests never call OpenAI or any network service. API tests force `OPENAI__API_KEY` empty.
