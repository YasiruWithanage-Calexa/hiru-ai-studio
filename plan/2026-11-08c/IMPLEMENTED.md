# Quiet by default: what was built (phases 0, 1, 2 in part, 3, 4, 5), 2026-11-08

Built offline, uncommitted, in both repos. No model call, no Supabase call, nothing deployed. Tests run on fakes.

## Phase 1: files cross the internet once (this repo)

| Step | Where | Notes |
|---|---|---|
| 1a same file, same hour, same URL | `src/api/services/media_links.py` | Nonce is `HMAC(key, plaintext)[:12]`; `e` is the end of the current hour, or of the next if under 10 min remain. `seconds_left()`, `key()` and `thumb_url()` added. |
| 1b disk cache | `src/api/services/file_cache.py`, `routers/files.py` | Hashed file names (`<dir>/<bucket>/<aa>/<sha256>.<ext>`), single flight, LRU trim, `.part` + rename, content type sidecar. `FileResponse` gives Range/206. A file bigger than the cap, or `FILES__CACHE_MAX_GB=0`, streams through as before. `repos.storage.remove` evicts the copy. |
| 1c thumbnails | `hiru_ai/core/thumbs.py`, `adapters/storage.py`, `frame_render/runtime/{thumbs,store}.py`, `api/services/media_thumbs.py` | 640 px WebP q75 beside every frame / reference / look sheet (`<path>.thumb.webp`). Views carry `thumb_url` + `file_key`. Takes: `<take>.poster.webp` via the new `assemble /poster`, made on person uploads. Pillow added to `pyproject.toml` and the frame_render requirements. |
| 1d never overwrite | `adapters/storage.py`, both services' `runtime/rest.py` | `x-upsert: false` for `frames`, `references`, `takes`. Our own retry seeing "already exists" counts as success. Documents still upsert. |
| backfill | `scripts/backfill_thumbs.py` | Counts by default; `--apply` downloads each missing picture once; `--posters` for takes. |

Tests: `tests/api/test_jobs_and_files.py` (tickets, cache, Range, single flight, LRU, off-switch, header safety),
`tests/api/test_thumbs.py`, `tests/hiru_ai/test_adapters.py`, `tests/services/frame_render/test_upload_once.py`.

## Phase 2: one copy of the data in the browser (interface repo)

2a done (`@tanstack/react-query`, `lib/query/{keys,query-provider}`, mounted in `app/(studio)/layout.tsx`).
2b/2c/2d done for the **shot workspace** (the page with the storm): `getSceneRaw` -> `ShotWorkspace initial` ->
`useSceneData`; camera / accept / reject / upload put the API's answer in the cache; jobs read the production view once
and then the query polls itself only while a frame paints; the filmstrip and both chats no longer call
`router.refresh()`. 2e/2f done (`lib/media/{links,media}`, `file_key`, `thumb_url`, `poster_url`, `preload="none"`;
`MediaCacheProvider` removed; the canon `<img>`s are `<Media>`).

Guards: ESLint bans `router.refresh()`, `setInterval` and plain `<img>`/`<video>` in `features/**`; the request budget
is `shot-workspace.test.tsx` (idle 5 min = 0 requests; a camera edit = 1; a job = write + 2 production reads + the job
status; polling stops when nothing paints).

## Phase 5: stuck jobs end (this repo)

`src/api/workers/sweeper.py`, started in the API's lifespan, once a minute (`sweep(repos, now)` is the testable pass).
A job still `pending`/`running` whose row and `job_events` have been quiet past its limit is marked `failed` with
"Stopped: no progress for N minutes." Limits (D6): frame_render 10, video_render 30, doc_ingest 20, any other job 15.
The frames and renders of a job just failed end with it; any frame or render quiet past its own limit, and any document
stuck `processing` past 20 minutes, ends too. `waiting_input` is never swept. New repo reads: `active_before` (jobs,
frames, renders), `last_event_at`, `processing_before`. Tests: `tests/api/test_sweeper.py`.

## Phase 3: one status read while work runs

**API.** `GET /v1/productions/{id}/live?since=` (`routers/live.py`) answers `{busy, version, items}`. The plan called
the route `/activity`, which is already the audit log, so it is `/live`. It makes **four** column-limited queries
(frames, renders, documents, jobs; one per table, run together), not two: PostgREST cannot union tables and a database
function would be a schema change. Items are the ones still active plus any that changed after `since`. It is
production-wide (no `scene_id`; items carry `shot_id`). Mints no ticket. Tests: `tests/api/test_live.py`.

