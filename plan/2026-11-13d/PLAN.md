# Pushed, not polled: status by stream and one read per change (plan/2026-11-13d)

Revision 1 (2026-11-13). Nothing in this plan is built. Repos: this one (API, functions) and `hiru-ai-studio-interface`.
It continues plan/2026-11-08c ("quiet by default": one status poll, files cached) and plan/2026-11-13b ("one read per
row": no repeated query inside a request). Those plans made each read cheaper; this one removes most reads altogether:
the browser stops asking "has anything changed?" every few seconds and is told instead, and a change costs one small
read or none. Build **one phase at a time**, measure after each (section 6), write `IMPLEMENTED.md` here as phases land.

Every phase is offline ($0): no model call, no image, no video. Nothing is deployed until the person says so.

## 0. Rules for the chat that builds this (read before anything)

- **Two repos.** Backend `D:\projects\Hiru AI Studio\source\hiru-ai-studio` (Python 3.12: always `.venv/Scripts/python.exe`).
  Interface `...\hiru-ai-studio-interface` (Next.js 16; its `CLAUDE.md` and `AGENTS.md` are binding: no costs in the UI,
  TanStack Query cache, no `router.refresh()` for data the client can hold, shadcn/ui, no raw hex).
- **No model call, image or video, ever, in this plan.** The structure build used for measuring runs with
  `OPENAI__API_KEY=` blank (absent-safe: the rules path), so it is free.
- **The hosted project is the one dev database.** Measuring writes dummy rows to it (section 6): ask the person before the
  first run of each session. No SQL against it; a schema change goes into the next version pair (`Database/schema_v25.sql`,
  `upgrade_v24_to_v25.sql`) and a migration, and the person applies it.
- **Read plan/2026-11-13b first** (its `IMPLEMENTED.md`): its memo, its `/page` extras, its `/render-plans` and its
  phase 6 (`/cost`) are the ground this plan stands on. Do not redo its phases here; section 5 names where this plan
  depends on one.
- **Baseline before any change:** `ADAM_MODE=staged OPENAI__API_KEY= .venv/Scripts/python.exe -m pytest -q -p no:logging`
  and the interface's `npm run test`; report only failures that are new.
- **Commit only when the person asks.**
- Checks before finishing a phase (backend): `ruff check src tests scripts`, `mypy`, `pytest -q`, and when the schema
  changes `npx supabase test db` + `npx supabase db advisors --local --level warn` (CLAUDE.md "Conventions").
  Interface: `npm run lint`, `npm run typecheck`, `npm run test`.

## 1. Why

On 2026-11-13 the person created a production, uploaded a script and started the structure build with the API log on.
The log (kept in the chat that wrote this plan) showed:

| Stretch | Time | API requests | DB queries |
|---|---|---:|---:|
| Productions page | 7 s | **~75** | ~110 |
| Create production + upload | 1 s | 4 | 8 |
| Landing on the new production | 0.3 s | 10 | 16 |
| Reading the uploaded document | ~10 s | ~17 | ~25 |
| Structure build | 28 s (and on, while it runs) | ~32 | **~110** |

and, on a scene page opened before: `/page` 23 queries, `/cost` 20, `/render-plans` 11 and `/handoff` 11 on every shot
selected, two reads of the scene (20 queries) after every Zora turn.

The writes in the same stretch were small: a few dozen `job_events` rows and a handful of status changes. **The cost is
reads**: the same unchanged state read again every 2.5 to 3 seconds, by more than one loop, and a full server page
re-read whenever any of it moved.

### 1.1 Every poller in the interface today

| | Poller | Where | Every | Reads | Runs while |
|---|---|---|---|---|---|
| A | The shared status loop | `src/lib/activity/store.ts` | 3 s (backs off to 24 s on errors) | `GET /live?since=`: 4 queries | something of the open production is queued or running; tab visible |
| B | The build page | `src/features/build/components/build-refresher.tsx` via `src/lib/poll/use-live-refresh.ts` | 3 s | `GET /build`: 6-7 queries, growing | the build runs; any change calls `router.refresh()` |
| C | The start-build dialog | `src/features/build/components/start-build-dialog.tsx:101` | 2.5 s | `GET /documents`: 1 query | the dialog is open and a document is being read |
| D | `waitForJob` | `src/lib/activity/wait-for-job.ts` | rides A (3 s alone when no production is open) | `GET /v1/jobs/{id}` once at start and once at the end | a caller waits on a job |

The 1-second timers in `chat-thread.tsx` and `last-activity.tsx` are display clocks; they make no request.

A is well built (one loop, `since`, no overlap, stops when idle, sleeps in a hidden tab). It stays, and becomes the
only status source (phase 2) and then the fallback behind the stream (phase 5).

### 1.2 Findings

| # | Finding | Evidence | Phase |
|---|---|---|---|
| F1 | **The productions page renders itself in a loop**, about 4 server renders a second, each `/productions` + `/me` + `/usage` | log 14:28:57-14:29:04: ~25 cycles, no `OPTIONS` (so server renders, not browser polls); stopped only when the API stopped. Not seen at 14:33 | 1 |
| F2 | **Two loops watch one document's status**: A (`/live`) and C (`/documents`) | log 14:38:07-14:38:14; `/documents` twice within 0.6 s at 14:38:13 | 2 |
| F3 | **A build change costs four requests**: B's `/build`, then `router.refresh()` re-renders the page, which reads `/build`, `/overview` and `/questions` again; B's first read repeats the server's `/build` from 250 ms before | log 14:38:24, :28, :46 | 2 |
| F4 | **`/build` reads far more than a poll needs**: the latest build job (twice), all open questions, every episode, scene and shot of the production, its documents, and **every event of the job from the start** | `routers/build.py:180-183`, `_summary` at `:148-158`; `jobs.events(after_seq=0)` | 3 |
| F5 | **A and B poll the same build at once** (the build's job is active in `/live` too) | the two loops interleave in the log | 2 |
| F6 | **Every browser GET is preceded by an `OPTIONS` preflight**, doubling round trips. Starlette caches preflights 600 s by default, so a normal browser should not repeat them: most likely DevTools "Disable cache" was on | every client poll line in the log | 0 (verify), 1 (fix if real) |
| F7 | **`/live` is four queries** (frames, renders, documents, jobs) on every tick | `routers/live.py:56-58` | 3 |
| F8 | **The header reads `/usage` on every navigation** (1-2 queries, 60-480 ms) for a percentage that barely moves | every page in the log | 4 |
| F9 | **Landing on a production fires 9 GETs at once**, several for things a new production does not have yet (`/director-board`, `/director-personas`, `/sable`) | log 14:38:04 | 4 |
| F10 | **After a Zora turn the page reads the scene twice** (`/scenes/{id}` 11 + `/scenes/{id}/production` 9) | log 14:35:22 | 4 |
| F11 | **Selecting a shot reads `/render-plans` and `/handoff` (11 + 11)**, both loading the same shot | log 14:33:33, 14:36:25 | 4 |
| F12 | **`/packet` answers 404 on every scene open** when the scene has no breakdown (3 queries for nothing) | log 14:33:26 | 4 |
| F13 | **`/page` measured 23 queries**, where plan 13b phase 3 measured 14.7: a regression, a memo that was off, or the replaced database | log 14:33:27 | 0 (find out) |
| F14 | **`/cost` is 20 queries** | log 14:33:33 | plan 13b phase 6 (not here) |

## 2. The target

```
 worker writes a row ──► Postgres ──► Realtime (server side) ──► API hub ──► SSE stream ──► the browser's activity store
   (as today)                         service key, rows never      one per       small messages:      updates the TanStack
                                      reach a browser              instance      kind, id, status,    cache; reads ONE item's
                                                                                 new events           view only when it must
```

1. **One status source.** Everything the browser waits for (documents, the build, canon refine, every shot planner, the
   shot producer, frames, takes, the sweeper's failures, the director board, other people's chat messages) reaches the
   page through the activity store. No screen runs its own timer.
2. **A change carries itself.** A status message says what changed (a frame's new status, the build's new events after
   the last `seq`, "the scene's shots changed"). The interface writes it into the TanStack cache. A full read happens on
   first load and after a reconnect, never on a timer.
3. **Push, with polling as the fallback.** The API serves one Server-Sent Events stream per production on screen, open
   only while something is queued or running. The poll (A) stays behind one switch for when the stream cannot connect.
4. **The API decides what reaches a browser.** The API subscribes to Supabase Realtime with the service key; the browser
   never subscribes to tables and never sees a row, only the same small shape `/live` returns today.
5. **The database stays the truth.** Milestones (started, stage done, a frame or take done or failed, a question, the
   result) are rows, then pushed. Nothing important lives only in a cache: the sweeper, a re-delivered job and a
   reconnecting tab all read rows.

### 2.1 What is pushed, per kind of work

| Work | Started from | Rows that change | The message |
|---|---|---|---|
| Document upload and reading | upload, start-build dialog | `documents`, `jobs` | document id, status |
| Structure build (breakdown) | build page | `jobs`, `job_events`, `questions` | job status, new events after `seq`, "questions changed" |
| Canon refine | canon page | `jobs`, `job_events`, `canon_entities` | job status, "canon changed" |
| Shot planners (classic, Adam, David, Jonathan, Raphael) | scene page | `jobs`, `job_events`, `shots`, `scenes` | job status, "scene X's shots changed" |
| Shot producer, prompts | production panel | `jobs`, `video_prompts` | prompt id, shot id, status |
| First frames | production panel, workspace | `first_frames` | frame id, shot id, status |
| Video takes (Omni, Veo) | Generate Video card | `video_renders`, `takes` | render id, shot id, status; "take added to shot X" |
| Stuck work stopped by the sweeper | the sweeper | the same rows, to `failed` | the same messages, status `failed` |
| Board, other people's chat messages | scene page | `production_director_board`, `chat_messages` | "board changed", "thread X changed" |

Every table here is already in the `supabase_realtime` publication (`Database/schema_v24.sql:1353-1361`, `:1565`).
`job_events` has no `production_id`; the hub knows a job's production from the `jobs` row it saw first, and looks the
job up once (cached) when it did not.

Chat replies (Zora, Sable, the director chat) keep their own stream in the request that asked; the shared stream only
tells other tabs a thread or a plan changed.

## 3. Rules that do not change

- No cost, credit, model name, tier, tool id, prompt or storage path reaches a browser. A stream message is ids,
  statuses, timestamps, `seq` numbers and the build's own event text that `/build` already shows, nothing else.
- `Permission.VIEW` guards the stream; a production the caller cannot see is 404 (no stream opened, no hint it exists).
  Roles are read from the database when the stream opens and again on every reconnect.
- RLS is unchanged: read-only for browser roles. The browser opens no Realtime channel.
- Files: a message never carries a URL. The interface reads the one item's view (which mints its `/files` ticket) when it
  needs to draw it.
- Workers are idempotent per `job_id`, mark a failed job failed, and keep touching their row or writing `job_events`;
  the sweeper's limits (frame 10 min, take 30, document 20, other jobs 15; `waiting_input` never swept) stay.
- A write route returns the updated view.
- Boundaries (`tests/test_isolation.py`): the hub lives in `api/`; functions import nothing new; `contracts` gains only
  pydantic shapes (the message), no I/O.
- Tests never touch the network: the Realtime client is replaced by a fake in tests, as the OpenAI clients are.

## 4. Expected result

| Moment | Today | After phases 1-4 (poll) | After phase 5 (stream) |
|---|---|---|---|
| A build running, per 3 s | 1-2 requests + 4 on each change; 10-25 queries | 1 request; 1-2 queries | 0 requests; 0 queries (a message per change) |
| Reading a document | `/live` + `/documents` (+ 2 preflights) every ~3 s | `/live` only | nothing between changes |
| A frame or take running | `/live` every 3 s (4 queries) | `/live` every 3 s (1 query) | nothing between changes |
| The change itself | `router.refresh()`: 3 requests, ~12 queries | 0-1 small read | 0-1 small read |
| Productions page | the loop: ~75 requests in 7 s | 3 requests, once | same |
| Every navigation | `/usage` 1-2 queries | cached 60 s | same |
| Selecting a shot | 22 queries | ~12 | same |
| After a Zora turn | 20 queries | 0 | same |

These are targets; the phase reports in `IMPLEMENTED.md` record what was measured.

## 5. Phases

### Phase 0: measure first, reproduce F1, settle F6 and F13 (no product change)

1. **A creation walk** beside plan 13b's scene walk: extend `plan/2026-11-13b/measure/walk.js` (or add
   `plan/2026-11-13d/measure/create.js` using the same trace and `analyze.py`) to: open the productions page, create a
   production, upload a small seeded script, wait for it to be read, start the build, watch the build page until it
   settles, open one scene and one shot. Functions run locally with `OPENAI__API_KEY=` blank (the rules path, $0).
   Record per stretch: API requests, DB queries, `OPTIONS` count, bytes. This is the baseline for every later phase.
2. **Reproduce F1.** Open `/productions` with the API stopped; start the API; watch the API log. Then the same with the
   API up from the start, and after an HMR edit. Find what re-renders the page (an error boundary's retry, a
   `router.refresh()` from a mounted component, the dev overlay) and write the cause in `IMPLEMENTED.md`. Check
   `next build && next start` too: a loop that happens only in dev is still fixed (people develop on it), but the
   report says so.
3. **Settle F6.** Repeat a poll with DevTools closed (or "Disable cache" off). If preflights stop, F6 is not a product
   problem and phase 1 skips it; if they repeat, phase 1 fixes it.
4. **Settle F13.** Trace one `/page` call: is the 13b memo on (`RequestLogMiddleware` opens it), and which queries
   repeat or are new? Record the answer; a regression is fixed in phase 4, a data difference is just noted.
5. **Count the writes** of one rules-path build, one document read, and (with the fake engines) one frame and one
   render: `job_events` rows, `updated_at` touches, status changes. Phase 6 uses these numbers.

### Phase 1: the bugs (interface, small API)

1. Stop the productions page loop (F1) at its cause from phase 0. Add a test that renders the page with a failing then
   recovering API and counts the server reads.
2. F6, only if phase 0 proved it real: set `max_age` explicitly on `CORSMiddleware` (`api/main.py:100`; browsers cap it
   at 2 h) or, the person's choice (D5), send the browser's API calls through a same-origin Next rewrite so there is no
   preflight at all.
3. Measure; record.

### Phase 2: one status source (interface, small API)

1. **The build in `/live`.** `/live` gains the build's progress: when the production's latest `structure_build` job is in
   the window, its item carries `seq` (its last event number) next to its status. No new route.
2. **The build page reads through the cache.** `BuildRefresher` and `useLiveRefresh` go: the build page draws from a
   TanStack query (`queryKeys.build(productionId)`) seeded by the server render. When the activity store reports a new
   `seq`, the page asks `GET /build/events?after_seq=N` (phase 3 builds it; until then the full `/build`) and appends.
   A new stage or a finished build invalidates only `/overview`; a question event invalidates only `/questions`.
   No `router.refresh()` on this page.
3. **The start-build dialog listens to the activity store** (`useOnActivity` for `document` items) and updates its
   document list from the message; it reads `/documents` once on open and once when a document reaches `ready` or
   `failed` (its role and page count come with that read). Poller C goes.
4. `waitForJob` is unchanged (it already rides A).
5. Tests: the store emits a `seq` change; the build page appends without a refresh; the dialog does not poll.
   Measure; record.

### Phase 3: lighter reads (API, one schema change)

1. **`/live` in one query.** A SQL function `live_items(production_id, since)` returns the union of the four reads
   (frames, renders, documents, jobs: id, kind, shot_id, status, job_kind, updated_at), ordered, with the latest build
   job's last `seq`. `security invoker`, granted to the roles the API uses; the repo calls it once. Into
   `schema_v25.sql` + `upgrade_v24_to_v25.sql` + a migration (`npx supabase migration new live_items`), with rows in
   `supabase/tests/database/`. The person applies v25 (D6); until then the four-query path stays behind the repo method.
2. **`GET /build/events?after_seq=N`**: only the new events (the repo already has `events(job_id, after_seq)`), the job's
   status and the open question COUNT. One job read, one events read.
3. **`/build` (the full view) reads the job once**, not twice (`get_build` and `_summary` both call `jobs.latest`), and
   the summary counts episodes, scenes and shots with `count` queries instead of listing every row.
4. Tests: each route's answer equals today's for the same data; query counts asserted with the counting fakes.
   Measure; record.

### Phase 4: batched reads on the pages (API + interface)

Each item answers one finding; each keeps the old route until nothing calls it.

1. **`/usage` cached** (F8): the server-side header read is cached 60 s per person (a `fetch` revalidate or a small
   per-request-scope cache in `features/usage/api.ts`); the API side may also keep the percentage 60 s per person.
2. **The landing read** (F9): `GET /v1/productions/{id}/home` answers what the production's first page draws (overview,
   documents, access, board summary) in one request, the way `/page` serves the scene page. `/director-personas` (a
   fixed library) is cached for the session. `/sable` is read only when Sable is enabled.
