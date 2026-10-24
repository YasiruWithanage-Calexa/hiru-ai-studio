# Hiru AI Studio — Backend Plan

> Python API backend for Hiru AI Studio. Draws on PromptMotion's structure and proven engines
> (fork `1d748dc`, 2026-10-19), uses **OpenAI** as the only LLM provider and **Supabase** for auth,
> database, storage, realtime and vector search, with multi-user and role management.
>
> Inputs: `hiru-ai-studio-knowledge-base/HIRU_AI_STUDIO_CONTEXT_V2.md`, the Figma prototype
> (`pmfpQXH81FfdmGkmMdjicD`, main flow 00 → 0a → 0b → 1 → 2d → 3d → 4), and the PromptMotion repo.
> Status: **plan, for review.** Implementation goes phase by phase (§13), one PR per step.

---

## 1. Goals and non-goals

**Goals**
- One backend for the full Hiru flow: productions → document intake → live structure build →
  canon → Director panel → Production panel → prompt & handoff.
- Content model `Drama → Episode → Scene → Shot`. It must work for every Hiru format, not only
  dramas, and must not be tuned to *Wessanthara Jāthakaya*.
- Veo 3.1 rules (§5 of the context doc) enforced **in code**, not only in prompts.
- Every agentic capability PromptMotion has proven (§6), plus what a multi-user studio needs:
  server-side memory, shared state, roles and an audit trail.
- A RAG system good enough to answer from a production's own bible, scripts and canon, with
  measured retrieval quality.
- Multi-user, **Hiru only** (single tenant): workspace admins, members, roles per production,
  enforced in the API **and** in Postgres RLS.

**Non-goals (for now)**
- In-app video generation. Handoff is "Copy for Flow" plus takes upload (see open question Q1).
- Billing or credits. The UI shows only **monthly usage %** (§10). No prices in any API response
  meant for the UI.
- Localising the UI. Only spoken lines are in Sinhala.

---

## 2. What we take from PromptMotion, and how

PromptMotion has three ways of sharing code. Hiru uses the third for everything:

| PromptMotion pattern | Use in Hiru |
|---|---|
| `green_engine` + `pm_contract` imported in-process by functions | **No.** It is a large shared surface that we would have to carry whole. |
| `api/` importing engine code directly | **No.** |
| **Self-contained services** under `src/services/<name>/` that **vendor** their own runtime + engine and import **only** `libs/contracts` (guarded by `test_service_isolation.py`, bundled by `verify_vendored.py`) | **Yes, for every function.** It is what makes a fork possible: a service is a folder we can copy, pin and diff. |

### 2.1 Forked engines (proven, copied, then adapted)

Each fork keeps an `UPSTREAM.md` naming the source path and commit, plus a list of every
intentional divergence. `scripts/upstream_diff.py` shows what changed upstream since the pin, so
fixes can be pulled across by hand. This is how we keep "shared core with PromptMotion" without
sharing a deploy or a database.

