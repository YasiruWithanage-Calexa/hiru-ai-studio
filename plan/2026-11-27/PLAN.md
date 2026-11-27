# Test deployment on Google Cloud

Date: 2026-11-27. Status: **proposed, nothing built or deployed**.

This replaces the "First deploy" steps in `README.md` for the test environment. It does not change the product.

Revision, same day: the API runs on an **`e2-small` virtual machine**, not Cloud Run.

## 1. Decisions

### Made

| # | Decision |
|---|---|
| G1 | A **test** deployment that uses the current hosted Supabase project (`gzvtzarhcwrtzyzvgymp`, the one in `.env` today). Production is later. |
| G2 | Google Cloud project `project-5e9aa04e-5c47-45e7-bbb` (SceneCraft-ai-Project), `gcloud` profile `scene-craft`. |
| G3 | Region **`asia-southeast1`** (Singapore), where the database is. Replaces PLAN.md Q5 (`asia-south1`). |
| G4 | API on one **Compute Engine `e2-small` VM**, always on. Workers on **Cloud Run functions**; the ffmpeg service (`assemble`) on **Cloud Run**. Replaces the "no VM" choice in PLAN.md. |
| G5 | Media in **Cloud Storage**. Supabase keeps login and the database (with pgvector and Realtime). |
| G6 | Frontend on **Firebase App Hosting**, in the same project as the backend (the user added Firebase to it). |

G5 changes a fixed decision in `CLAUDE.md` ("Supabase for ... storage"). `CLAUDE.md` is updated in phase 1.

### Proposed here (approve or change)

| # | Proposal | Why | Alternative |
|---|---|---|---|
| D1 | API address: your domain (such as `api.example.com`) if you have one, else `<ip>.sslip.io` for testing | The frontend needs the API on HTTPS. `sslip.io` is a free third-party name service | Buy a domain now |
| D2 | `assemble` accepts calls from the internet **but requires a Google identity**. All 15 functions stay internal | The video function cannot reach an internal-only service without a private route | Private routing for the functions: stricter, more setup. Do this for production |
| D3 | Deploy by hand from this machine first; GitHub automation later | Your role cannot create the GitHub identity link today | Grant `IAM Workload Identity Pool Admin` now |
| D4 | One media bucket, `scenecraft-test-media`, with folders `documents/`, `frames/`, `references/`, `takes/` | Same paths as today, one set of permissions | One bucket per folder |
| D5 | Resource names stay `hiru-staging-*` and `hiru-*` | No code renaming | Rename to `scene-craft` before the first deploy |

## 2. Layout

```
Browser ──> Firebase App Hosting (Next.js) ──> VM e2-small: Caddy (HTTPS) ──> API ──> Supabase (auth, DB)
   │                                                                          │  │          ▲
   └──────────────── files: /files/{ticket} ──────────────────────────────────┘  │          │
                                                       chat functions (3) <──────┤          │
                                       Cloud Tasks <─────────────────────────────┘          │
                                            └──> job functions (12) ────────────────────────┤
                                                      │                                     │
          Cloud Storage (media) <── API, functions, Cloud Run: assemble (ffmpeg) ───────────┘
          Secret Manager · Artifact Registry · Cloud Logging
```

### The VM

| Item | Setting |
|---|---|
| Machine | `e2-small` (2 GB, shared processor), `asia-southeast1` |
| Disk | 30 GB balanced persistent disk, Debian 12, 2 GB swap |
| Network | Static public IP; ports 80 and 443 open; SSH only through Google's identity-aware tunnel (IAP); Private Google Access on |
| Identity | Service account `hiru-staging-api`: queue jobs, call functions and `assemble`, read its secrets, pull images, use the bucket, write logs. No key files |
| Software | Docker Compose: the API container and Caddy (certificates are automatic) |
| Settings | An env file only `root` can read, written at deploy from Secret Manager and §6 |
| File cache | On disk, 5 GB |
| Logs | Docker sends them to Cloud Logging |
| Upkeep | Automatic security updates; containers restart after a reboot; an uptime check on `/healthz` with an email alert |

The VM holds no data of its own. It can be deleted and rebuilt from Terraform and the deploy script.

## 3. What must be fixed first

The Terraform and workflows in the repo have never run. Found on 2026-11-27 by reading them:

