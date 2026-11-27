# Hiru AI Studio — backend

Python backend for Hiru AI Studio: a FastAPI API (on one VM), Cloud Run functions for the AI
engines, and Supabase for auth, database, storage, realtime and vector search.
The frontend lives in `../hiru-ai-studio-interface`.

- Design and phase plan: [plan/2026-10-23/PLAN.md](plan/2026-10-23/PLAN.md)
- What is built so far: [plan/2026-10-23/IMPLEMENTED.md](plan/2026-10-23/IMPLEMENTED.md)

**Status:** Phases 0–3 are built and verified locally (API and functions on this machine).
Nothing is deployed yet (the test deployment: [plan/2026-11-27](plan/2026-11-27/PLAN.md)).

**The one dev database is the hosted Supabase project `gzvtzarhcwrtzyzvgymp`** (schema
`Database/schema_v2.sql`, managed by hand: [Database/README.md](Database/README.md)). The API,
the functions, the frontend and the scripts all point at it. The local Supabase stack is only for
the automated database tests (`npx supabase test db`), which need a throwaway database.

## Local development

Needs Python 3.12+. Node and Docker Desktop only to run the database tests locally.

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

copy .env.example .env               # then fill the hosted project's secret key, DB URL, OpenAI key

# The first admin (sign-up is invite-only). --password creates a confirmed local user.
.venv\Scripts\python scripts\create_admin.py you@hirutv.lk --password <pw> --name "Your Name"
.venv\Scripts\hiru-ai ingest --all   # craft knowledge + camera techniques

.venv\Scripts\python -m uvicorn api.main:app --app-dir src --reload --env-file .env   # API on :8000, docs at /docs
powershell -File scripts\start-functions.ps1        # echo :8201, doc_ingest :8202, script_split :8203,
                                                    # structure_build :8204, canon_extract :8205, director_chat :8206