| Hiru service | Forked from | What changes |
|---|---|---|
| `director_chat` | `services/nova_chat` (StudioTurnEngine: conductor → ops → kernels → dependency graph → parallel agents → board → verifiers → reply) | Brief → Hiru **scene/shot plan** as the kernel's document. Sessions persisted server-side (Vega's are browser-only). Director board personas (Lead / Advisor). Script lines are read-only input: dialogue comes from the approved script. OpenAI tiers. |
| `shot_producer` | `services/nova_producer` (camera-aware fork of vega_producer: `screenwriter`, `shots` scene-level render, `continuity` ledger, `doctrine`, `serialize` (IR → Veo prose), `schemas/clip_schema_veo_3_1.yaml`) | Input is a Hiru scene with its shot list already set by the director (no re-splitting). Output is per shot: camera recommendation, frame strategy, Veo prompt. Keeps the 11-section prose order, beat binding, voice pins, `camera_link`, repair-only-downgrades. |
| `frame_render` | `services/video_render` (take / transport / storage / events plumbing) | **Provider replaced**: `engine/image.py` is Gemini "Nano Banana" upstream. Hiru uses the OpenAI image model with reference sheets. Video providers (`veo`, `omni`, `seedance`, `minimax`) are **not** copied. |
| `infra/assemble` (Cloud Run) | `infra/assemble` (ffmpeg `/last-frame`, `/join`) | Only `/last-frame` (carry-previous-frame strategy) and probe of uploaded takes. `/join` is kept for later. |
| Shared rules in `libs/contracts` | `pm_contract/timing.py`, `pm_contract/dialogue_binding.py`, `libs/contracts/vega_production.py` (`snap_duration`, word targets, audio modes) | Copied into `contracts/veo.py` and `contracts/timing.py`. Fix the `snap_duration` "billed per shot" comment while copying. The 10 s rung stays **off** until Q4 is answered. |
| RAG retrieval + ingest | `vega_chat/engine/retrieval.py`, `scripts/vega_ingest_knowledge.py`, `scripts/ingest_craft_techniques.py`, `scripts/vega_eval_retrieval.py` | Extended into a hybrid retriever (§7). Craft corpus copied: `knowledge_base/vega/*.md`, `knowledge_base/rules/sceen_rules/*`, `docs/knowledge-base/camera_shots.csv`, `docs/engines/veo-3-1-prompting-guide.md`. |
| API patterns | `api/dependencies.py` (Supabase JWKS verification), `api/workers/task_manager.py` (Cloud Tasks + OIDC, local ports, idempotent courier), `api/services/media_links.py` + `routers/files.py` (encrypted file tickets), token tracker | Rewritten for Hiru's roles. The logic is kept; the tier and credit code is dropped. |
| CI | `.github/workflows/deploy-functions.yml` (WIF auth, deploy only changed functions) | Same shape, Hiru GCP project. |

### 2.2 New Hiru engines (custom functions)

| Service | Purpose | Engine style |
|---|---|---|
| `doc_ingest` | Detect each uploaded file's role (bible, script, canon index, image pack, other), extract text (text-layer PDF, Markdown, plain text / Fountain; Sinhala-safe; **no OCR**: scanned PDFs are rejected with a clear message), chunk, embed, index | Deterministic extraction + one cheap classification call per file |
| `structure_build` | Build episodes → scenes → shots from the documents. Streams progress per agent and **asks questions** when the material is ambiguous ("0b · Live build") | **LangGraph** with a Postgres checkpointer, so a question can pause the graph until a person answers, even hours later |
| `canon_extract` | Characters, locations and props with versioned cards, wardrobe anchors and **voice pins**. Reference-sheet prompts | LangGraph: extract → dedupe/merge → critic → write |
| `script_split` | Scene script → shot list with lengths on the 4/6/8 ladder, dialogue bound to shots and beats, sound mode per shot, envelope fit | Planner + deterministic timing kernel (`contracts.timing`) + critic. Called by `structure_build` and by the director chat ("Re-split") |
| `prompt_check` | Free, model-free checks for the Prompt & handoff screen: word overruns, missing silence line, banned brands or public figures, voice-pin drift, aspect and duration | Pure Python, runs in the API process (no function needed) |

**Rule from PromptMotion we keep:** a new product is a new *intake*, not a new engine. If a
need can be met by feeding Hiru data into a forked engine, we do that before writing a new one.

---

## 3. System architecture

```
 Next.js frontend (hiru-ai-studio-interface)
   │  supabase-js: sign-in, session, Realtime subscriptions (job progress, presence)
   │  HTTPS + Bearer (Supabase JWT)
   ▼
 hiru-api  ── FastAPI on Cloud Run (min 1 instance) ─────────────────────────────
   │  authz (org + production roles) · REST · SSE proxy for chat · file tickets
   │  dispatch: Cloud Tasks (OIDC) → functions   |  LOCAL_FUNCTIONS=true → localhost
   ▼
 Cloud Run functions (gen2, internal ingress, Python 3.12, one service account each)
   doc_ingest · structure_build · canon_extract · script_split
   director_chat (sync, streaming) · shot_producer · frame_render
 Cloud Run service: assemble (ffmpeg)
   │
   ▼
 Supabase (separate project for Hiru)
   Auth · Postgres + RLS · pgvector · Storage (private buckets) · Realtime
 OpenAI API (LLMs, embeddings, images)  ·  Secret Manager  ·  Cloud Logging/Trace
```

