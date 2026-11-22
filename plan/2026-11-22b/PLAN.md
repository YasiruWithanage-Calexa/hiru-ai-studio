# Files on Google Cloud Storage, everything else stays on Supabase (plan/2026-11-22b)

Revision 1 (2026-11-22). Agreed with the person in chat on 2026-11-22 ("option C"). Plan only: nothing built.
Builds on plan/2026-11-21 (Storage egress: `CachedFiles`, the shared cache folder, assemble Range reads, `/inspect`) and
plan/2026-11-08c (write-once media paths, thumbnails, `/files/{ticket}`).

Why: every stored file now crosses the internet twice, Supabase → Cloud Run (Supabase egress) → browser (Google
egress). With the files in a GCS bucket in **asia-south1**, the region Cloud Run already runs in, the first hop is free.
The Free plan's 1 GB of file storage and 5 GB of egress were already being reached on ~1 GB stored (plan/2026-11-21 §1).
Without files, Supabase holds only text, vectors and auth, so the Pro plan ($25) covers it for a long time.

Estimated monthly cost (chat, 2026-11-22, list prices, to re-check): Pilot ~$28 (Pro $25 + GCS ~$3), Growing ~$48,
Busy ~$167 against ~$560 with files on Supabase. GCS Standard asia-south1 is $0.0253 per GB a month; reads from Cloud Run
in the same region cost nothing.

## 0. Rules for the chat that builds this

- **Stays on Supabase:** Postgres (every table, pgvector, RLS, `auth.uid()`), Auth (login, invites, JWKS), Realtime
  (`api/live/hub.py`), PostgREST. Only the four buckets move: `documents`, `frames`, `references`, `takes`.
- **Paths do not change.** Every `storage_path`, `text_path`, `reading_path`, `last_frame_path`, `poster_path`, sheet
  path and thumbnail path in the database stays byte for byte the same. No schema change, no backfill of rows.
- **Write-once stays the safety argument** (`IMMUTABLE_BUCKETS`): a media path names one file forever. On GCS this is
  `ifGenerationMatch=0` (a second write answers 412). `documents` still overwrite.
- **Browsers never reach GCS.** Files still go through `/files/{ticket}`. No signed URLs to browsers, no public bucket,
  no CORS. The ticket key stays derived from the Supabase service-role key (`api/services/media_links.py`).
- **No paid call** (model, image, video) without the person's yes, each time. Tests run with `OPENAI__API_KEY=` blank and
  never touch the network: a fake GCS in tests, as today's fake storage.
- **The builder applies nothing to cloud resources**: no `terraform apply`, no bucket creation, no copy `--apply`, no
  deleting Supabase objects, no plan upgrade. Those are the person's (phases 5, 7, 9, 10).
- **Both trees may have uncommitted work.** Read `git diff` of a file before editing it. Never stash; use a worktree.
- **Only Shot Planner Raphael stays.** Do not port the retired services (Adam, David, Jonathan, DaVinci, director_chat);
  leave their storage code as it is and ignore their test failures.
- **No enable switch.** GCS is used when `GCS__BUCKET` is set; empty means Supabase Storage exactly as today (local
  tests, and the fallback while copying). That is configuration of where files live, not a feature flag.

## 1. What uses Supabase Storage today (read 2026-11-22; re-check in phase 0)

