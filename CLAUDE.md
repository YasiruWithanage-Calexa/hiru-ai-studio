# Hiru AI Studio backend — working rules

Read the current plan first: [plan/2026-10-23/PLAN.md](plan/2026-10-23/PLAN.md) (design, phase
order, decisions log in §14), then [plan/2026-10-23/IMPLEMENTED.md](plan/2026-10-23/IMPLEMENTED.md)
(what is built, deviations, open items). Code comments cite it as "PLAN.md §n". Implementation
goes one phase at a time; at the end of a phase, update IMPLEMENTED.md. A new plan revision goes
in a new `plan/<date>/` folder.

## Fixed decisions (ask before changing any)
- **LLMs are OpenAI only.** Ask the user before using Gemini or any other Google model.
- Supabase for auth, DB, storage, realtime and pgvector. **Hiru only** (single tenant).
- Proven PromptMotion engines are **forked**, not imported (PLAN.md §2.1). Each fork gets an
  `UPSTREAM.md` with the source path, commit (`1d748dc` at plan time) and every divergence.
- The UI shows **no credits or costs**; `/v1/usage` returns a percentage only.
- Nothing is deployed until the user says so; everything is tested on localhost first.

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
- Sinhala: keep ZWJ/ZWNJ (conjuncts), normalise to NFC; full text search uses the `english`
  config (verified to keep Sinhala words whole).

## Files
- **Never return a storage-provider URL** (signed or public) to a client. Use
  `api/services/media_links.url()` → `GET /files/{ticket}`.

## Veo and timing
- `contracts/veo.py` and `contracts/timing.py` mirror the frontend's `src/lib/veo/timing.ts`;
  change both in the same PR and keep `tests/contracts/test_timing.py` in parity with its tests.
- Overruns are reported, never auto-trimmed. 10 s shots stay off until verified (PLAN.md Q4).

## Conventions
- Settings via `get_settings()` only (`lru_cache`); nested env vars use `__`.
- **Hosted dev DB** (`dwivfkavmtjzhypqswze`) is managed by hand from [Database/](Database/README.md):
  `schema_v1.sql` is the full schema, run in the SQL Editor; the user edits data there directly.
  A structural change goes in two places in the same step: a new `Database/changes/NNN_<what>.sql`
  (the user runs it) and a migration (local stack + tests). Keep the two equivalent; fold the changes
  into the next `schema_vN.sql` when they pile up. Never run SQL against the hosted project myself
  unless the user asks.
- Migrations: new timestamped file in `supabase/migrations/`; never edit one that has been
  applied to staging or prod (none has been yet).
- Before finishing a step: `ruff check src tests scripts`, `mypy` (and per service, as in CI),
  `pytest -q`, `npx supabase test db`, `npx supabase db advisors --local --level warn`, and for
  retrieval changes `scripts/eval_retrieval.py` (`--runs 3` in hybrid mode).
- Schema work: follow `.claude/skills/supabase*` (installed). Create migration files with
  `npx supabase migration new <name>`; never hand-pick the timestamp.
- Tests never call OpenAI or any network service. API tests force `OPENAI__API_KEY` empty.