| # | Problem | Effect | Fix |
|---|---|---|---|
| F1 | Region is `asia-south1` | Far from the database | `asia-southeast1`, including the state bucket |
| F2 | Terraform and `deploy-api.yml` put the API on Cloud Run | G4 not met | Replace with the VM, network and firewall; add `scripts/deploy_api.ps1`; disable the workflow |
| F3 | Media uses Supabase Storage | G5 not met | Phase 1, §4 |
| F4 | All services are internal-only, and nothing sets up a private route | Calls to chat functions and `assemble` may be refused | D2. The VM should reach internal functions through the project network; **verify in phase 4**. If refused, give the 3 chat functions the D2 setting |
| F5 | File cache defaults to 5 GB; on Cloud Run the disk is memory | Functions and `assemble` can run out of memory | Functions `FILES__CACHE_MAX_GB=0`; `assemble` `ASSEMBLE__CACHE_MAX_MB=256` |
| F6 | The API gets no `OPENAI__API_KEY` | Search silently falls back to keywords | Add it to the API |
| F7 | `GOOGLE__API_KEY` is nowhere in the deployment | No video generation | New secret, for the API and `hiru-video-render` only |
| F8 | Feature switches are not passed | Cloud behaves differently from localhost | One settings list used by API and functions (§6) |
| F9 | `migrate.yml` runs `supabase db push` | Conflicts with the hand-managed database; could replay migrations on it | **Do not run it.** Disable the workflow |
| F10 | `github.tf` needs a permission your role lacks | `terraform apply` fails | Put it behind a variable, off (D3) |
| F11 | Queue sends up to 50 jobs at once, no function limit set | Uncontrolled AI spending, or refused jobs that run out of retries | Queue 10 at once, each function maximum 10 instances |

Not yet verified, checked in phase 1: that the API container starts with all its data files, and that every function starts from its deploy bundle (`hiru-video-render` bundles `hiru_ai` but lists only 3 requirements).

## 4. Moving media to Cloud Storage

**Setting.** `FILES__BACKEND=supabase|gcs` (default `supabase`), `FILES__GCS_BUCKET`, `FILES__READ_FALLBACK=true|false`. Database rows already store a folder name and a path, so **no database change**.

**Places to change**

| Where | What |
|---|---|
| `src/api/repositories/supabase.py` | upload, download, remove |
| `src/api/services/file_cache.py`, `routers/files.py` | download source |
| `src/libs/hiru_ai/adapters/storage.py`, `supabase_rest.py` | the graph engine's file port |
| `src/services/*/…/runtime/rest.py` (11 services) and `doc_ingest/runtime/store.py` | call the one shared module, `hiru_ai/core/media.py` |
| `infra/assemble/app.py` | download and upload; no signed URLs, it downloads within the region |

Forked services record the change in their `UPSTREAM.md`.

**Rules kept**

- Browsers get files only through `/files/{ticket}`. The bucket is private with public access prevention.
- `frames`, `references` and `takes` are written once (`ifGenerationMatch=0`). `documents` still overwrite.
- Thumbnails and posters keep their names.
- Size limits are already checked in code; confirm file types are too, since Supabase buckets enforce both today.

**The shared database matters here.** Localhost and the cloud read the same rows, and a row does not say where its file is. So:

1. Ship the code with the setting on `supabase`.
2. Switch **localhost and cloud** to `gcs` with read fallback on: new files go to the bucket, a missing file is read from Supabase.
3. Copy existing files with `scripts/copy_media.py` (new; safe to repeat; keeps paths and file types). Compare counts and sizes.
4. Turn fallback off. **Supabase files are not deleted** in this plan.

Going back after step 2 needs the new files copied back first.

Localhost needs Google credentials: `gcloud auth application-default login` as `yasiru@calexa.io`. This machine has **one** such credentials file; if PromptMotion or `modenmuse` uses it, keep a separate copy and point Hiru at it with `GOOGLE_APPLICATION_CREDENTIALS`.

## 5. Phases

Each phase ends with a check. Steps marked **[you]** need you; **[approve]** needs a yes before I run it, because it creates or changes something outside this machine.

### Phase 0: Preparation

- [you] Ask the project owner (`scenecrafta@gmail.com`) for a **budget alert** on billing account `014953-…`, and whether it is a free trial.
- [you] Confirm the hosted database is at **schema v30** (`Database/README.md`).
- [you] If you have a domain, say which name the API gets (D1).
- [approve] Install Terraform; sign in for application credentials; `firebase login:use yasiru@calexa.io` in both Hiru folders.

### Phase 1: Code, on localhost only

1. Storage backend (§4) with tests for both backends, no network in tests.
2. Terraform: F1, F2, F5 to F7, F10, F11; the VM (§2); media bucket and permissions.
3. `scripts/deploy_api.ps1`: build the image here, push it, write the env file on the VM, restart, check `/healthz`, return to the previous image if it fails. With it, the VM's Compose and Caddy files.
4. `scripts/deploy_functions.ps1`: the same bundle and function list as `deploy-functions.yml`, plus §6 settings.
5. Disable `deploy-api.yml` and `migrate.yml`. Add `apphosting.yaml` and `firebase.json` to the interface repo.
6. Build and start the API container locally; start each function from its bundle in a clean container.
7. Update `CLAUDE.md`, `README.md`, `.env.example`.

