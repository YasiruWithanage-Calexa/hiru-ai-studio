# Test deployment: what is built

Plan: [PLAN.md](PLAN.md). Updated 2026-11-27.

**Phases 0 to 4 are done: the interface, the API, the 15 functions and `assemble` are deployed.** Storage is still
Supabase Storage. Phases 5 and 6 are open. No job has run in the cloud yet.

## Phase 0

Done by the user: the budget alert; the database `gzvtzarhcwrtzyzvgymp` is at schema v30; the API address is
`sslip.io`. Terraform 1.17.2 installed with winget.

## Phase 4

Deployed 2026-11-27: `assemble`, the 15 functions (`hiru-echo` first, then three groups at once), the API.

| Check | Result |
|---|---|
| API over HTTPS | `/healthz` 200 with a valid certificate; plain HTTP redirects |
| Signed out | `/v1/*` 401, a bad file ticket 404, the internal callback without its secret 403 |
| Browser origins (CORS) | the site allowed, another origin refused |
| **F4: the VM reaches internal-only functions** | **yes**: all 15, called from the API container with its identity, answer from the function (400 to an empty body); without identity 403 |
| `assemble` | 200 with an identity, 403 without |
| Functions | all `ACTIVE`, internal ingress, maximum 10; `graph` engine on the two; the Google key only on `hiru-video-render` |
| Restart of the VM | the API answers again after about 24 s, by itself |
| Server | 1.3 GB memory free; `api.env` readable by root only; no application errors in the logs |

Fixed on the way: `--build-service-account` takes the address alone (a full resource name was doubled); the deploy
scripts get Terraform's token themselves and no longer take a tool's progress output for a failure.

- Not run yet: a job through Cloud Tasks, a function calling the API back, `hiru-video-render` calling `assemble`
  (each needs a real job, phase 6).
- The API's `/docs` page is public in `staging`, as the code has it for anything but `prod`.
- Internet scanners already probe the address; they get 404.
- The user added the redirect address in Supabase, signed in and saw their productions, frames and sheets load. In
  the next half hour: 139 API requests, no 5xx, slowest about 1.1 s, no function or site errors, 1.36 GB memory free.

## Phase 3

Done 2026-11-27. The user added Firebase to the backend's project (SceneCraft-ai-Project), so there is one project; the
separate project `hiru-ai-studio` made first is not used (our account could not set anything up in it).

| What | Value |
|---|---|
| Site | `https://hiru-studio--project-5e9aa04e-5c47-45e7-bbb.asia-southeast1.hosted.app` |
| Backend | App Hosting `hiru-studio`, `asia-southeast1`, local source deploy (`npx firebase-tools@15.37.0`; the installed 14.14.0 has no prompt-free create) |
| Interface repo | `firebase login:use yasiru@calexa.io` for the folder, `.firebaserc`, `apphosting.yaml` |

Checked: **Next.js 16 builds and runs on App Hosting** (no fallback needed); `/` and signed-out pages redirect to
`/login`; the login page and its 12 scripts load with the security headers; the browser files name the cloud API and the
Supabase project, not localhost, and hold no secret key; the 520 uploaded files include no `.env.local`; the upload
bucket has no public grant; no errors in the logs.

Not checked: signing in and out (needs a person); pages that read the API (phase 4).

- `/auth/accept` answers 404: the interface has no such page, though the API sends invitations there
  (`SUPABASE__INVITE_REDIRECT_URL`). The route list showed none before this deployment either.
- The first local build stopped once with Next.js's notice that "your version of Next.js is affected by a known
  security vulnerability" (`experimental.agentUpgrade`); `npm audit` lists no advisory for `next` (6 moderate, in
  `shadcn` and what it brings), 16.4.6 was the newest published version, and the upgrade it suggests was not run.

## Phase 2

Applied 2026-11-27: the state bucket, then 23 resources (APIs and empty secrets), the six secret values, then 41
resources. A second plan shows no differences.

| What | Value |
|---|---|
| API address | `https://136-85-47-52.sslip.io` (VM `hiru-staging-api`, `asia-southeast1-b`); nothing runs on it yet |
| `assemble` | `https://hiru-staging-assemble-p6kgwapc3a-as.a.run.app`, a placeholder image until phase 4 |
| Media bucket | `scenecraft-test-media` (empty; storage is still `supabase`) |
| State bucket | `project-5e9aa04e-5c47-45e7-bbb-tfstate` |
| Uptime alert | to the address the user gave (`staging.tfvars`) |

Checked: the VM runs; Docker, Compose, 2 GB swap, automatic updates and the folders are in place (1.5 GB of memory
free); login works through the tunnel; port 22 does not answer from the internet; the bucket enforces public access
prevention; no `allUsers` grant on the project or the bucket; `assemble` answers 403 without an identity.

- The apply is in two steps: the secrets (with `-target`), their values, then everything. `assemble` cannot be created
  while a secret it reads has no value.
- `api-internal-secret` and `assemble-secret` are made new for the cloud, never copied from `.env`.
- Terraform signs in with `GOOGLE_OAUTH_ACCESS_TOKEN` from `gcloud auth print-access-token`: this machine already has an
  application default credentials file used by other work, and it was left as it is. Phase 5 needs localhost to reach
  the bucket and has to settle which sign-in it uses.
- Organization rules checked: a public address is allowed and OS Login is not required. Automatic rights for default
  service accounts are switched off, which is what the build account is for.