3. **The Zora turn carries the updated scene** (F10): the turn's final stream event includes the scene view and the
   production view the page reads today, and the interface puts them in the cache instead of reading again.
4. **The shot panel** (F11): `GET .../shots/{id}/panel` returns render plans and handoff from one `load_shot` (as
   13b phase 5 did for the two plans); the Generate Video card and the handoff read it through one query key.
5. **No `/packet` 404s** (F12): `/page` says whether the scene has a breakdown packet (it already reads the scene); the
   interface asks for the packet only when it does.
6. **`/page` back to ~15 queries** (F13) if phase 0 found a regression.
7. `/cost` (F14) stays with plan 13b phase 6; this plan only records its number.
8. Measure; record.

### Phase 5: the stream (API + interface)

1. **The hub** (`api/live/hub.py`): one per API instance. It subscribes, with the service key, to Postgres changes on
   the tables of section 2.1 through the async Realtime client already installed with `supabase` (2.33). For each
   change it builds the same `LiveItem` `/live` returns (plus `seq` for build events, plus "changed" notices for
   shots, scenes, board, chat), finds its production (directly, or job -> production from a small cache for
   `job_events`), and hands it to the streams open for that production. It subscribes only while at least one stream
   is open, and drops the subscription when the last one closes. Rows are never forwarded; only the fields named above.
