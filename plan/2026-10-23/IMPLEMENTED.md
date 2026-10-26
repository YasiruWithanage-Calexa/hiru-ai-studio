# Implemented so far (against PLAN.md of 2026-10-23)

Status on **2026-10-24**: Phases 0–3 are built and verified on localhost, each including a real
OpenAI run; Phase 3's was against the hosted dev database. Phase 4 is built and verified the
same way: the hosted project runs schema v3 (2026-10-24) and the Phase 4 smoke test passed on it
in rules mode and with OpenAI. The frontend's overview, episode, Director and Production screens
now read the real API (see "Frontend wiring"). Phase 5 (handoff) is built and tested locally;
it needs schema v4 on the hosted DB (`Database/upgrade_v3_to_v4.sql`, not run yet). Every
frontend screen now reads and writes the real API: no screen reads mock data. Supabase agent skills (`supabase`,
`supabase-postgres-best-practices`) are installed in `.claude/skills/`. **Nothing is deployed** (by
decision: test locally first). Commits are made by hand.

| Phase | Steps | State |
|---|---|---|
| 0 — Foundations | 1–6 | Done locally. Terraform and CI written and validated, not applied. |
| 1 — Documents and RAG | 7–9 | Done locally, in keyword mode and (with an OpenAI key) hybrid mode. |
| 2 — Structure and canon | 10–13 | Done locally, rules-only and with OpenAI. See "Phase 2" below. |
| 3 — Director panel | 14–16 | Built: function, API, migrations, tests, replay, hygiene guards. See "Phase 3". |
| 4 — Production panel | 17–19 | Done: two forked functions, API, migration, schema v3 on the hosted DB, smoke with OpenAI, frontend panel wired. See "Phase 4". |
| 5 — Handoff | 20–21 | Built and tested locally; hosted DB needs `upgrade_v3_to_v4.sql`. See "Phase 5". |
| After 5 | — | The director chat edits the Script column (2026-10-26). See "After Phase 5". Needs `Database/upgrade_v4_to_v5.sql` on the hosted DB. |
| 6 | 22 | Not started. |

## Verification at the end of Phase 5 (2026-10-24)

- Backend: `pytest` 501 passed (incl. `tests/contracts/test_handoff.py`, `tests/api/test_handoff.py`,
  `tests/infra/test_assemble.py` with real ffmpeg, `tests/api/test_studio_screens.py`); ruff and
  mypy clean. Terraform `validate` passes with the new `assemble` service.
- Database: 126 pgTAP tests pass on the migrations, on `schema_v4.sql` alone and on v3 +
  `upgrade_v3_to_v4.sql`; the three dumps are identical.
- Frontend: `npm run check` (lint, types, 43 tests) passes; `next build` passes. A browser tour
  against the local stack on the hosted DB (still v3) loads build, canon, canon entity,
  questions, activity, director library, Director and Production with no console errors. The
  handoff page fails there only because the `takes` table is not on the hosted DB yet.
- Not yet clicked through in a browser: takes upload/accept with a carried last frame and the
  bundle download (they need v4 on the hosted DB). The API tests cover them.

## Verification at the end of Phase 4

| Check | Result |
|---|---|
| Python tests (`pytest`) | **482 passed** (+44: `contracts.producer`, shot_producer design/prompts/hygiene/wording, frame_render, Production panel API incl. frame upload) |
| SQL tests (`supabase test db`) | **113 passed** (+19 in `005_production`: one accepted frame per shot, only finished frames accepted, prompt versions unique, cascades, private buckets, RLS, Realtime) |
| Lint / types | ruff clean; mypy clean for `api`, `contracts` and all eight functions |
| Schema lint / advisors | `supabase db lint`: no errors; `supabase db advisors --level warn`: no issues |
| Schema v3 | Dumps of the migration build, of `schema_v3.sql` alone and of `schema_v2.sql` + `upgrade_v2_to_v3.sql` are identical (buckets, Realtime, personas, `graph` too); 113 tests and advisors pass on the upgraded one |
| `upstream_diff.py` | Both new forks read; nothing changed upstream since `1d748dc` |
| Phase 4 smoke, rules only, **hosted DB** | **Passed, 23 checks** in 53 s: panel locked until approval, writer 403, design by rules, a person's lens, frames report "not set up" without a key, accept → prompt with Nimal's line byte for byte, stale after a longer S02 and a new card for Kamala, prompt v1 kept |
| Phase 4 smoke **with OpenAI, hosted DB** | **Passed, 25 checks** in 323 s: scene designed by gpt-5, two frames painted (`gpt-image-2`), the person's 85mm in the frame prompt, prompt v1, a reference sheet for Kamala. A follow-up frame for S04 attached her sheet (`images.edit`) and kept her look from the new card |
| Frontend (`hiru-ai-studio-interface`) | `npm run check`: lint, types, **43 tests** pass (+4 for the scene mapping); Prettier clean on every changed file. Driven in a browser (Playwright, signed in as the smoke admin): overview, episode, Director, Production (three shots) and handoff all render real data; accept → prompt (Sinhala shown as `lang="si"`), a lens change flags the prompt out of date and putting it back clears it, an uploaded frame appears and can be accepted; no page errors or failed API calls |

Found by the real runs and fixed:
- `gpt-image-1` is listed on the account but refused ("does not exist"); the image tier now
  defaults to **`gpt-image-2`** (`gpt-image-1.5` also works; the `gpt-image-2.5-*` models carry
  preview code names and were not used).
- Prompt wording: a lowercase move after a full stop, doubled full stops where the model's text
  already ended with one, a stop before " — ", and "(the person)" for a character whose card
  has no gender or wardrobe (now no tag at all). Regression test added.

Tooling notes: the machine's global Supabase CLI (2.107) rejects `supabase/config.toml`; use the
CI version, `npx -y supabase@2.121.0 ...`. `.env` has Windows line endings: a shell loader must
strip them (`tr -d '\015'`) or every value ends in `\r`. The Phase 4 smoke data on the hosted DB:
productions "Phase 4 smoke …", admin `smoke-p4-admin@hirutv.lk`, users `director-/crew-/writer-…@hirutv.lk`.

Tooling note: the machine's global Supabase CLI (2.107) rejects `supabase/config.toml`; use the
CI version, `npx -y supabase@2.121.0 ...`.

## Verification at the end of Phase 3