- Service accounts now wait for the APIs to be enabled.
- `assemble` ignores the service-level `scaling` block, which showed as a difference on every plan.
- The first login added an SSH key for this machine to the VM.
- The uptime check fails, and mails the alert, until the API is deployed in phase 4.

## Built

| Part | Where |
|---|---|
| One place that says where files live: `FILES__BACKEND=supabase\|gcs`, `FILES__GCS_BUCKET`, `FILES__READ_FALLBACK` | `src/libs/hiru_ai/core/media.py` |
| Used by the API (upload, download, removal, disk cache, `/files`) | `api/services/media_store.py`, `repositories/supabase.py`, `services/file_cache.py`, `routers/files.py` |
| Used by the AI package, 12 function storage clients and the scripts | `hiru_ai/adapters/`, `services/*/runtime/`, `scripts/_common.py` |
| `assemble` on Cloud Storage (its own copy, held equal by a test) | `infra/assemble/app.py` |
| Copy of existing files: dry run by default, never overwrites or deletes | `scripts/copy_media.py` |
| Terraform: VM, network, firewall, static address, uptime check, media bucket, build account, secrets, queue limits | `infra/terraform/` (`run.tf` removed) |
| What runs on the VM: Docker Compose, Caddy, first boot, deploy with return to the previous version | `infra/vm/` |
| One settings list for the cloud | `infra/env/staging.env` |
| Deploys by hand | `scripts/deploy_{api,functions,assemble}.ps1`, `deploy_common.ps1` |
| `deploy-api.yml` and `migrate.yml` disabled | `.github/workflows/` |
| Frontend hosting settings (interface repo) | `apphosting.yaml`, `firebase.json`, `.firebaserc` |
| Docs | `README.md`, `CLAUDE.md`, `.env.example`, `UPSTREAM.md` notes |

With `FILES__BACKEND` unset, storage requests are the ones sent before.

## Different from the plan

| # | Change | Why |
|---|---|---|
| 1 | One shared storage module, not a copy in each service | Every bundle already ships `hiru_ai`, and two services already import `hiru_ai.core` |
| 2 | The Supabase project is `gzvtzarhcwrtzyzvgymp` | Backend `.env`, database URL and interface all use it; confirmed by the user, and `CLAUDE.md`, the READMEs and both `.env.example` files now name it |
| 3 | `AI_ENGINE=graph` for `hiru-shot-producer` and `hiru-frame-render` | Localhost always starts them that way; the old workflow did not |
| 4 | No OS Login on the VM | For an account from another organization it needs a grant on the organization |
| 5 | A separate build account for functions | A new project may leave the default one without rights |
| 6 | Memory: `hiru-shot-producer` 512 MB to 1 GB, `assemble` 1 GB to 2 GB | The workers' 300 MB in-memory file cache and the take cache |
| 7 | Added `scripts/deploy_assemble.ps1` and `.gitattributes` | `assemble` had no hand deploy; Linux files need LF line ends |
| 8 | `scripts/copy_media.py` written now (used in phase 5) | Part of the storage work |

## Checked on this machine

| Check | Result |
|---|---|
| New storage tests (both backends, no network) | pass |
| Full test suite (6,620 tests) | 6,525 passed, 30 skipped, **65 failed, none caused by this phase** (below) |
| `ruff` | 5 findings, all in files this phase did not change (same 5 as before) |
| `mypy` (API, contracts, AI package) | clean |
| `mypy` per service | clean except `shot_producer`: errors in 3 files this phase did not change |
| Import rules | 49 kept, 3 broken: the same 3 as before; the new import is listed as an exception |
| AI catalog | current |
| Terraform | `fmt` and `validate` pass; the settings file is read correctly |
| API container | builds, starts, `/healthz` answers, signed-out call 401, bad file link 404, data files present |
| Function bundles | all 15 install and start in a clean Linux container. 14 import every module; `hiru-video-render` uses only the file cache and storage modules of `hiru_ai`, and its own modules all import |
| Deploy scripts | dry run with made-up values; two bugs found and fixed |
| VM files | Compose and Caddy files valid, shell syntax valid, secrets with quotes and `$` arrive unchanged |

### The 65 failures

Each was run again on an untouched copy of the last commit, with the same `.env`:

- **62** fail there too, with the same summary lines (the Adam planner's gold and system tests, `script_split`, planner
  checks, group removal scans, some API tests).
- **3** (`stray or misspelt folder`) are caused by folders holding only old `__pycache__` files on this machine:
  `hiru_ai/steps/prompt_polish`, `hiru_ai/steps/zora`, `hiru_ai/agents/prompt_writer`. The same copy fails them when
  those folders are added. The deploy script now leaves empty folders out of every bundle.
- Of the 62, **11** pass when the switches in `.env` (`ADAM_MODE`, `USAGE_DETAIL`, `ZORA__ENABLED`, image quality,
  tracing keys) are set back to their defaults; **51** fail whatever they say. Their cause was not looked into.

## Not checked

- Cloud Storage has not been called for real: tests stand in for the bucket and the token.
- The app was not started against the hosted database: the running API writes to it (the stuck-job sweeper).
- `supabase test db` was not run: no database change.

## Open

**Needs a person**

- The interface has no `/auth/accept` page yet (invitation links).
- Approve phase 5 (media move).

**Later**

- `deploy-functions.yml` and `deploy-assemble.yml` still start on a push to `main` and fail without the GitHub
  identity. They need rewriting with `deploy-api.yml` when GitHub deploys are turned on.