2. **The route**: `GET /v1/productions/{id}/stream?since=<version>` (`routers/live.py`), `text/event-stream`,
   `Permission.VIEW`. It first sends a catch-up built from `/live`'s read for `since` (so nothing is missed between a
   page's load and its stream), then live messages, each with an `id:` equal to its version. A comment line every 20 s
   keeps proxies from closing it. The stream ends by itself after about 4.5 minutes (D2) and the browser reconnects
   with its last version; ending also re-checks access.
3. **Limits**: at most 3 open streams per person per production (a fourth closes the oldest); a stream whose production
   has had nothing active for 2 minutes ends; nothing is held per stream but a queue of at most 200 messages (a slow
   client that overflows is closed and catches up on reconnect).
4. **The browser**: the activity store gets a second transport. It reads the stream with `fetch` and a streamed body,
   the way the chat panels do (the built-in `EventSource` cannot send the bearer token, and a token in the URL would be
   logged). It opens the stream where today it would start polling (`kick()`), closes it when the work settles or the
   tab is hidden, reconnects with `since` on a drop (backoff 1, 2, 4 ... 30 s), and falls back to the poll after 3
   failed connects in a row. Screens do not change: they already subscribe to the store.
5. **The switch**: `LIVE__TRANSPORT=poll|stream` on the API (the route answers 404 when `poll`, which tells the browser
   to poll) and the same name read by the interface. Default `poll` until the person's check (D4).