Check: `ruff`, `mypy`, `pytest`, `supabase test db`, `terraform validate` all pass; app works locally with `supabase` storage.

### Phase 2: Cloud foundation

1. [approve] Create the Terraform state bucket.
2. [approve] `terraform plan`, you review it, then `terraform apply`. This creates the VM, so **its cost starts here**.
3. [approve] Load secret values from your `.env` into Secret Manager (never printed, never in Terraform state): Supabase service key, Supabase database URL, OpenAI key, Google key, internal secret, assemble secret.
4. If you use a domain, [you] point it at the VM's IP address.
5. Check Cloud Run limits for the region, and that organization rules allow a public IP.

Check: resources are in Singapore; the bucket is private; the tunnel reaches the VM; port 22 is closed to the internet.

### Phase 3: Frontend trial

Done early because Next.js 16 is only "preview" on App Hosting.

1. [approve] Add Firebase to the project (you may have to accept its terms), create the App Hosting backend, deploy from local source.
2. Check that it builds and starts, the sign-in redirect (`proxy.ts`), sign in and sign out. Pages that read the API are checked in phase 4.

If it fails, the frontend goes on plain Cloud Run with a Dockerfile. Not classic Firebase Hosting in front of it: that strips the sign-in cookies.

### Phase 4: Backend

1. [approve] Deploy `assemble`, then the 15 functions, then the API on the VM.
2. Set the frontend's address in CORS and the invite redirect; set `NEXT_PUBLIC_API_URL` and redeploy the frontend.
3. [you] In Supabase Auth, add `https://<frontend>/auth/accept` to the redirect list. Keep the localhost entry.

Check (free, read only): `/healthz` over HTTPS; signed-out API calls refused; calls to functions without identity refused; **the VM can reach a chat function (F4)**; the API comes back after a VM restart; memory use is comfortable; logs clean.

### Phase 5: Media move

Steps 2 to 4 of §4. [approve] the switch and the copy.

Check: old and new pictures and takes open from localhost and from the cloud; counts match.

### Phase 6: Full check

- [approve] Anything that writes test data to the database, such as an `echo` job or a smoke script.
- [you] Sign in, upload a script, build, plan a scene, paint a frame, generate a video, use each chat. These make **paid** OpenAI and Google calls; I do not run them.
- Results go in `plan/2026-11-27/IMPLEMENTED.md`.

## 6. Settings

Cloud copies what localhost uses today:

| Setting | Value |
|---|---|
| `ENVIRONMENT` | `staging` |
| `LOCAL_FUNCTIONS` | `false` |
| `ADAM_MODE` | `take` |
| `USAGE_DETAIL` | `true` |
| `ZORA__ENABLED` | `true` |
| `OPENAI__IMAGE_QUALITY` | `low` |
| `OPENAI__MODEL_*`, `OPENAI__EFFORT_*` | as in `.env` |
| `AI_ENGINE` | not set (`legacy`), except `graph` for `hiru-shot-producer` and `hiru-frame-render`, as on localhost |
| `LIVE__TRANSPORT` | `poll` |
| `VIDEO__FAKE_PROVIDER` | `false` |
| Sable, reader, breakdown | off |

Langfuse tracing stays off in the cloud unless you want it.

## 7. Cost

| Item | Estimate per month |
|---|---|
| VM `e2-small`, always on | US$15.09 |
| Its disk and public IP address | about US$7 |
| **API total** | **about US$22** |
| Frontend, functions, queue, `assemble` at test volume | small, paid by use |
| Storage | small, grows with takes |
| OpenAI and Google AI calls | billed separately, likely the largest part |

The machine price is from [gcloud-compute.com](https://gcloud-compute.com/asia-southeast1/e2-micro.html) (third party, dated 2026-11-22). Disk and IP are unconfirmed. Check with the [Google pricing calculator](https://cloud.google.com/products/calculator) before relying on them.

## 8. Risks

| Risk | Handling |
|---|---|
| Test and localhost share one database | Test data mixes with development data. Keep both on the same code version and storage setting |
| 2 GB and a shared processor may be tight | Swap, memory check in phase 4. Moving to `e2-medium` is a restart (about US$15 more) |
| One machine | The API is down for a short time on deploys and reboots. Acceptable for testing |
| `sslip.io` is outside our control; certificates for it may be rate limited | Use a domain if either causes trouble |
| Next.js 16 on App Hosting | Phase 3 trial, Cloud Run fallback |
| New project has low limits | Check in phase 2; ask for more if needed |
| No budget alert yet | Phase 0, before anything is created |

## 9. Left for production

New Supabase project in Singapore, private networking for all services, a larger or second API machine behind a load balancer, GitHub deploys, own domain, backups and monitoring alerts.