**Interface.** `src/lib/activity/` is the one poll: `store.ts` (a plain module: kick, 3 s while busy, stops when idle,
pauses in a hidden tab, backs off, gives up after 8 errors), `provider.tsx` (`ActivityProvider` in
`(studio)/layout.tsx` names the production from the URL; a settled item invalidates only its own queries;
`useOnActivity(active, match, run)` for screens), `wait-for-job.ts`. `waitForJob` now rides it: one read of the job at
the start and one at the end, no timer. Removed: `fetchFrameProgress`, `fetchRenderProgress`, the scene production
query's `refetchInterval`, the `useLiveRefresh` uses in Production and Takes, the documents panel's and the video
card's own `usePoll`. Tests: `store.test.ts`, `wait-for-job.test.ts`, and the rewritten budget test in
`shot-workspace.test.tsx` (a painting frame = a 3 s status question, ONE production read when it lands, then silence).

Kept on purpose: `build-refresher` and `start-build-dialog` still poll `fetchBuildProgress` (events and messages of one
build job; `/live` carries job status only), so `use-live-refresh.ts` stays for them.

## Phase 4: lean reads (this repo)

- `resolve_access` is kept 15 s per (database, production, person), cleared by `authz.forget_access()` in the member,
  role and production write routes. A missing production or role is never kept.
- `canon.list` and `looks.list_for_production` are kept 30 s per production (deep copies out), cleared by the repo's own
  writes and by `api.cache.job_ended()`, which `GET /v1/jobs/{id}` (terminal) and `/live` (anything settled) call, since
  workers write cards and sheets from other processes.
- The hot prompt read lists its columns (no `ir`). The other hot tables stay on `select("*")`: every column of frames,
  takes, renders and shots is used by a view, so dropping any would be a guess.
- `GET .../scenes/{id}/page` returns scene, production view, episode, access, threads and the main chat in one request
  (`routers/page.py`, calling the functions the five routes call; a test checks it equals them). The interface's
  `getSceneRaw` uses it: the shot page's first read is **1** call, not 5.
- Tests: `tests/api/test_lean_reads.py`, `tests/api/test_page.py`.

## Phase 0: measure (this repo)

`DEBUG_TRAFFIC=true` (local/test only): `api/traffic.py` logs one line per route per minute (calls, queries, bytes, and
`/files` hits vs misses vs bytes from Supabase), warns on a route over 60 calls/min or one file fetched from Supabase
more than twice in an hour, and serves a JSON snapshot at `GET /debug/traffic`. `scripts/traffic_scene.py` opens a shot
page twice, edits the camera, idles, and writes `plan/2026-11-08c/baseline.json`. **It has not been run** (it needs the
running API, a sign-in and a real shot). Its job step (`--with-job`) calls the image model and costs money: there is no
fake image provider for frames, so it is off by default and needs the person's yes. Tests: `tests/api/test_traffic.py`.

### Not done (named so it is not forgotten)

- Phase 2 for every screen the server still draws: **25 files** still call `useRefreshPage()` (Director panel: script
  editor, scene card, shot list, Adam/David/Jonathan/Raphael panels; Production and Handoff pages; canon dialogs; prices;
  template; questions; build; Sable). A click there draws the page again; for a scene page that is now one `/page` call
  plus the shell reads, not five. Each is one screen to move onto a query like `features/scenes/queries.ts`.
- Job routes still answer `{job_id}`, not `{job_id, view}`; the client reads the production view once instead.
- The request-budget tests exist for the shot workspace only, not for the Director page.
- Two guards of section 5 are not written as asked: "activity makes at most 2 queries" is `test_live.py` (one per table,
  four tables); "write routes return data" needs the list of routes of 2c, which is not made.
- Generated takes get no `.poster.webp` until the video worker can call assemble (or `backfill_thumbs.py --posters`).
- Hashed requirements lock (`requirements/hiru_ai_openai.txt`) not re-resolved for Pillow.
- `tests/adam/test_removal.py` fails on `Database/schema_v19.sql` (Raphael's, not this plan's).