6. Tests: a fake Realtime client feeds rows; the stream emits the right messages for the right production only; a
   person without access gets 404; catch-up plus live gives every change exactly once; the browser store reconnects and
   falls back. Measure the creation walk with `stream` on; record.

### Phase 6: fewer writes (functions), only as large as phase 0's counts say (D3)

1. **Heartbeats throttled.** A worker touches its row's `updated_at` at most once every 30-60 s (the sweeper's shortest
   limit is 10 minutes). Each service's `runtime/store.py` (each function vendors its own); forked services record it in
   their `UPSTREAM.md` (`video_render` is a fork).
2. **`job_events` batched** where a worker writes them in bursts: buffered and written as one insert every 2-3 s or
   every 20 events, and always flushed before a status change and at the end. One write, one push. The build page's
   events still arrive in order (`seq`).
3. **Ticks are pushed, never stored**, if a worker has any (a percentage, "thinking"): they go out as Realtime
   broadcast messages the hub forwards, not as rows. Today no worker sends ticks; this item exists so none is ever
   stored as a row.
4. Tests per service: a re-delivered job still skips finished work; the sweeper still sees progress; a crash mid-batch
   loses at most the unflushed events, never a status. Measure writes; record.

### Phase 7: measure again and write it down

The creation walk and 13b's scene walk, on `next build && next start`, with `poll` and with `stream`. `IMPLEMENTED.md`
gets the table of section 4 with measured numbers, the open items, and what the person decides next (D4).