| Check | Result |
|---|---|
| Python tests (`pytest`) | **438 passed** (+73: scene-plan kernel, conductor rules, whole turns with a fake store and model, prompt hygiene, replay gate, scene and director API) |
| SQL tests (`supabase test db`) | **94 passed** (+25 in `004_director`: constraints, deferred renumbering of shots and lines, cascades, RLS on every new table, Realtime) |
| Lint / types | ruff clean; mypy clean for `api`, `contracts` and every service |
| Schema lint / advisors | `supabase db lint`: no errors; `supabase db advisors --level warn`: no issues |
| Director replay, rules mode | 11/11 rule cases (tune 100 %, held-out 100 %) |
| Director replay, **model mode** (real OpenAI) | First run: tune 78 %, held-out 71 %, and the reply described changes that were not made. After the fixes below: **tune 100 %, held-out 100 %, twice in a row** (~33k input / 49k output tokens per run of 16 cases, ~6 min) |
| Phase 3 smoke **with OpenAI, on the hosted dev DB** | **Passed, 34 checks** in 210 s: conductor on gpt-5-mini, answers on gpt-5, re-split planned by the model (0 kernel issues), memory embedded (`text-embedding-3-large`); it found the duplicate-memory bug below |
| Phase 3 smoke, rules only (`scripts/smoke_phase3.py`) | **Passed, 34 checks** in 28 s, real API + `director_chat` + `script_split` + local Supabase: scene view and timeline → writer 403 on lengths → director locks S02 at 8 s (ids kept, version 2) → writer edits a Sinhala line (shots kept, stale edit 409) → board set → streamed turns: an edit (saved, audited as `director_chat`), a reviewer (answered, nothing changed), a question, a standing rule (memory + `chunks`) → approve blocks chat and hand edits → re-split replaces the shot list |
| `upstream_diff.py` | Nothing changed upstream since `1d748dc` |

## Verification at the end of Phase 2

| Check | Result |
|---|---|
| Python tests (`pytest`) | **365 passed** (+96: shot-plan kernel, screenplay parser, canon helpers, the three new engines, build / canon / structure / courier API) |
| SQL tests (`supabase test db`) | **69 passed** (+20 in `003_structure`: constraints, cascades, RLS on every new table, `graph` schema closed to browsers) |
| Lint / types | ruff clean; mypy clean for `api`, `contracts` and every service (each with only its own package + `contracts` on the path) |
| Schema lint / advisors | `supabase db lint`: no errors; `supabase db advisors --level warn`: no issues |
| Phase 2 smoke, rules only (`scripts/smoke_phase2.py`) | **Passed, 37 checks**, real API + all five functions + local Supabase + the real Postgres checkpointer: upload 5 files → build → canon with index codes and voice pins → the build **stops on 2 questions** → a writer answers through the API → the last answer **resumes the graph** → episodes 1–5, 8 scenes, every line bound to a shot and a character, every shot 4/6/8 s → canon v2 by a producer, lock → rebuild **reuses the earlier answers**, keeps ids, keeps the locked card, no duplicates; writer 403s and cross-production 404 |
| Phase 2 build with OpenAI (real key, fixture production) | Passed through every stage: canon (gpt-5) + dedupe (gpt-5-mini), questions + resume, architect titles (gpt-5), 8 scenes planned by the model with critic review → 24 shots, **0 kernel issues**. Took ~15 min because scenes were planned one at a time; planning is now parallel (4) and time-boxed (see below). A second full smoke run with OpenAI on the parallel code was still running when this was written. |
| Retrieval eval | Not affected (chunking, headers and SQL unchanged; doc_ingest only also stores the extracted text) |

## Verification at the end of Phase 1

| Check | Result |
|---|---|
| Python tests (`pytest`) | 269 passed (contracts, API with fakes, echo, doc_ingest) |
| SQL tests (`supabase test db`) | 49 passed (`001_access`: 27, `002_rag`: 22) |
| Lint / types | ruff clean; mypy clean for `api`, `contracts` and `doc_ingest` |
| Schema lint | `supabase db lint`: no errors |
| Phase 0 smoke (`scripts/smoke_local.py`) | Passed: real Supabase sign-in (ES256 via JWKS), production create, RLS read + write block, invite e-mail, echo job via local function |
| Phase 1 smoke (`scripts/smoke_phase1.py`) | Passed: 22 checks, real producer and writer accounts, uploads, real doc_ingest function, search, roles, delete, cross-production 404 |
| Retrieval eval, keyword mode (`scripts/eval_retrieval.py`) | Production docs: recall@1 0.57, **recall@5 1.00**, MRR 0.74 · Craft: 0.25 / 0.75 / 0.46 · Techniques: 0.50 / 0.75 / 0.62. Identical across repeated full re-ingests. CI gate. |
| Retrieval eval, hybrid mode (real OpenAI, worst of 3 full ingests) | Production docs: recall@1 0.79, recall@5 1.00, **MRR 0.88** · Craft: 0.25 / **1.00** / 0.62 · Techniques: 0.75 / **1.00** / 0.80. Compared with a 0.05 tolerance (model-written headers vary between ingests). |
| Phase 1 smoke with OpenAI | Passed: hybrid search + rerank through the real API and function; every model call in `token_usage` (header calls served about half their input from the prompt cache) |
| Supabase advisors (`supabase db advisors`) | No warnings (CI fails on any warning); only "unused index" notes on an empty database |
| Container / infra | `docker build` + health check pass; `terraform validate` passes |

## Phase 0 — Foundations

**Step 1: Scaffold.** `pyproject.toml` (api + contracts packages; ruff, mypy, pytest), `.env.example`,
`.gitignore`, `.dockerignore`, `Dockerfile`, `README.md`, `CLAUDE.md`.
- *Deviation:* pip + venv instead of `uv` (not installed on the dev machine; nothing depends on it).

**Step 2: Contracts** (`src/libs/contracts/`, pydantic + stdlib only).
- `veo.py`: orientation, 4/6/8 s ladder (`snap_duration`, reachable totals), sound modes,
  camera link, frame strategy. `timing.py`: word targets, slow deliveries, overrun checks,
  default beats. Ported from PromptMotion, with test cases kept in step with the frontend's
  `timing.test.ts`.
- `roles.py`: the one permission table. `production.py`: Production → Episode → Scene → Shot
  wire models. `jobs.py`: job kinds, statuses, events, dispatch payload.

**Step 3: Supabase** (`supabase/migrations/20261023000000_foundation.sql`).
- Profiles (workspace role admin/member, active flag), productions, production members,
  invitations (applied automatically by a trigger when the invited person signs up), audit log,
  jobs, job events (Realtime). RLS is read-only for browser roles; all writes go through the API.
- Auth is invite-only (`supabase/config.toml`).
- *Deviations:* no organisations table (Q9: Hiru only); no custom JWT hook (roles are read from
  the DB on every request, so changes apply immediately); helper named `my_production_role()`
  (a function named after the enum type parsed as a cast).