| # | Where | What it does |
|---|---|---|
| S1 | `libs/hiru_ai/adapters/storage.py` `SupabaseFiles` | The `Files` port (`core/ports.py:299`): download, upload (+ thumbnail), retries, write-once `x-upsert`, `already_exists` |
| S2 | `libs/hiru_ai/adapters/supabase_rest.py:812-816` | Builds `CachedFiles(SupabaseFiles(rest))` for the graph engine |
| S3 | `api/repositories/supabase.py:392-408` | API storage: `upload`, `remove`, `download` through supabase-py (`documents.py`, `handoff.py:229/392`, `media_thumbs.py`) |
| S4 | `api/services/file_cache.py:155` | The API disk cache downloads from `/storage/v1/object/...` |
| S5 | `api/routers/files.py:69` `_stream_through` | Range-forwarding stream for files too big for the cache |
| S6 | `infra/assemble/app.py:110-150` | `_storage`, `_download`, `_signed_url` (Supabase `/object/sign`, 300 s) for ffmpeg Range reads; uploads cuts to `takes` |
| S7 | Each service's `runtime/rest.py` or `runtime/store.py` | Own copy of download/upload. Live: `frame_render`, `video_render`, `doc_ingest`, `script_split`, `structure_build`, `canon_extract`, `shot_producer`, `shot_planner_raphael` (confirm zora_chat / sable_chat in phase 0) |
| S8 | `scripts/_common.py`, `scripts/camera_live.py`, `scripts/backfill_thumbs.py`; `lab/*/fetch.py`, `lab/timecodes/run.py` | Read files directly |
| S9 | `Database/schema_v28.sql:1448-1460` | Bucket rules: private, size limits (documents 25 MB, frames/references 15 MB, takes 30 MB), allowed mime types |
| S10 | Interface repo | **Nothing.** Supabase there is auth only (`lib/supabase/*`, `proxy.ts`, login); media comes from `/files/{ticket}` through `<Media>` |

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **One GCS bucket per environment** (`<project_id>-hiru-files`, asia-south1, Standard, uniform bucket-level access, public access prevention enforced). Object name = `<supabase bucket>/<path>`, e.g. `takes/abc/1.mp4` | One IAM binding, one place to watch; the four buckets become prefixes, so paths in rows are unchanged |
| D2 | **Talk to GCS with httpx + `google-auth` tokens** (JSON API: `GET .../o/{name}?alt=media`, `POST upload/... uploadType=media&ifGenerationMatch=0`, `DELETE`), not `google-cloud-storage` | Same client, retries, streaming and Range code as today; one small dependency; works in the async API and the sync workers alike |
| D3 | **`GcsFiles` beside `SupabaseFiles`** behind the same `Files` port, with the same retries, thumbnail write, and write-once rule. A 412 on our own retry counts as success (today's `already_exists`) | The callers do not change; `CachedFiles` wraps it unchanged |
| D4 | **A small shared GCS client** in `libs` (token, URLs, download, upload, delete, ranged stream). The API, the services and assemble import it instead of each keeping a copy. Where a service is packaged alone (`runtime/rest.py`), it gets a copy of the same file, kept identical by a test that compares them | Cuts the 8+ copies of storage code to one source of truth |
| D5 | **Bucket rules move into code** (S9): `core/file_store.py` keeps `BUCKET_RULES` (max bytes, allowed mime) and every upload checks them before writing. The Supabase bucket rows stay as they are | GCS has no per-prefix mime or size limit |
| D6 | **Reads fall back to Supabase while copying.** With `GCS__BUCKET` set and `GCS__FALLBACK_SUPABASE=true`, a GCS 404 reads from Supabase and, for write-once buckets, writes the file to GCS (copy on read). Writes go only to GCS. The fallback is removed from config after the copy is verified (phase 9) | No downtime, no window where a file is missing |
| D7 | **Assemble reads GCS with a bearer header**, not a signed URL: ffmpeg `-headers "Authorization: Bearer <token>"` on `https://storage.googleapis.com/<bucket>/<object>`. The token comes from the metadata server and lives about an hour. Falls back to a whole download as today | No `signBlob` permission, no capability URL that could leak |
| D8 | **Identity: the service accounts, no keys.** API, functions and assemble get `roles/storage.objectAdmin` on this bucket only. Local machines use `gcloud auth application-default login` against the dev bucket | Nothing secret to store or rotate |
| D9 | **Copy is a script, not rclone**: `scripts/copy_files_to_gcs.py` lists `storage.objects` (read-only SQL through the service role), copies each missing object (same name, same content type), and checks size + MD5. Dry run by default (counts, MB, what is missing); `--apply` copies. Safe to re-run | Our usual pattern; no S3 keys to create on Supabase; doubles as the verifier |
| D10 | **Supabase objects are kept 30 days after cut-over**, then deleted by the person (`scripts/copy_files_to_gcs.py --purge-supabase`, dry run first) | A way back while the move proves itself; then the space is free |
| D11 | **GCS soft delete left at the default 7 days**; versioning off; no lifecycle rule yet | Cheap protection against a wrong delete; write-once makes versions unneeded |
| D12 | **A GCP budget alert** on the project (the person sets the amount) | The point of the move is cost; it should be watched |

## 3. Settings

```
GCS__BUCKET=                    # empty = Supabase Storage as today
GCS__FALLBACK_SUPABASE=false    # true only while copying (phases 6-9)
```

Read by the API, every live service, assemble and the scripts. Terraform sets them on Cloud Run. `.env.example` explains
both. `FILES__CACHE_*` unchanged.

## 4. Phases

| # | What | Done when |
|---|---|---|
| 0 | Read-only: confirm S1-S10 (every `/storage/v1`, `.storage.from_`, `SupabaseFiles`, `_signed_url` in `src`, `infra`, `scripts`, `lab`); which services are live; measure stored GB per bucket (`select bucket_id, count(*), sum((metadata->>'size')::bigint) from storage.objects group by 1`) and the last month's egress (dashboard, the person) | A list and the numbers in IMPLEMENTED.md |
| 1 | Shared GCS client (D2, D4) + `BUCKET_RULES` (D5) + fake GCS for tests | Unit tests: download, ranged read, upload with `ifGenerationMatch=0`, 412 on retry = success, 412 on first write = error, 404, 5xx retried, 4xx not, delete, rules refuse a wrong mime or size |
| 2 | `GcsFiles` (D3) and the fallback wrapper (D6); `supabase_rest.py:812` picks GCS when `GCS__BUCKET` is set | Tests: `CachedFiles(GcsFiles)` passes the existing file-store tests; fallback reads Supabase on a GCS 404 and copies write-once files once; `documents` never copied on read |
| 3 | The API (S3, S4, S5): repository storage, disk cache download, `_stream_through` with Range, document remove, take upload, zip download, thumbnails | Existing API tests green against the fake GCS; a Range request returns 206 with the right bytes |
| 4 | Services (S7), assemble (S6, D7), scripts and labs (S8) | `grep -rn "/storage/v1" src infra scripts` finds only the Supabase adapter kept for the fallback; the identity test of copied client files passes; assemble Range test (`tests/infra/test_assemble_range.py`) passes on GCS |
| 5 | **The person**: Terraform (bucket, IAM per D8, env vars), `terraform plan` read, then `apply`; budget alert (D12) | Bucket exists, private; each service account can read and write it, nothing else can |
| 6 | Deploy with `GCS__BUCKET` set and `GCS__FALLBACK_SUPABASE=true`, dev first | A new frame, take and document land in GCS; an old one still opens in the browser |
| 7 | **The person**: `scripts/copy_files_to_gcs.py` dry run, then `--apply` (dev, then prod) | Dry run on re-run says 0 missing, MD5 all match |
| 8 | Check: for every path in the database rows (frames, takes, sheets, documents, posters, thumbnails) the object exists in GCS; open a scene's board, frames, takes and a document in the browser; render one frame and one take only with the person's yes | A script report of 0 missing; screens look as before |
| 9 | `GCS__FALLBACK_SUPABASE=false` on every service; a week of logs shows no 404 from GCS | Supabase Storage egress in the dashboard drops to about zero |
| 10 | **The person**, 30 days later (D10): purge Supabase objects (dry run, then apply). Upgrade to Pro whenever they choose; it does not depend on this plan | Supabase storage usage near zero |
| 11 | Docs: `docs/ARCHITECTURE.md` (where files live), `Database/README.md` (buckets are prefixes in GCS, rules in code), `.env.example`, `infra/assemble/README.md`, deployment note on ADC for local machines | Reviewed by the person |

Interface: no change. `<Media>`, `thumbSrc` and `/files/{ticket}` stay as they are.

## 5. How we know it worked

- Supabase Usage: storage egress near zero; file storage near zero after phase 10.
- GCS: stored GB matches phase 0's measure plus new work; the bill shows storage and operations, no network charge
  between GCS and Cloud Run.
- The job-end log line from plan/2026-11-21 (`storage: n from …`) names GCS, and its counts do not rise.
- Nothing visible changed for a person using the app.

## 6. Risks

| Risk | Answer |
|---|---|
| A row points at a file that never got copied | Fallback stays on until phase 8's check reports 0 missing |
| A second write to a media path (a bug) silently replaces a file | `ifGenerationMatch=0` refuses it, as `x-upsert: false` does today |
| A local machine without Google credentials | Clear error naming `gcloud auth application-default login`; tests need none |
| Bucket made public by mistake | Public access prevention enforced in Terraform |
| Cost surprise | Budget alert (D12); reads from Cloud Run are same-region and free |