.venv\Scripts\python scripts\smoke_local.py  you@hirutv.lk <pw>   # Phase 0 end-to-end check
.venv\Scripts\python scripts\smoke_phase1.py you@hirutv.lk <pw>   # documents → ingest → search
.venv\Scripts\python scripts\smoke_phase2.py you@hirutv.lk <pw>   # build: canon → structure → shots, questions
.venv\Scripts\python scripts\smoke_phase3.py you@hirutv.lk <pw>   # Director panel: edits, chat, board, memory
```

The smoke scripts create productions and `*@hirutv.lk` test users in the dev database; delete
them in the dashboard when you are done (Authentication → Users, and the productions table).

### With and without an OpenAI key

Everything runs without `OPENAI__API_KEY`: documents are indexed for keyword search, file roles
come from rules, and search is not reranked (responses say `"mode": "text"`). With a key, the
same code adds embeddings (hybrid search), model role detection for unclear files, a
descriptive header per passage, and reranking. After adding a key, re-ingest documents
(`POST .../documents/{id}/reingest`) and re-run `hiru-ai ingest --all`.

## Documents and search (Phase 1)

- Upload: `POST /v1/productions/{id}/documents` (multipart `file`). Text-layer PDF, Markdown,
  plain text or Fountain, at most 25 MB. Scanned PDFs and non-UTF-8 text are **rejected** with
  a message saying how to fix the file. The same file uploaded twice is one document.
- The `doc_ingest` function reads the file, detects its role (bible, script, canon index,
  outline, notes), splits it along its structure (scenes, headings), and indexes it. Progress
  arrives as `job_events` (Realtime); document status changes are on Realtime too.
- `GET .../documents` lists files needing role confirmation first; `PATCH .../documents/{doc}`
  confirms a role (switching into or out of `script` re-ingests, since scripts split by scene).
- Search: `POST /v1/productions/{id}/search` `{query, corpora?, roles?, k?, rerank?}` returns
  passages with citations (file, section, pages). `POST /v1/craft/techniques/search` finds a
  camera technique by the effect it should have ("she should feel trapped").

## Director panel (Phase 3)

- `GET /v1/productions/{id}/scenes/{scene}`: the script, shots, lines and the **timeline**
  (shot edges, when each line is spoken, overruns, the envelope), computed on the server by
  `contracts.shotplan` so every panel shows the same numbers.
- By hand: `PATCH .../shots/{shot}` (length 4/6/8 locks it; `null` releases it; sound, framing,
  join, title), `PUT .../scenes/{scene}/script` (writers; lines keep their ids and shots follow),
  `POST .../scenes/{scene}/resplit` (a `script_split` job), `POST .../approve` / `unapprove`.
- Chat: `POST .../scenes/{scene}/chat` streams one director turn (server-sent events: `accepted`,
  `status`, `delta`, `plan`, `message`, `done`, `error`). The `director_chat` function edits the
  shot plan only through kernel operations; dialogue is read-only. Threads and messages are
  stored and shared (`GET .../scenes/{scene}/threads`, `GET .../threads/{thread}/messages`).
- Board: `GET /v1/director-personas`, `GET/PUT .../director-board` (one lead, up to three
  advisors). Memory: `GET/POST/DELETE .../memory` (also written by the chat and by answered
  build questions; searched like documents).
- `scripts/replay_director.py` replays held-out director cases (`--model` with a key);
  `scripts/upstream_diff.py --upstream <PromptMotion checkout>` lists upstream changes to forks.

## Checks

```powershell
.venv\Scripts\python -m ruff check src tests scripts
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest -q
# Use `npx -y supabase@2.121.0` if an older global CLI rejects supabase/config.toml.
npx supabase start; npx supabase test db   # SQL tests on a throwaway local database (Docker), then
npx supabase stop                          # stop it again; the dev database is the hosted one
npx supabase db lint --level error
.venv\Scripts\python scripts\eval_retrieval.py      # retrieval quality vs tests/eval/thresholds.json
.venv\Scripts\python scripts
eplay_director.py     # director replay cases (rules mode; --model with a key)
```

CI runs all of these (plus mypy per service and `terraform validate`), see `.github/workflows/ci.yml`.

## Layout

| Path | What |
|---|---|
| `src/api/` | FastAPI app: `deps/` (auth, authz), `routers/`, `repositories/` (all DB access), `services/` (AI, retrieval, file tickets), `workers/task_manager.py` (dispatch) |
| `src/libs/contracts/` | Shared wire contracts (pydantic only): roles, production model, Veo rules, timing, jobs, documents |
| `src/services/<name>/` | One Cloud Run function each; imports only itself + `contracts`. `echo` (template), `doc_ingest`, `script_split`, `structure_build`, `canon_extract`, `director_chat` (fork, `UPSTREAM.md`) |
| `src/libs/hiru_ai/knowledge_bases/` | The knowledge bases (craft corpus copied from PromptMotion, `UPSTREAM.md`), one folder each |
| `supabase/` | `config.toml`, `migrations/`, `tests/` (pgTAP) |
| `infra/terraform/` | GCP project: the API VM, the media bucket, Cloud Run, Cloud Tasks, IAM, Secret Manager |
| `infra/vm/`, `infra/env/` | What runs on the API VM (Compose, Caddy, deploy); each environment's settings |
| `scripts/` | `create_admin`, `eval_retrieval`, `replay_director`, `upstream_diff`, `smoke_local`, `smoke_phase1`–`3`, `start-functions.ps1` |
| `tests/fixtures/corpus/` | "Harbour Lights", an invented sample production for tests and evals |
| `plan/` | Plans, one folder per planning date |

## Access model

Single tenant (Hiru only). A workspace **admin** can do everything and is the only role that
creates productions and manages members, settings and orientation. Inside a production a
member is a **producer**, **director**, **writer**, **production** (crew) or **reviewer**; the
full table is in `src/libs/contracts/roles.py` and PLAN.md §9. The browser reads through RLS
and writes only through the API.

## Deploying the test environment

The plan, the order of the phases and what each needs from a person: [plan/2026-11-27/PLAN.md](plan/2026-11-27/PLAN.md);
what is built: its [IMPLEMENTED.md](plan/2026-11-27/IMPLEMENTED.md). The API runs on one VM (`infra/vm`), the AI workers
on Cloud Run functions, `assemble` on Cloud Run, the interface on Firebase App Hosting; Supabase keeps sign-in and the
database. Deploys are run by a person:

1. Create the Terraform state bucket (see `infra/terraform/versions.tf`), copy `staging.tfvars.example` to
   `staging.tfvars` and fill it, then in `infra/terraform`:
   `terraform init -backend-config="bucket=<project>-tfstate"`, `terraform workspace select -or-create staging`.
   Terraform signs in with a short-lived token, so the machine's application default credentials stay as they are:
   `$env:GOOGLE_OAUTH_ACCESS_TOKEN = gcloud auth print-access-token`.
2. The secrets first, because `assemble` cannot be created while a secret it reads has no value:
   `terraform apply -var-file=staging.tfvars -target=google_secret_manager_secret.secrets`, then
   `scripts/load_secrets.ps1` (from `.env`; or `gcloud secrets versions add hiru-staging-<name> --data-file=-`), then
   `terraform apply -var-file=staging.tfvars`.
3. With Docker running: `scripts/deploy_assemble.ps1`, `scripts/deploy_functions.ps1`, then
   `scripts/deploy_api.ps1 -FrontendUrl https://<interface>`.
4. In Supabase Auth: keep "Allow new users to sign up" **off** and the **e-mail provider enabled** (turning off e-mail
   sign-up disables e-mail login too), and add the interface's `/auth/accept` URL to the redirect allow-list.

Settings of the environment are in `infra/env/staging.env` (the API and the functions get the same list). The
**Deploy API** and **Migrate database** workflows are disabled: the database is managed by hand (`Database/README.md`).