- *Finding:* in Supabase Auth, disabling **e-mail** sign-up disables e-mail **login** too. Sign-up
  is closed with the global switch instead (also noted in the README deploy steps).

**Step 4: API skeleton** (`src/api/`).
- JWT verification against Supabase JWKS (ES256/RS256), legacy HS256 via secret; profile loaded
  per request (deactivation applies immediately). `require_admin` / `require_permission`.
- Endpoints: `/healthz`, `/v1/me`, `/v1/members`, `/v1/invitations`, `/v1/productions` (+ `/access`,
  `/members`), `/v1/jobs/{id}` (+ `/events`), `/files/{ticket}` (encrypted tickets, Range
  support; ported from PromptMotion).
- *Deviation:* PyJWT instead of PromptMotion's `python-jose` 3.3.0 (known CVEs).

**Step 5: Jobs.** `api/workers/task_manager.py` (job row first, then Cloud Tasks with OIDC, or a
local HTTP call), `src/services/echo/` as the function template (idempotent, 200-on-failure
contract).
- *Deferred:* the multi-hop courier (`/internal/pipeline/advance`) is not built; nothing needs it
  until Phase 2.

**Step 6: Infrastructure and CI** (written and validated, **not applied**).
- `infra/terraform/`: APIs, Artifact Registry, one service account per role, Secret Manager,
  Cloud Tasks queue, Cloud Run API service, Workload Identity Federation for GitHub.
- `.github/workflows/`: `ci.yml`, `deploy-api.yml`, `deploy-functions.yml` (deploys only changed
  functions, zip = service + contracts), `migrate.yml` (manual).

## Phase 1 — Documents and RAG

**Step 7: Upload and ingestion.**
- Migration `20261023060000_documents_rag.sql`: `documents`, private `documents` bucket,
  document status on Realtime.
- API (`routers/documents.py`): upload (25 MB; text-layer PDF, Markdown, plain text, Fountain;
  extension, magic-byte and binary checks; SHA-256 de-duplication per production), list (files
  needing role confirmation first), confirm role (re-ingests when chunking changes), re-ingest,
  delete. File links are `/files/{ticket}`, never storage URLs.
- Function `src/services/doc_ingest/` (`hiru-doc-ingest`, local port 8202):
  extract (PDF via pypdf, UTF-8/UTF-16 text, NFC with ZWJ kept, **scanned PDFs rejected, no OCR**)
  → role (rules first, model when unsure) → structure-first chunking (scene headings, Markdown
  headings, page ranges, overlap) → context header per chunk (always a base header, plus a model
  line when a key is set) → embeddings (reused by hash on re-ingest) → chunks replaced.
- *Added beyond the plan:* a warning for script PDFs with no Sinhala Unicode (legacy fonts such as
  FM Abhaya extract as Latin noise); a `rejected` status separate from `failed` (the file is
  unusable vs our failure); token usage recorded from the first model call (`token_usage`).

**Step 8: Hybrid retrieval.**
- `chunks` (one table; corpora `craft`, `production_docs`, `canon`, `memory`; `vector(1536)` +
  weighted full-text) and `match_chunks()`: vector and keyword ranks fused by reciprocal rank
  fusion, scoped before ranking, deterministic ordering, RLS applies to signed-in callers.
- API: `POST /v1/productions/{id}/search` (corpora, role filter, k, rerank) with citations
  (file, section, pages); `api/services/ai.py` (query embedding, rerank) and
  `services/retrieval.py`. Absent-safe: no key → `mode: "text"`, no rerank.
- *Deviations:* full text uses the `english` configuration, not `simple` (with `simple`,
  stopwords such as "the" matched every passage; Sinhala verified unaffected). Production corpora
  are searched by exact scan after scoping (more accurate at this size; the HNSW index is there
  for later).

**Step 9: Craft knowledge and evaluation.**
- `src/knowledge_base/` copied from PromptMotion (`UPSTREAM.md`); `scripts/ingest_knowledge.py`
  → 89 craft chunks and 61 camera techniques (`craft_techniques`, `match_craft_techniques()`,
  effect-first, unknown categories fall back to the whole domain);
  `POST /v1/craft/techniques/search`.