## 6. How to measure (before and after every phase)

Plan 13b's tools, unchanged: `plan/2026-11-13b/measure/` (`seed.py`, `walk.js`, `analyze.py`; the traffic-bot user and
the "test" production). Its section 3 has the commands. API with `DEBUG_TRAFFIC=true` and
`DEBUG_TRAFFIC_LOG=plan/2026-11-13d/measure/trace.jsonl`; interface on :3030; functions with `OPENAI__API_KEY=` blank
for the creation walk. The creation walk adds rows (a production, a document, its build) to the hosted dev database:
ask the person first, and section 8 lists what to remove.

Each phase records in `IMPLEMENTED.md`: per stretch, API requests, `OPTIONS`, DB queries, before and after; and, for
phase 5, open streams, messages sent, reconnects.

## 7. Decisions for the person

| # | Decision | Recommended |
|---|---|---|
| D1 | Where the stream's changes come from: server-side Realtime (the API subscribes; tables already published), Postgres `LISTEN/NOTIFY` (needs a direct or session-mode connection; the transaction pooler cannot LISTEN), or one internal poll per production shared by all tabs | **Server-side Realtime** |
| D2 | The API's hosting limits for streams: Cloud Run (`deploy-api.yml` sets no `--timeout`, so 300 s) | Keep 300 s and reconnect every ~4.5 min; raise `--timeout` only if reconnects show in the numbers |
| D3 | Phase 6 now, or after phase 0's write counts | **After the counts**; it may shrink to the heartbeat throttle |
| D4 | When `LIVE__TRANSPORT=stream` becomes the default | After phase 7 on localhost and the person's check; deploying is the person's |
| D5 | If preflights are real (F6): `max_age`, or a same-origin rewrite | `max_age` first (one line); the rewrite only if preflights still show |
| D6 | Applying schema v25 (`live_items`) to the hosted project | The person's, after phase 3's tests |

## 8. Left in the dev database by the measurement

The creation walk's productions (named `traffic-create-<date>`), their documents, build jobs, events, episodes, scenes
and questions. `seed.py clean` (extended in phase 0 to cover them) removes them; run it when the person says so.

## 9. Risks

- **A missed message.** Every message carries a version; a reconnect asks for everything since the last one; the poll
  stays as fallback. A page's first load reads the truth, so a lost message costs at most one stale status until the
  next change or reconnect.
- **Realtime limits on the Supabase plan** (connections, messages per second): the API holds one subscription per
  instance, not one per tab, so the count is small. Phase 7 records messages per build.
- **Cloud Run instances kept busy by open streams** (billed while a request is open): streams open only while work runs
  and end after ~4.5 min or 2 min idle.
- **Several API instances.** Each has its own hub and its own subscription; a stream lives on one instance; nothing is
  shared between instances, so nothing needs to be.
- **Stale caches in the API** (access 15 s, canon and looks 30 s): unchanged; the hub calls `api.cache.job_ended()` when
  it sees work settle, as `/live` does today.