**Differences from PromptMotion, and why**
- **API on Cloud Run, not a VM.** Scales to the team's use, no machines to patch, same container
  locally and in production.
- **No Redis.** Job progress is written to a `job_events` table and the browser reads it through
  **Supabase Realtime**, which applies RLS, so a user only sees events for productions they belong
  to. Chat tokens stream over SSE (API proxies the function's stream, as PromptMotion does).
- **Server-side sessions.** Director chat threads, decisions and approvals are stored, because
  several people work on one production.
- **Migrations through the Supabase CLI** (`supabase/migrations/*.sql`, applied in CI), not
  hand-run `schema-vN.sql`.

---

## 4. Repository layout

```
hiru-ai-studio/
├── PLAN.md                     # this file
├── CLAUDE.md                   # working rules for agents (written in Phase 0)
├── pyproject.toml              # api + contracts package; ruff, mypy, pytest config (pip + venv)
├── .env.example
├── src/
│   ├── api/                    # FastAPI app → Cloud Run service "hiru-api"
│   │   ├── main.py             # create_app(), lifespan (Supabase client, settings)
│   │   ├── config.py           # pydantic-settings, get_settings() (lru_cache), Secret Manager in prod
│   │   ├── deps/               # auth.py (JWKS verify), authz.py (require_admin / require_permission), db.py
│   │   ├── routers/            # me, members, productions, documents, build, canon, episodes,
│   │   │                       #   scenes, shots, director, frames, prompts, takes, jobs, files,
│   │   │                       #   usage, internal (function callbacks)
│   │   ├── services/           # authz policies, media_links (tickets), usage, audit, prompt_check
│   │   ├── repositories/       # all DB access; routers never write SQL
│   │   └── workers/            # task_manager.py (Cloud Tasks / local), courier for multi-hop jobs
│   ├── libs/
│   │   └── contracts/          # STANDALONE (pydantic only): production.py (Drama/Episode/Scene/Shot),
│   │                           #   veo.py, timing.py, canon.py, jobs.py, rag.py, roles.py, llm.py (tier names)
│   ├── services/               # one folder per Cloud Run function; each vendors runtime/, imports only contracts
│   │   ├── doc_ingest/         # NEW
│   │   ├── structure_build/    # NEW (LangGraph)
│   │   ├── canon_extract/      # NEW (LangGraph)
│   │   ├── script_split/       # NEW
│   │   ├── director_chat/      # FORK of nova_chat        + UPSTREAM.md
│   │   ├── shot_producer/      # FORK of nova_producer    + UPSTREAM.md
│   │   └── frame_render/       # FORK of video_render     + UPSTREAM.md (OpenAI image provider)
│   │       └── (each) main.py, requirements.txt, <pkg>/{app,engine,runtime}/
│   └── knowledge_base/         # craft corpus (copied from PromptMotion) + Hiru house style
├── infra/
│   ├── assemble/               # FORK: ffmpeg Cloud Run service
│   └── terraform/              # GCP project, Cloud Run, Tasks queues, IAM, Secret Manager, WIF
├── supabase/
│   ├── config.toml
│   ├── migrations/             # timestamped SQL, RLS policies, RPCs (match_chunks, has_production_role)
│   └── seed.sql                # dev org, users per role, a sample production
├── scripts/                    # ingest_knowledge, eval_retrieval, eval_prompts, replay_director,
│                               #   verify_vendored, upstream_diff, start-functions.ps1
├── tests/                      # unit, contract, isolation, RLS (pgTAP), prompt hygiene, eval fixtures
└── .github/workflows/          # ci.yml, deploy-api.yml, deploy-functions.yml, migrate.yml
```

**Isolation rules (tested in CI)**
- `services/*` import only their own package and `contracts`. Never `api` or another service.
- `contracts` imports only pydantic and the standard library.
- Engines never touch Supabase directly; they go through a repository in their own `runtime/`.
- Every DB write that can be retried is an idempotent upsert (Cloud Tasks re-delivers).

---

## 5. LLM layer (OpenAI only)

**Provider client.** Keep **litellm** inside the forked services so their code stays close to
upstream and diffs stay small (model strings become `openai/<model>`). New services use the same
vendored `runtime/llm.py` wrapper, so there is one way to call a model: tiers, JSON/structured
output, retries, token ledger, prompt-cache-friendly ordering.

**Tiers** (names from PromptMotion; the model behind each is configuration, not code):

| Tier | Used for | Default (confirm current OpenAI line-up in Phase 0) |
|---|---|---|
| `ultra` | Treatment / structure build, director reshape, hard critic | flagship reasoning model, effort `high` |
| `high` | Specialist agents, shot producer scene hop, canon cards | flagship, effort `medium` |
| `medium` | Conductor / classifier, file-role detection, reranking | mini model |
| `low` | Reply wording, summaries, chunk context headers | nano/mini model |
| `embed` | RAG | `text-embedding-3-large` at 1536 dims (fits pgvector HNSW) |
| `image` | First frames, reference sheets | OpenAI image model, high quality |

**Features we use on purpose**
- **Structured outputs** (JSON schema) on every node that returns data. Never on a node with
  tools (PromptMotion rule).
- **Function calling** for the director chat's read tools (§6.2).
- **Prompt caching**: static prefix first, byte-identical across shots (schemas, rules, canon
  card, voice pins), per-shot data last. Measured by the token ledger's cached-token count.
- **Reasoning effort** per tier, set in config.
- **Batch API** for bulk, non-interactive work (re-embedding a corpus, "generate prompts for all
  shots" overnight).

**Gemini:** not needed for anything in Phases 0–5. The only Google dependency on the roadmap is
in-app **Veo rendering** (Q1), which is a video model, not an LLM. I will ask before adding it.

---

## 6. Agentic capabilities

The list below is what PromptMotion has proven, where each piece lives in the fork, and where
Hiru uses it. Items marked **new** are not in PromptMotion.

### 6.1 Proven in PromptMotion

| Capability | PromptMotion source | Hiru use |
|---|---|---|
| **Conductor routing**: a cheap call reads the message, picks a lane, extracts the user's explicit edits as operations and scopes tasks | `nova_chat/studio/engine.py` | Director chat |
| **Kernel-applied operations**: models propose ops, code applies them; user locks respected | `studio/ops.py` (PlanKernel), `brief_ops.py` (BriefKernel) | Scene/shot plan edits; script lines locked |
| **Dependency graph**: a change marks only the stale nodes; an edit that would rewrite most of the plan becomes a reshape offer instead | `studio/deps.py` | "Change shot 3 to a two-shot" re-tasks only what depends on it |
| **Parallel specialists with ownership** and a board that settles conflicts by owner | `studio/agents.py`, `studio/board.py` | Director, cinematography, dialogue/timing, sound, continuity, editing |
| **Verifiers + repair + bounded second round** | `repair_treatment`, free checks, round 2 | Every plan change ends valid or says why |
| **Two-critic loop** (correctness vs taste), idea gate | Vega critic loop | Structure build and shot producer review |
| **Continuity ledger** (append-only) | `nova_producer/engine/continuity.py`, `ledger.py` | Wardrobe, props, positions across shots and episodes |
| **IR → per-engine serializer** | `serialize.py`, `clip_schema_veo_3_1.yaml` | Veo prose now; Kling later via one schema + one serializer |
| **Deterministic dialogue binding** | `pm_contract/dialogue_binding.py` | Lines come from the approved script, pinned by code |
| **RAG grounding + intent → technique lookup**, classifier-filtered, absent-safe | `vega_chat/engine/retrieval.py`, `craft_techniques` | Camera recommendations in Production; chat grounding |
| **Streaming synthesis** (SSE), honest elapsed time, no fake progress | vega_chat turn | Director chat, live build |
| **Human in the loop**: approve before spend; upstream change flags, never redoes; picking is free | `routers/productions.py` rules | First frame accept unlocks prompt; canon change flags shots out of date |
| **Prompt hygiene + replay + tuner** with held-out cases and charter budgets | `docs/engines/prompt-hygiene.md`, `nova_studio_replay.py`, `nova_studio_tune.py` | Same guard tests and replay harness for Hiru charters |
| **Token ledger per phase** | `token_ledger`, `token_tracker` | Usage % and cost tracking (internal only) |

### 6.2 New for Hiru

- **Durable, resumable workflows.** LangGraph with a Postgres checkpointer (Supabase) for
  `structure_build` and `canon_extract`. The graph can stop on a question, wait for an answer
  from any member with the right role, and resume. Retries resume from the last node.
- **Agent tools (read-only).** The director chat can call `search_production(query)`,
  `get_scene(id)`, `get_canon(name)`, `get_shot_timing(scene_id)`, `list_open_questions()`. Tools
  only read; every write is a kernel operation, so the model never writes to the DB.
- **Production memory.** Approved decisions, director notes and resolved questions are stored as
  `memory_items` and retrieved like documents, so a decision made in Episode 2 is known when
  Episode 7 is planned.
- **Multi-user awareness.** Chat threads per scene, @-mentions of members, presence through
  Realtime, every agent change attributed (agent + triggering user) in `audit_log`.
- **Guardrails in code**: brand, public-figure and biographical-claim filter before a prompt
  leaves; overruns reported, never trimmed; silence stated for silent shots.
- **Evals as a release gate**: retrieval probes, prompt checks on a fixed set of Hiru scenes, and
  director-chat replay cases, run in CI on every change to a prompt or engine.
- **Tracing**: OpenTelemetry spans per agent call (model, tier, tokens, cached tokens, latency)
  to Cloud Trace, joined to `job_id`. See Q6 for an optional LLM trace UI.

---

## 7. RAG design

**Corpora** (one `chunks` table, separated by `corpus` and scope):

| Corpus | Scope | Source |
|---|---|---|
| `craft` | global | PromptMotion craft notes, scene rules, Veo guide, Hiru house style |
| `technique` | global | `craft_techniques` rows (structured, one CSV column per DB column, embedded effect-first) |
| `production_docs` | production | uploaded bible, scripts, canon index, notes |
| `canon` | production | canon cards (re-indexed on every new version) |
| `memory` | production | approved decisions, director notes, answered questions |

**Ingest** (`doc_ingest`)
1. Extract text per page or section, keep structure (scene headings, character cues, page numbers).
   Sinhala kept in Unicode NFC.
2. Chunk on structure first (scene, section), then by size (~500–800 tokens, small overlap).
3. **Contextual header** per chunk from the `low` tier ("Episode 3, Scene 12, Nimal and Kamala at
   the well"), stored and embedded with the chunk.
4. Embed in batches, store `embedding vector(1536)` + `fts tsvector` + metadata (production,
   document, episode, scene, characters, page).
5. Idempotent by content hash: unchanged chunks are not re-embedded.

**Retrieve** (`match_chunks` RPC, RLS-safe)
- **Hybrid**: HNSW vector search + Postgres full-text search, merged with reciprocal rank fusion.
  Full text matters for names and Sinhala terms embeddings handle badly.
- **Filters** from the caller (scene, episode, character, corpus), never from model text alone.
- **Rerank** the top ~30 with the `medium` tier, keep 5–8.
- **Placement**: retrieved text goes **after** the static prompt prefix (keeps the cache).
- **Absent-safe**: retrieval failure → agent runs without it and the job logs a warning.
- **Citations**: every answer from documents carries chunk ids, so the UI can show the source.

**Quality gate**: `scripts/eval_retrieval.py` with per-corpus probes (recall@k, MRR, off-scope
rate). Run on every corpus or retriever change; thresholds fixed in CI after Phase 1.

---

## 8. Data model (Supabase)

All tables have `id uuid`, `created_at`, `updated_at`, `created_by`, and RLS enabled.

**Access** (single tenant: one Hiru workspace, no organisations table)
- `profiles` — 1:1 with `auth.users`; display name, initials, `app_role` (`admin | member`),
  `active`. Created by a trigger on `auth.users`.
- `invitations (email, app_role, production_id?, production_role?, invited_by, accepted_at)` —
  sign-up is invite-only; a pending invitation is applied when the invited user's profile is created.
- `production_members (production_id, user_id, role)` — see §9.
- `audit_log (production_id?, actor_user_id, actor_agent, action, entity, entity_id, diff jsonb)`.

**Production content**
- `productions (title, kind, language, orientation 'horizontal'|'vertical', status, settings jsonb)`.
- `documents (production_id, storage_path, mime, detected_role, confirmed_role, status, hash)`.
- `episodes (production_id, number, title, synopsis, status)`.
- `scenes (episode_id, number, heading, location_id, envelope_seconds, script jsonb, status, locked_at)`.
- `shots (scene_id, number, duration_s check in (4,6,8), sound_mode, camera_link, frame_strategy,
  beats jsonb, ir jsonb, status, version)`.
- `dialogue_lines (scene_id, shot_id?, beat_index?, character_id, text, delivery, order)`.
- `canon_entities (production_id, kind character|location|prop, name, current_version_id, locked)`
  + `canon_versions (entity_id, version, card jsonb, wardrobe_anchor, voice_pin, reference_assets)`.

**Director and production work**
- `director_personas` (global library) + `production_director_board (production_id, persona_id, seat lead|advisor)`.
- `chat_threads (production_id, scene_id?, title)` + `chat_messages (thread_id, author_user_id?, agent?, content, ops jsonb, citations jsonb)`.
- `questions (production_id, job_id, scope, text, options jsonb, answer, answered_by)` — the live build's questions.
- `first_frames (shot_id, n, storage_path, prompt, accepted_at, accepted_by)`.
- `video_prompts (shot_id, version, prose, ir jsonb, checks jsonb, stale bool)`.
- `takes (shot_id, storage_path, uploaded_by, accepted, last_frame_path)`.
- `memory_items (production_id, kind, text, source_ref)`.

**Jobs, RAG, usage**
- `jobs (production_id?, kind, status, request, result, error, requested_by, cursor)`.
- `job_events (job_id, seq, agent, type, payload)` — Realtime-published.
- `chunks (corpus, production_id?, document_id?, content, context_header, embedding, fts, meta)`.
- `craft_techniques` (as PromptMotion schema-v34).
- `token_usage (production_id, job_id, phase, model, input, cached_input, output)`.
- `usage_budget (month, budget_units)` → `usage_percent` view.
- LangGraph checkpoint tables (managed by the checkpointer, in a separate `graph` schema).

---

## 9. Roles and permissions

Two layers:
- **Workspace role** (`profiles.app_role`): **admin** or member. An **admin** has every
  permission on every production and is the only role that can manage members, settings and
  orientation. Productions are created by admins, because orientation is chosen at creation.
- **Production role** (`production_members.role`): what a member can do inside one production.
  A member with no role on a production cannot see it.

| Action | admin | producer | director | writer | production | reviewer |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| View production, canon, shots, prompts | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Comment / chat | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create productions; manage members, settings, orientation | ✓ | | | | | |
| Upload documents, confirm file roles, run structure build | ✓ | ✓ | ✓ | | | |
| Answer live-build questions | ✓ | ✓ | ✓ | ✓ | | |
| Edit script & dialogue | ✓ | ✓ | ✓ | ✓ | | |
| Edit / lock canon, voice pins | ✓ | ✓ | ✓ | | | |
| Director chat edits, split scenes, set shot lengths, manage director board | ✓ | ✓ | ✓ | | | |
| Generate / accept first frames, generate video prompts | ✓ | ✓ | ✓ | | ✓ | |
| Copy / download handoff bundle, upload takes | ✓ | ✓ | ✓ | | ✓ | |
| Approve a scene for production (lock) | ✓ | ✓ | ✓ | | | |

**Enforcement**
1. **API**: one permission table in `contracts/roles.py`; routes declare
   `require_permission(Permission.EDIT_SCRIPT)` or `require_admin`. Tested as a full matrix.
2. **Postgres RLS**: SQL helpers `is_admin()`, `my_production_role(production_id)`,
   `can_view_production(production_id)` (SECURITY DEFINER, stable). Reads: a user sees a
   production's rows only if they are an admin or a member of it (this protects Realtime and
   direct supabase-js reads). Writes: **the browser writes nothing directly**; every write goes
   through the API, so the permission table above is enforced in one place.
3. Roles are read from the database on each request (no custom JWT claims), so a role change
   applies immediately.
4. Functions run with the service role but receive `actor_user_id` and write it to `audit_log`.
5. RLS is tested in SQL against the local Supabase stack in CI: each role × each table.

---

## 10. API surface (by screen)

All under `/v1`. Long work returns `{job_id}`; progress through Realtime on `job_events`.

| Screen | Endpoints |
|---|---|
| Auth / workspace | `GET /me`, `GET /members`, `PATCH /members/{id}` (admin: workspace role, active), `POST /invitations` (admin, sends the Supabase invite email), `GET/PUT/DELETE /productions/{id}/members` (admin) |
| 00 Productions home | `GET /productions` (with resume point), `POST /productions` |
| 0a New production | `POST /productions/{id}/documents` (upload), `PATCH /documents/{id}` (confirm role), `PATCH /productions/{id}` (orientation, what AI builds, director board) |
| 0b Live build | `POST /productions/{id}/build` → job; `GET /productions/{id}/questions`; `POST /questions/{id}/answer` (resumes the graph) |
| 1 Drama overview & canon | `GET /productions/{id}/episodes`, `GET/PATCH /canon/{id}`, `POST /canon/{id}/versions`, `POST /canon/{id}/lock` |
| 2d Director panel | `GET /scenes/{id}` (script, shots, timeline data), `POST /scenes/{id}/chat` (SSE), `GET /scenes/{id}/threads`, `POST /scenes/{id}/resplit` → job, `PATCH /shots/{id}` (length 4/6/8, sound mode), `GET/PUT /productions/{id}/director-board`, `GET /director-personas` |
| 3d Production panel | `GET /shots/{id}` (camera rec, frames, prompt lock state), `POST /shots/{id}/frames` (single), `POST /scenes/{id}/frames` (batch) → job, `POST /frames/{id}/accept`, `POST /shots/{id}/prompt` (only after a frame is accepted) |
| 4 Prompt & handoff | `GET /shots/{id}/prompt` (prose + checks), `GET /scenes/{id}/bundle` (zip), `POST /shots/{id}/takes`, `POST /takes/{id}/accept` |
| Shared | `GET /jobs/{id}`, `GET /files/{ticket}` (streamed, Range-aware), `GET /usage` → `{percent}` only, `POST /internal/pipeline/advance` (functions → API, secret + OIDC) |

**Rules carried over**
- **No storage-provider URL ever reaches a client.** Files go through encrypted `/files/{ticket}`.
- Timeline numbers (shot edges, dialogue spoken length, overruns) are computed by
  `contracts.timing` on the server, so the Director and Production panels agree.
- `/usage` returns a percentage only.

---

## 11. Infrastructure and delivery

- **GCP**: separate project for Hiru (region per Q5). Cloud Run (`hiru-api`, `assemble`), Cloud Run
  functions (gen2, internal ingress), Cloud Tasks queues per function, Secret Manager, Artifact
  Registry, Cloud Logging/Trace. One service account per function, least privilege.
- **Terraform** in `infra/terraform`. Workload Identity Federation for GitHub Actions; no keys.
- **Supabase**: separate project. Private storage buckets (`documents`, `frames`, `takes`,
  `references`). PITR backups on.
- **CI** (`ci.yml`): ruff, mypy, pytest, isolation tests, `verify_vendored`, pgTAP RLS tests,
  prompt-hygiene guard, retrieval + prompt evals (on changes to prompts or engines).
- **Deploy**: API on push to `main` (Cloud Run revision, health check, traffic shift); functions
  only when their folder or `contracts` changed (PromptMotion's workflow); migrations through
  `supabase db push` with a manual approval for production.
- **Environments**: `local` (Supabase CLI + functions-framework, `LOCAL_FUNCTIONS=true`),
  `staging`, `prod`.
- **Python 3.12** in production (3.12+ locally), `pip` + venv, dependencies pinned per service.

---

## 12. Quality, security, observability

- Unit tests for kernels, timing, binding, serializer (golden prose files per sample scene).
- Contract tests between API and each function (pydantic models in `contracts`).
- Replay harness for the director chat (held-out cases), copied from Nova's.
- Security: JWT verification by JWKS, RLS everywhere, file tickets, upload type and size limits,
  per-user rate limits (slowapi), prompt-injection handling for uploaded documents (document text
  is data: wrapped and labelled, never placed in system instructions), PII-free logs.
- Observability: structured JSON logs with `job_id`/`user_id`, OpenTelemetry traces, token
  ledger, alerting on job failure rate and function errors.

---

## 13. Phased delivery

Each step is a separate PR that you review before the next one starts.

**Phase 0 — Foundations** — *built and verified locally 2026-10-23; not yet deployed (needs the
GCP + Supabase projects, README "First deploy").*
1. Repo scaffold, lint/type/test tooling, `CLAUDE.md`, `.env.example`.
2. `libs/contracts` v1: production hierarchy, roles, jobs, Veo/timing rules (ported + tested).
3. Supabase migrations: profiles (workspace role), invitations, productions, production
   members, audit, jobs, RLS helpers and policies, SQL RLS tests.
4. API skeleton: settings, JWKS auth, authz matrix, `/me`, members, invitations,
   productions CRUD, production members, file tickets, health.
5. Task dispatch (`task_manager`, local + Cloud Tasks), `jobs` + `job_events` + Realtime.
6. Terraform for the GCP project, CI, staging deploy of the API.

**Phase 1 — Documents and RAG** — *built and verified locally 2026-10-23 (keyword mode; the
hybrid mode needs an OpenAI key to measure). See IMPLEMENTED.md.*
7. Storage buckets + upload endpoint; `doc_ingest` (extract, role detection, chunk, header, embed).
8. `chunks` table, `match_chunks` hybrid RPC, reranker, citations.
9. Craft corpus + `craft_techniques` ingest; `eval_retrieval.py` with Hiru probes; set thresholds.

**Phase 2 — Structure and canon**
10. `script_split` + timing kernel (4/6/8 ladder, envelope fit, word targets, overrun flags).
11. `structure_build` (LangGraph, checkpointer, questions, progress events).
12. `canon_extract` + canon versions, locks, voice pins, reference-sheet prompts.
13. Endpoints for screens 0a, 0b, 1.

**Phase 3 — Director panel** — *built and verified locally 2026-10-24 (rules mode; see IMPLEMENTED.md).*
14. Fork `nova_chat` → `director_chat`; swap the kernel's document to Hiru scenes/shots; OpenAI tiers.
15. Read tools, server-side threads, production memory, director board personas.
16. Timeline data endpoint, shot length edits, re-split; replay harness + hygiene guards.

**Phase 4 — Production panel**
17. Fork `nova_producer` → `shot_producer` (camera recommendation, frame strategy, Veo prose).
18. Fork `video_render` → `frame_render` with the OpenAI image provider; single + batch.
19. Accept-frame → prompt unlock; staleness when canon or shots change upstream.

**Phase 5 — Handoff**
20. `prompt_check`, bundle download, takes upload, `assemble` `/last-frame` for carried frames.
21. Usage % (token ledger → budget view).

**Phase 6 — Hardening**
22. Evals in CI as gates, tracing dashboards, load test of batch frame generation, security
    review, backup/restore drill, production cut-over.

**Later**: in-app Veo rendering (needs Google, Q1), Kling serializer, localisation, `/join`
final cut.

---

## 14. Open questions

Decided 2026-10-23:

| # | Question | Decision |
|---|---|---|
| Q1 | In-app video generation (Veo through Google's API) | Out of scope until after Phase 5; handoff stays "Copy for Flow" + takes upload. Ask again then. |
| Q2 | Roles | Production roles producer, director, writer, production, reviewer, plus a workspace **admin** who alone manages members, settings and orientation and has every other permission. Producers do **not** manage members, settings or orientation. |
| Q3 | Fixed 8 s shots or the 4/6/8 ladder? | Build the ladder; a production setting can force 8 s. |
| Q4 | Is 10 s renderable on current Veo 3.1? | Keep 10 s off until verified. |
| Q5 | GCP region | `asia-south1` (Mumbai) for API and functions; Supabase in its nearest region (`ap-south-1`). |
| Q6 | LLM trace UI | Cloud Trace + our token ledger first; Langfuse (self-hosted) only if agent debugging needs it. |
| Q7 | Sharing with PromptMotion | Forks + `UPSTREAM.md` + diff script now; extract a shared package only for code both sides change often. |
| Q8 | Document formats | Text-layer PDF, Markdown and other plain-text files. **No OCR**; scanned PDFs are rejected with a clear message. |
| Q9 | Tenancy | **Hiru only.** No organisations table. |