- `tests/fixtures/corpus/`: "Harbour Lights", an invented production (bible, script with Sinhala
  dialogue, canon index, outline, director's notes). `tests/eval/retrieval_probes.json`
  (14 production, 4 craft, 4 technique probes) and `scripts/eval_retrieval.py`, run in CI.
- *Finding fixed:* equal scores were returned in arbitrary order, so results changed between
  re-ingests of identical files; ordering is now total.
- *Advisor fixes* (migration `20261023071230_advisor_fixes.sql`): RLS policies evaluate
  `auth.uid()` and the argument-free helpers once per query (`(select ...)`), and ten foreign keys
  got covering indexes. The Phase 1 migration was renamed to `20261023060000_documents_rag.sql`
  (it had been dated a day ahead, which would have ordered it after this fix).
- *Finding fixed:* with a real key in `.env`, an API test that expects "no AI" built a real
  OpenAI client. API tests now force the key empty; AI paths are tested only with fakes.
- *Finding fixed:* the SQL tests counted all rows, so they passed on CI's fresh database but
  failed on a local database holding dev data. Each test file now empties the tables inside its
  own transaction (rolled back at the end, so dev data is untouched).

## Phase 2 — Structure and canon

**Design.** A structure build is **one job that runs three functions in turn**
(`contracts.build.BUILD_PIPELINE`): `canon_extract` → `structure_build` → `script_split`, so the 0b
screen follows a single `job_id`. Each function emits `stage` events (read, canon, episodes,
scenes, shots, continuity, review) and agent messages; `GET .../build` draws the stage list, the
agent strip and the chat from those events alone.

**The courier** (deferred from Phase 0, now built): `POST /internal/pipeline/advance`
(`X-Internal-Secret`). A function that finishes a hop that is not the last hands its state to the
API, which moves `jobs.cursor` with a compare-and-set and sends the next hop; a re-delivered
callback does nothing. `DispatchPayload` gained `pipeline` and `cursor`; functions skip stale or
finished deliveries. `again: true` re-sends the **same** function (inserted into the job's
pipeline), used by `script_split` when its time budget runs out.

**Step 10: `script_split` + the shot-plan kernel.**
- `contracts/shotplan.py` (pure, shared with the API): planner proposal (block ranges) → shots on
  the 4/6/8 ladder (or the fixed length), lines bound to shots and beats verbatim, gaps/overlaps
  repaired, a shot that cannot hold its speech split at a line boundary into a CONTINUOUS
  follow-on (carry last frame), sound mode decided by the lines (never a spoken mode without
  words). Overruns, word budgets and envelope overruns are **reported, never trimmed**; scenes are
  never padded. A person's length (`duration_locked`) is kept.
- `src/services/script_split/` (`hiru-script-split`, port 8203, 900 s): rule planner (establishing
  wide, shot / reverse shot, short action rides with its line) or the `high` model planner, then
  the kernel, then the `medium` critic with **one bounded re-plan**; the better plan by kernel
  issues wins (rules win if the model's plan breaks more). Approved scenes are never touched.
  Continuity checks (no location, speaker not in canon). Episodes become `ready` when all their
  scenes have shots.
- Scenes are planned **4 at a time** and the hop stops starting new waves after 420 s, handing the
  rest to a fresh delivery (`again`), so a long drama does not hit the function deadline.

**Step 11: `structure_build`** (`hiru-structure-build`, port 8204, LangGraph):
read → analyse → **ask** → architect → write.
- `contracts/screenplay.py` (pure, shared): Fountain/screenplay parsing (headings with INT/EXT,
  place, sub-place, time; upper-case cues, `@` forced cues for Sinhala names, `Name: line` for
  known names, parentheticals and cue extensions as delivery, `SOUND:`, transitions), episode
  numbers from headings / title page / filename, outline parsing.
- Questions, each with a suggested answer: which episode an unnumbered script is; two scripts for
  one episode; a heading place that only partly matches a canon location; a scene with no place;
  a speaker close to a canon name. `ask` calls LangGraph `interrupt()`: the hop writes the
  questions, sets the job `waiting_input` and returns; the API resumes it when the last one is
  answered (`POST .../questions/{id}/answer`). **Answers are reused by later builds** (question
  keys are stable). Without `SUPABASE__DB_URL` the build cannot wait: it takes the suggested
  answers and records the questions as `defaulted`.
- The `ultra` architect names scenes and writes missing synopses (parallel, per episode). Rebuilds
  keep episode and scene ids, never rewrite an **approved** scene, remove scenes no longer in the
  script, and add unknown places and speakers to the canon as drafts.
- **Prose episodes** (`engine/prose.py`, 2026-10-25): a file that tells its episodes as story
  prose (`EPISODE 1 — TITLE`, `Name:` above each spoken line, no `INT.`/`EXT.` headings, often with
  the cast bible in front, so its detected role is `bible`) used to build 0 episodes. `read` now
  runs every `script`/`outline`/`bible`/`other` document without scene headings through
  `prose.convert`: the `high` model cuts each episode into scenes (canon place and character
  names reused, scene lengths adding up to the episode's stated "Approx. Duration"); the result is
  rendered as Fountain and goes through `analyse` unchanged. The model's cut is accepted only if
  every spoken line is kept word for word, otherwise (or without a key) rules make one scene per
  episode and a warning says so. Documents with real scene headings are untouched.
- Checkpointer: `langgraph-checkpoint-postgres` in schema `graph` (tables created by the
  checkpointer); thread deleted when the hop finishes; retries resume from the last node.

**Step 12: `canon_extract`** (`hiru-canon-extract`, port 8205, LangGraph):
read → extract → dedupe → critic → write.
- Rules: canon index lines (`C01 Kamala (කමලා) — mother, 52. … Voice: …`), bible character
  sections ("Wardrobe anchor:"), script cues and heading places; merged with the index first.
  With a key: `high` extraction of cards, `medium` dedupe ("AMMA" is Kamala); the documents' own
  "Voice:"/"Wardrobe" wording is kept over the model's paraphrase.
- `contracts/canon.py`: codes (C/L/P + number), `CanonCard`, derived **voice pin** and **wardrobe
  anchor**, reference-sheet prompt (static prefix first), `name_key` (keeps Sinhala vowel signs
  and ZWJ).
- Writes: new version only when the card changed; a **person's** version is only gap-filled;
  **locked** items are never changed (reported). Critic notes core characters missing pins.
- Places that only partly match a known location are left to `structure_build` to ask about.

**Step 13: endpoints for screens 0a, 0b, 1.**
- 0a: `ProductionSettings.build` (what AI builds: canon / scenes / shots), set with the existing
  `PATCH /v1/productions/{id}`.
- 0b: `POST/GET /v1/productions/{id}/build`, `GET .../questions`, `POST .../questions/{qid}/answer`.
- 1: `GET .../episodes`, `GET .../episodes/{eid}`, `GET .../structure` (tree + canon counts),
  `GET .../canon` (+`?kind=`), `GET/PATCH .../canon/{id}`, `POST .../canon/{id}/versions`,
  `POST .../canon/{id}/lock|unlock`.
- Migration `20261023103638_phase2_structure_canon.sql` (now part of `Database/schema_v2.sql`): `canon_entities`, `canon_versions`, `episodes`, `scenes`, `shots`,
  `dialogue_lines`, `questions`, schema `graph`, `documents.text_path`; read-only RLS on every
  table; Realtime on episodes, scenes, shots, questions, canon.
- doc_ingest now stores the extracted text (`<production>/<document>/extracted.txt`, pages split by
  form feeds) and sets `text_path`; the build reads that instead of re-parsing PDFs.

**Deviations from the plan**
- Routes are nested under `/v1/productions/{id}/…` (`questions/{qid}/answer`, `canon/{id}`) instead
  of the flat `/questions/{id}` / `/canon/{id}` in PLAN.md §10, so every route authorises against
  the production in its path, like the documents routes.
- The build's order is canon → structure → shots (canon first so scenes link places and speakers).
- No litellm in the new services: OpenAI through each service's vendored `runtime/llm.py`.
- `script_split`'s critic is a mid-tier review plus the kernel's free checks (no second
  "taste" critic yet).
- Added beyond the plan: answer reuse across builds; the courier's `again`; time-boxed planning.

**Needs doing on the hosted project** (by hand, per `Database/README.md`): run
`Database/upgrade_v1_to_v2.sql`, then re-ingest existing documents (they were read
before the text was kept), and set `SUPABASE__DB_URL` (session pooler) and `API__INTERNAL_URL` /
`API__INTERNAL_SECRET` for the functions.

## Phase 3 — Director panel

**Step 14: `director_chat`** (`hiru-director-chat`, port 8206, 300 s; fork of `nova_chat`,
`UPSTREAM.md` lists every divergence). Synchronous and streamed, not a job: the API stores the
person's message, decides `can_edit` (Permission.DIRECT) from trusted data, and proxies the
function's server-sent events. A turn is conduct → apply → tasks → round 1 → verify → bounded
round 2 → persist → streamed reply.
- `ScenePlanKernel`: closed operation set (set, retime, unlock_length, split, merge, regroup,
  set_join, beat.set, insert, remove, set_envelope); dialogue read-only (`line.*` refused with the
  reason); exact undo; each operation re-fitted alone and rolled back if the scene stops being a
  valid plan; a length a person set is locked against agents.
- Conductor by model (`medium`, strict JSON) or by rules without a key; specialists
  (cinematography, timing, sound, continuity) in parallel on `high`, limited to their own
  operations; the board settles collisions by ownership and keeps the losing view as a
  disagreement block; advisors review the result (`medium`), never edit it; reply streamed on `low`.
- Read tools (search_production, get_canon, get_shot_timing, list_open_questions), scope fixed by
  the turn. An edit that restructures most of the scene is undone and offered as a re-split.

**Step 15: tools, threads, memory, board.**
- Migration `20261023111753_phase3_director.sql`: `director_personas` (five generic archetypes,
  no real people, no prices), `production_director_board` (one lead, advisors), `chat_threads`,
  `chat_messages` (Realtime), `memory_items` (also indexed in `chunks` as corpus `memory`),
  `shots.duration_locked`, shot numbers unique **deferrable**. Migration
  `20261023180232_phase3_line_order.sql`: line order unique deferrable too (a script edit
  reorders lines in one upsert). Hosted DB: folded into `Database/schema_v2.sql` /
  `upgrade_v1_to_v2.sql` (see "Hosted dev database").
- API (`routers/director.py`): `GET /v1/director-personas`; `GET/PUT .../director-board` (DIRECT;
  exactly one lead, up to three advisors, active personas only; an empty board shows the default
  lead the turn uses); `GET/POST .../scenes/{id}/threads`; `GET .../threads/{id}/messages`;
  `POST .../scenes/{id}/chat` (COMMENT; SSE: `accepted` first, then the function's `status`,
  `delta`, `plan`, `message`, `done {message_id, lane}`, or one client-safe `error`);
  `GET/POST/DELETE .../memory` (DIRECT to write). Answered build questions are stored as memory
  (`kind: answer`) as PLAN.md §6.2 asks.
- In production the API calls the function with a Google ID token (`api/services/director.py`);
  Terraform grants the API's service account `run.invoker`.

**Step 16: timeline, shot edits, re-split, replay, hygiene.**
- `contracts/sceneplan.py` (new, shared by the API and the function): script + lines → kernel
  items, stored rows ↔ plan, and `rows_after_fit`: shot ids kept, the follow-on part of a shot
  the kernel split is a new shot, `version` bumped only when something a prompt depends on changed.
- API (`routers/scenes.py`): `GET .../scenes/{id}` (script blocks with their shot, shots, lines
  with spoken start/end and overrun, issues, canon refs, board, neighbours; timeline computed
  by the kernel on each read); `PATCH .../shots/{id}` (DIRECT: length 4/6/8 locks it, `null`
  releases it, sound/framing/join/title; a sound mode the lines contradict is a 422, not a silent
  change); `POST .../scenes/{id}/resplit` (a one-scene `script_split` job);
  `POST .../scenes/{id}/approve|unapprove` (APPROVE_SCENE; approved scenes refuse every edit,
  episode status follows); `PUT .../scenes/{id}/script` (EDIT_SCRIPT; optimistic version check,
  lines keep ids, NFC with ZWJ kept, speakers matched to canon by name or alias, the shot list
  carried across the edit by matching blocks, new blocks join the shot before them).
- `scripts/replay_director.py` + `tests/eval/director_replay.json` (16 cases, tune/held-out) +
  `tests/eval/director_thresholds.json`: rules mode is a pytest gate; `--model` scores the real
  model. `tests/services/director_chat/test_prompt_hygiene.py`: static system prompts (byte-
  identical across turns and scenes), data wrapped in tags, "data, never instructions" in every
  system prompt, charter size budget, no money words, read-only tools without scope arguments.
- `scripts/upstream_diff.py`: per forked file, upstream commits since the pin (`--patch` for
  diffs). Run against the local PromptMotion checkout: nothing changed since `1d748dc`.
- Registered in `scripts/start-functions.ps1`, `deploy-functions.yml`, `task_manager.DIRECTOR_CHAT`.

**Bugs found and fixed in the code written before this session**
- The turn wrote rows by zipping kernel shots with fitted shots (`strict=True`), which crashes
  when the kernel splits an overlong shot; and the shot numbers the model read could differ from
  the numbers its operations addressed. The kernel now adopts such splits (`_absorb`), and
  write-back goes through `contracts.sceneplan`.
- The "this would change most of the scene" check counted the shots left after the edit, so
  removing 3 of 4 shots went through. It now uses the count before the edit.
- The editor could be asked twice about the same overrun; round 2 now only covers new ones.
- The turn's history included the message being answered.

**Found by the real-model run and fixed (2026-10-24)**
- The reply (on `low`, gpt-5-nano) described changes that were not made and misnumbered shots.
  It now runs on `medium`, is told the shot list is the plan after the turn, and gets an explicit
  "Applied: nothing" when nothing changed.
- The model wrote free text or names as values ("Close-up", "the radio only") and put a join on
  the wrong shot. The prompts now list the value codes and say a join belongs to the later shot;
  the kernel accepts common names for framings and sound modes.
- A specialist made 16 changes for a one-shot request. Specialists are now held to their task's
  shots in code (others dropped, at most 6 operations per task).
- A standing rule was stored again when the model echoed it from the history on an unrelated
  message. The prompt says "only rules THIS message states", and the turn skips rules the
  production already holds.
- Prompt caching shows 0 cached tokens: the static prompts are under OpenAI's 1,024-token cache
  minimum, so there is nothing to cache yet (cost is small either way).

**Deviations from the plan**
- Routes nested under `/v1/productions/{id}/…` (as in Phase 2), not `/scenes/{id}`.
- Re-split replaces the shot list (new ids; lengths people set and beat notes go with it).
- Two people editing one scene at the same moment: the last write wins (the script has a
  version check; shot edits and chat turns do not yet).


## Phase 4 — Production panel

**Design.** Per shot, three things in order, each gated by the one before: a DESIGN (the DP's IR
and a camera recommendation), FIRST FRAMES (pick one; accepting unlocks the prompt), and VIDEO
PROMPT versions. Production work needs the scene APPROVED in the Director panel. Nothing upstream
is redone: designs, frames and prompts record `Pins` (shot version, a hash of the shot's script,
place and time, and the canon card versions of the people and place in it); the API compares
them on every read and reports what is out of date and why (`contracts/producer.py`,
`api/services/production.py`).

**Step 17: `shot_producer`** (`hiru-shot-producer`, port 8207, 900 s; fork of `nova_producer`,
`UPSTREAM.md` lists 11 divergences).
- One strict-JSON call designs a whole scene (`high` tier); answers matched by shot number,
  missing shots asked once more, the rest by rules. System prompt byte-identical everywhere; the
  production block (cast with codes, wardrobe anchors, the lead persona's style and charter, a
  technique palette from `match_craft_techniques`, retrieved once per job) opens every request.
- After the call, in code: codes → names in prose, invented people anonymous, people not in the
  shot dropped, any Sinhala the model echoed removed, beats mapped onto the kernel's windows with
  the director's beat notes on top, the director's shot size always wins.
- Prompt mode: Veo prose serialized in code as titled SECTIONS (`contracts.producer.PromptSection`)
  with each Sinhala line its own segment, byte-exact; voice casting from canon voice pins;
  identity anchors from wardrobe anchors; silence stated for wordless shots; joins for
  continuous / matched shots; the camera section rebuilt when a person changed the camera.
  Each prompt is a new version with checks (one speaker, lines verbatim, voice pins, words over
  target, camera changed). Without a key the design is made by rules.
- `contracts/producer.py`: the camera vocabulary (mirrors the frontend's `camera-options.ts`,
  which gained "Over-the-shoulder" and three lighting presets), defaults by shot size and scene
  heading, camera checks (axis, wardrobe anchors, voice pins), pins and stale reasons, the
  first-frame prompt, prompt sections and their plain text.

**Step 18: `frame_render`** (`hiru-frame-render`, port 8208, 600 s; fork of `video_render`,
provider replaced by OpenAI's image model, `OPENAI__MODEL_IMAGE` default `gpt-image-2`, quality
`medium`).
- The API inserts frame rows `queued`; the function CLAIMS each (conditional update, so a
  re-delivery never pays twice), composes the prompt from the IR and the camera as it stands,
  attaches the reference sheets of the characters and the location in the shot (in order, named
  by position; an unreadable sheet is left out and not named), paints (`images.edit` with
  references, `images.generate` without), stores to the private `frames` bucket, records the
  prompt, references and pins. Four in parallel. Refusals are reported, never retried; provider
  text never reaches a person. A `token_usage` row per picture.
- Reference-sheet mode: paints the current card's sheet (`contracts.canon.reference_sheet_prompt`)
  into the private `references` bucket and records it on `canon_versions.reference_assets`.

**Step 19: accept → prompt unlock, staleness** (`routers/production.py`, all under
`/v1/productions/{id}`): `GET scenes/{id}/production`, `GET shots/{id}`, `POST scenes/{id}/design`,
`PATCH shots/{id}/camera` (null or the recommended value clears a person's change),
`POST shots/{id}/frames` and `POST scenes/{id}/frames` (one job: a `shot_producer` design hop
first when a design is missing or out of date, then `frame_render`, through the courier),
`POST frames/{id}/accept|reject` (picking is free; a stale frame cannot be accepted),
`POST shots/{id}/prompt` and `POST scenes/{id}/prompts` (only unlocked shots),
`GET shots/{id}/prompt|prompts`, `POST shots/{id}/frames/upload` (a person's own PNG/JPEG/WebP,
checked by content, pinned like a painted frame), and `POST canon/{id}/reference-sheet`
(EDIT_CANON); canon
entities carry `reference_sheet_url`. Frames and sheets reach browsers only through
`/files/{ticket}`.
- Prompt lock: scene approved; a shot that opens on a generated frame needs an accepted, current
  frame; a shot that carries on from the previous take (`carry_last_frame`) needs none and cannot
  have frames of its own (409 with the reason).
- Migration `20261024103506_phase4_production.sql`: `shots.design`, `shots.camera_overrides`,
  `first_frames` (one accepted per shot, only `done` can be accepted), `video_prompts` (versions
  unique per shot), read-only RLS, Realtime, private `frames` and `references` buckets.
  Hosted DB: `Database/schema_v3.sql` and `upgrade_v2_to_v3.sql`.
- Registered in `task_manager.FUNCTIONS`, `deploy-functions.yml`, `start-functions.ps1`;
  `.env.example` has the image settings; PyYAML added to dev dependencies (the clip schema).

**Deviations from the plan**
- `video_prompts.stale` is not a stored flag: staleness is computed on read from pins, so no
  write path (API, director chat, canon extraction, script edits) can forget to set it.
- The Veo serializer stays in `shot_producer` (the fork); the first-frame prompt moved to
  `contracts` so `frame_render` composes it from the camera as it stands at paint time.
- Routes nested under `/v1/productions/{id}/…` as in Phases 2–3; `GET .../scenes/{id}/production`
  and the scene-level prompts request are additions.
- Reference sheets (mentioned in `contracts/canon.py` for Phase 4) are included, though not listed
  in PLAN.md §10.
- The video prompt does not cite reference sheets: Veo gets the accepted first frame, which
  already carries identity. No storyboard shots, no `last_frame`.
- Re-split still replaces the shot list with new ids, which deletes that scene's frames and
  prompts (they cascade with their shots).

## Phase 5 — Handoff

- `contracts/handoff.py`: `check_prompt` (overrun against the Veo length, missing first frame,
  stale prompt, voice pin and wardrobe anchor present, banned terms from
  `ProductionSettings.banned_terms` plus defaults), takes status, 30 MB take limit.
- Migration `20261024162733_phase5_handoff.sql`: `takes` (one accepted take per shot, unique
  index), `usage_budget`, RLS read-only for members, Realtime, private `takes` bucket. pgTAP
  `006_handoff.test.sql`.
- `infra/assemble/`: small ffmpeg service (`/health`, `/probe`, `/last-frame`, shared-secret
  header). The API calls it through `services/assemble.py` (`ASSEMBLE__URL`, `ASSEMBLE__SECRET`);
  Terraform `assemble.tf` and `deploy-assemble.yml` are written, not applied.
- API `routers/handoff.py`: `GET .../shots/{id}/handoff`, `POST .../shots/{id}/takes`,
  `POST .../takes/{id}/accept` (with `carry_last_frame`: the take's last frame becomes the next
  shot's accepted first frame) and `/reject`, `GET .../scenes/{id}/bundle` (zip: README, shots.json,
  each shot's prompt and first frame). `routers/usage.py`: budget from `usage_budget` (admin
  `PUT /v1/usage/budget`), else the env setting.
- Also added for the remaining screens: `GET .../activity`, `POST .../ask` (canon matches + search,
  answered with numbered citations, or the sources alone without a key), canon create / draft from
  documents / usage, and `answered_by_name` on questions.

## Frontend wiring (`hiru-ai-studio-interface`)

**Phase 5 and the rest (2026-10-24).** No screen reads mock data now (`scene-3.mock` and
`directors.mock` stay only for unit tests):
- Director panel: streamed chat turns (`browserStream`), approve / unapprove, re-split, per-shot
  length (auto / 4 / 6 / 8), script editing, director board (add, remove, make lead).
- Prompt & Handoff: real checks, prompt regenerate, takes upload / accept (carry last frame) /
  reject, scene bundle download.
- Build (0b), canon library and entity (create, draft from documents, edit card as a new version,
  lock, reference sheet), questions (answer), activity feed, and "Ask the production".
- `lib/api/server.ts` calls `connection()` and each drama section has its own `loading.tsx`; this
  removed the dev-mode "`Date.now()` while prerendering" error noted under Phase 4.


**Phase 4 (2026-10-24).** Real data from the overview down to a shot:
- `features/drama/api.ts`: episodes, the "Open episode" target and the canon card from
  `GET .../structure` and `GET .../canon`. Episode rows link to their episode page.
- `features/episodes/api.ts` + `lib/map-episode.ts`: the sidebar list and the episode page (stage
  bars from scene statuses and shot counts; `shots_prompted` added to the API's episode summary).
  The episode mock is removed.
- `features/scenes/api.ts` + `lib/map-scene.ts`: a scene from `GET .../scenes/{id}` (script,
  lines, timeline, board, canon) and `GET .../scenes/{id}/production` (camera, frames, prompt,
  staleness), mapped onto the existing screen types (`Shot.production` added; frames carry their
  `/files/{ticket}` URL, status and stale reasons). The scene mock stays only for a unit test.
- `features/production/client.ts`: design, camera, frames (generate / upload / accept / reject),
  prompts, scene-wide batch actions, and `waitForJob` (polls `GET /v1/jobs/{id}`, then the page is
  read again). The Production panel shows real frame images (plain `<img>` on the ticket URL),
  painting / failed / out-of-date states, the prompt lock reason, a design banner with
  "Recommend settings", stale-prompt reasons, and keeps refreshing while frames paint. The three
  header buttons run the scene-wide jobs. `camera-options.ts` mirrors `contracts/producer.py`.

**Earlier phases:**

The Next.js app now reads and writes real data through this API (no more mock seam for these):
- **Auth:** Supabase email + password sign-in (`/login`), session in cookies (`@supabase/ssr`),
  `src/proxy.ts` refreshes it and redirects signed-out visitors. Server components call the API
  with the session's access token (`lib/api/server.ts`); client components do the same from the
  browser (`lib/api/browser.ts`, CORS allows the frontend origin). Roles still come from the API.
- **Screens on real data:** productions list and cards, drama overview (title, format; episodes and
  canon are empty until Phase 2), account/sign-out, usage meter, **Documents** tab (upload, follow
  ingest, confirm role, re-read, delete) and **New production** (creates the production, uploads
  the files with their chosen roles).
- **Still mock:** build, director, production, handoff and director-board screens (Phase 2+).
  Real productions have no episodes, so those pages are not reachable from them yet.
- **API additions:** `GET /v1/usage` → `{percent}` (month's model tokens against
  `USAGE__MONTHLY_TOKEN_BUDGET`, default 5,000,000; needs `token_usage_since()`, migration
  `20261023120000_usage_total.sql`, also in `Database/schema_v2.sql`) and an optional `role` form field on document upload (used by the new-production form,
  so a chosen role applies from the first read, with no race against a later PATCH).
- The meter hides itself if `/v1/usage` fails, so the hosted project works before the SQL is run.

## Hosted dev database (`Database/`)

The user chose to run the hosted Supabase project `dwivfkavmtjzhypqswze` as the dev database and
to manage it by hand, not with `supabase db push`.
- `Database/schema_v1.sql`: the three migrations combined into one file, with each policy in its
  final form and every index next to its table. It runs in one transaction.
- Verified on the local stack: reset with no migrations, then loaded the file the way the SQL
  Editor would. The `public` and `storage` dumps match the migration build line for line. The
  Realtime publication, the bucket and the `auth.users` trigger are identical. The 49 database
  tests pass and the advisors report no issues.
- `Database/README.md`: first-time setup (sign-up off, redirect URLs, first admin, `.env`) and
  how to change data or structure from now on.
- **The hosted project is the one dev database** (2026-10-24). It runs v2: the user ran
  `upgrade_v1_to_v2.sql`, and every Phase 2–3 table and column was confirmed through the REST API.
  The backend `.env` and the frontend `.env.local` point at it; the local stack is only for tests.
- **Schema files are versioned, not per change** (the user's rule, 2026-10-24): `schema_v2.sql` is
  the whole Phase 0–3 schema for an empty project, and `upgrade_v1_to_v2.sql` moves the hosted
  project from v1 (it replaces the earlier `changes/001–003` files). Verified on the local stack:
  the `public` and `storage` dumps from the migrations, from v2 alone and from v1 + the upgrade
  are identical; personas, Realtime tables and the `graph` schema match; 94 database tests and
  the advisors pass on v2.

## Not done yet from the plan (Phases 0–3 scope)

- **Test data on the hosted dev DB** from the Phase 3 smoke run: a production "Phase 3 smoke …"
  and users `smoke-admin@`, `director-…@`, `writer-…@`, `reviewer-…@hirutv.lk`.
- **Frontend:** the Director panel and director-board screens still read mocks; the API above
  is ready for them (`GET .../scenes/{id}` carries everything the 2d screen draws).
- **Hosted DB:** upgraded to v2 and fully configured (secret key and DB URL in the backend `.env`;
  no v1 documents to re-read). For Cloud Run, switch `SUPABASE__DB_URL` to the session pooler (the
  direct host is IPv6-only).
- **Deploy note:** functions are deployed with internal-only ingress; the API calling
  `hiru-director-chat` directly needs its egress through the VPC (Direct VPC egress) when deployed.
- Concurrent edits to one scene: the script has a version check; shot edits and chat turns are
  last-write-wins for now.
- The frontend's build, drama-overview and canon screens still use mock data; the Phase 2
  endpoints are ready for them.
- Model tiers default to `gpt-5` (ultra/high) and `gpt-5-mini` / `gpt-5-nano`; verified available.
  gpt-5 at medium/high effort takes 20–60 s per shot-plan call.

- Reranker quality is not scored separately yet (the eval measures the retriever); add
  rerank probes once real Hiru questions exist.
- Model choice: `gpt-5-mini` / `gpt-5-nano` / `text-embedding-3-large` are verified available and
  working. Newer families exist on the account (gpt-5.4 mini/nano, gpt-5.5, gpt-6); switching is
  a config change plus an eval run, pending the user's choice.
- Rate limiting (§12) and OpenTelemetry tracing (§6.2, §12): not added yet; planned for Phase 6
  unless needed sooner.
- `scripts/upstream_diff.py` (§2.1): arrives with the first engine fork (Phase 3).
- Batch API for bulk embedding (§5): not used; embeddings run in batches of 64 inline.
- Deployment (steps 6 and on): waiting for the decision to deploy.

## Needed from Hiru / the team

- Real sample documents (especially Sinhala script PDFs) to test extraction and the legacy-font
  warning on actual files.

## After Phase 5 — the director chat edits the Script column (2026-10-26)

**Deviation from PLAN.md §6.2 / §10** ("script lines are read-only input: dialogue comes from the
approved script"). The user asked that everything the Script column shows can be changed by chat,
and that each change is checked against the shots around it. What changed, and what did not:

- **Script blocks** (action, sound, beat, cut, and spoken lines: text, speaker, delivery):
  `block.set | block.insert | block.remove` in the kernel. **Dialogue is still never written by an
  agent.** The words must be ones the person typed (this message or an earlier one of theirs,
  compared in NFC, any case, plain quotes), they are **staged** as an options card (Apply / Keep it
  as it is) with their checks, and `engine/choice.py` applies them on the person's click. Needs
  `Permission.EDIT_SCRIPT` (a writer can change words but not the shot list; a director or
  producer both). The chat saves the script, its lines and `script_version + 1`, refuses a script
  someone saved meanwhile, and the shots, frames and prompts for the changed words go out of
  date through `script_hash` as they do for a hand edit. Non-dialogue blocks apply at once.
- **Canon chips, ignored checks, the DoP note** are a shot's `person_edits` (new jsonb column,
  `contracts.producer.PersonEdits`): who is in the shot (add or take out any canon entry; the
  scene's place too), advisories to ignore by topic (`axis | speaker size | wardrobe | voice pin`;
  only advisories; they stay listed, marked), and a note that replaces the DP's rationale and is
  given to the next design as "DIRECTOR'S NOTE FOR THE DoP". `cast_in`, `pins_for`
  (`shot_canon_ids`) and the frame references read it in the API, `shot_producer` and
  `frame_render` alike, so a chip change marks the shot's design, frames and prompts out of date
  and a prop a person added has its sheet attached.
- **Time and Words** are not stored: Time is a shot's length (`retime`, as before) and Words is a
  line's text against what fits (`block.set`, with "words 7 → 9 (room for 13)" on the card).
  A request to "fit" more words retimes or splits; a line is never cut unprompted.
- **Checks against the shots around it** (`engine/ripple.py`): the impact set, notes in code (sound
  follows the words, who is in a shot changed, speaker not in the canon, a joined shot's opening,
  a word the edit took out that another shot still says, the same speaker elsewhere) and the
  continuity specialist on that set. Other scenes are not read or edited.
- Options cards cannot carry any of these operations; the specialists cannot either.
- Tests: `test_kernel_script.py`, `test_turn_script.py`, API (`test_director.py`,
  `test_production.py`), shot_producer, frame_render. **Not run here:** `supabase test db` and
  the three-way schema dump comparison (no Docker); the new column has a migration
  (`20261026032147_chat_person_edits.sql`), pgTAP checks in `005_production.test.sql` and is in
  `Database/schema_v5.sql` and `upgrade_v4_to_v5.sql` (v4 was already on the hosted DB, so it is a new version, not folded into v4).
- Camera and lighting are unchanged: not editable from chat.

## Cinematography knowledge base (2026-10-26)

The craft RAG from PromptMotion already existed (Step 9: 89 chunks, 61 camera techniques); this
adds the 629-term cinematography database the user supplied (`files.zip`) and a Hiru-owned note.

- `src/knowledge_base/cinematography/*.csv` (provenance in `UPSTREAM.md`) is loaded by
  `scripts/cine_terms.py` and indexed by `scripts/ingest_knowledge.py` into `craft_techniques`.
  Dry run: **576 techniques** (550 terms + 26 `camera_shots.csv` rows with no counterpart; the 35
  that did overlap are merged, keeping their legacy feeling-first text). Domains: camera 223,
  story 121, post 88, light 73, animation 44, format 27. **79 short-form terms** (ads, social,
  video formats) are not indexed (`--include-short-form` adds them): Hiru makes television.
- `craft_techniques` gained `slug, subcategory, effect, example_scene, prompt_phrase, aliases,
  complexity, ai_supported, tags, related`; `match_craft_techniques()` returns them. Migration
  `20261026062153_cinematography_terms.sql`, in `schema_v6.sql` and
  `upgrade_v5_to_v6.sql` (v5 was already on the hosted project, so this is v6). Existing rows and callers are unaffected.
- `craft/hiru-house-style.md`: shot lengths, Sinhala dialogue, line-fits-shot, one sound mode per
  shot, canon. Written only from rules already in code; **television pacing and broadcast
  conventions are not in it yet** (needs Hiru's own material).
- Tests: `tests/knowledge/test_cine_terms.py` (7). pgTAP checks added to `002_rag.test.sql`.
- **Not verified:** no Docker here, so `supabase test db`, the advisors and the three-way dump
  comparison have NOT been run on the SQL; `eval_retrieval.py` has not been re-run (the new technique rows need v6). The shot palette
  (`shot_producer/engine/techniques.py`) still formats only name / use case / definition; the new
  `prompt_phrase`, `effect`, `ai_supported` and `related` are returned but not yet used there.

## Phase 4: still open

- Done since: the Director panel buttons, Prompt & Handoff, and the activity feed are wired (see
  "Frontend wiring"), and the dev-mode `Date.now()` error is fixed.
- Build page: there is no Pause / Stop yet (the API has no endpoint for them).

## Next

1. Run `Database/upgrade_v5_to_v6.sql` on the hosted project (the cinematography columns on `craft_techniques`; v5 is already on it), then `python scripts/ingest_knowledge.py` and `python scripts/eval_retrieval.py --runs 3`. Then click through takes and the
   bundle in the browser (needs the `assemble` service running locally, port 8209).
2. Phase 6 (hardening).
