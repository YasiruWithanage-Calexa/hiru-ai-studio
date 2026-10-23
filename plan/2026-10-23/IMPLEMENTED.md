# Implemented so far (against PLAN.md of 2026-10-23)

Status on **2026-10-23**: Phases 0 and 1 are built and verified on localhost, including a real
OpenAI run. Supabase agent skills (`supabase`, `supabase-postgres-best-practices`) are installed in
`.claude/skills/`. **Nothing is
deployed** (by decision: test locally first). Commits are made by hand.

| Phase | Steps | State |
|---|---|---|
| 0 — Foundations | 1–6 | Done locally. Terraform and CI written and validated, not applied. |
| 1 — Documents and RAG | 7–9 | Done locally, in keyword mode and (with an OpenAI key) hybrid mode. |
| 2–6 | 10–22 | Not started. |

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
- Not done yet (left to the user): running it on the hosted project and pointing `.env` at it,
  which needs the project's secret key.

## Not done yet from the plan (Phases 0–1 scope)

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

## Next

Phase 2 (steps 10–13): `script_split` with the timing kernel, `structure_build` (LangGraph with
questions to the crew), `canon_extract` with versions and voice pins, and the endpoints for
screens 0a, 0b and 1.
