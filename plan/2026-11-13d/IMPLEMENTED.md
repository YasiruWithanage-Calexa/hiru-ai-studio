# plan/2026-11-13d: what is built

## Phase 0: measured, F1 / F6 / F13 settled (2026-11-13)

Tools in [measure/](measure/): `create.js` (the creation walk), `analyze.py <label>` (per stretch: API requests, how
many the browser asked, OPTIONS, DB queries, response KB), `start-dev.ps1` (the API with the trace; functions only with
`-Functions`, see the incident below), `f1.js` / `f1b.js` (F1). `seed.py` in plan 13b's `measure/` gained `create-prod`
(a fresh `traffic-create-<time>` production, the traffic bot its director: creating a production is an admin's act and
the bot is not one, so the walk starts at the upload) and `clean-create` (called by `clean`). The API trace now records
response bytes (`observability.py`, `bytes`).

### Incident: the baseline walk made real model calls

The creation walk's build ran with the functions started by an earlier `start-dev.ps1` that removed
`OPENAI__API_KEY` from their environment. **It still made 49 OpenAI calls (~$1.34 at list prices: 23 gpt-5 calls in the
build's shot planning, 25 gpt-5-mini, one gpt-5-nano, one embedding).** Every function was stopped as soon as it was
seen; the last call was 14:28:45 UTC; the build job was then failed by the sweeper. The functions' werkzeug logs and the
`token_usage` timestamps show the local functions ran the work; a probe started exactly the same way saw no key
(`OPENAI__API_KEY` absent, `llm_enabled` false, `AISettings` key empty). **The cause is not known.** One difference: on
Windows an empty value removes a variable, so the API (`uvicorn --env-file .env`) re-read the key from `.env`; no
evidence was found that the API did the work. The person chose **no more build walks**: later phases are measured on
the walk's other stretches, on 13b's scene walk, and with query-count tests. `start-dev.ps1` now starts no function
unless asked, and with `-Functions` points their HTTPS proxy at a dead port (Supabase and localhost exempt).

### Baseline (label `p0`, `next dev`, 2026-11-13; [report.p0.txt](measure/report.p0.txt))

| Stretch | Seconds | API requests | from the browser | OPTIONS | DB queries | KB |
|---|---:|---:|---:|---:|---:|---:|
| Productions page | 8 | 3 | 0 | 0 | 3 | 2 |
| Landing on the new production | 7 | 4 | 1 | 1 | 7 | 1 |
| Documents page | 4 | 9 | 1 | 1 | 10 | 4 |
| Upload and reading (dialog open) | 11 | 11 | 11 | 11 | 28 | 7 |
| Structure build (10 min, then stuck) | 601 | 215 | 189 | 189 | **1285** | 413 |
| Build page after it settled | 10 | 3 | 3 | 3 | 20 | 5 |
| Overview, episode | 11 | 7 | 1 | 1 | 12 | 31 |
| Scene director | 8 | 8 | 0 | 0 | 33 | 31 |
| Shot | 8 | 5 | 0 | 0 | 44 | 18 |
| Idle 30 s | 30 | 0 | 0 | 0 | 0 | 0 |

The build stretch: `/build` 199 times (6.3 queries, 1.7 KB each; ~3 s apart, B's poll), `/overview` 8 and `/questions`
8 (each `router.refresh()`), `/live` 4. The reading stretch: `/documents` 7 (C's poll) beside `/live` 4 (A) for one
document (F2). `/page` 22 queries, `/cost` 21, `/packet` 404 on the scene open (F12).

### F1 (productions page loop): not reproduced

`f1.js` and `f1b.js`, with the productions page on screen: (a) API up from the start: 0 server renders in 12 s after the
load; (b) page opened with the API down (it shows `app/error.tsx`, which never retries by itself), API started: 0 reads
in 15 s; (c) HMR: ten client components, then the page, `features/productions/api.ts` and its mapper changed and
restored: 0 reads (Next dev keeps fetch answers across HMR refreshes). No component on the page calls
`router.refresh()`. The cause is not found, so phase 1 has nothing to fix; the plan's own log noted the loop "not seen
at 14:33". If it is seen again, the API log line times and the browser's state then are what to keep.

### F6 (a preflight before every GET): not a product problem

The API sends `access-control-max-age: 600`. Playwright's Chrome (a DevTools-protocol client, as an open DevTools is)
sent 192 preflights for 192 `/build` reads. A plain headless Chrome with no DevTools attached, fetching the same URL
with a bearer token ten times from an allowed origin, sent **one** preflight. Phase 1 skips F6 (D5 not needed). Walk
reports keep an OPTIONS column; it measures the automation, not people.

### F13 (`/page` 22 queries, 13b measured 14.7): a regression, found

The trace shows six reads repeated inside one `/page` (scene, shots, lines, episode, looks, scene looks). `production.load`
now also calls `repos.direction.series()` (commit 703d091, after 13b) in the same `gather` as the episode and looks
reads. `series` is not a name the 13b memo knows as a read, so the memo treats it as a write: it clears itself, and the
reads running beside it are not kept either. Fixed in phase 4.

### Writes (phase 6 input)

No worker writes `updated_at` itself; progress is `job_events` rows (a trigger keeps the job's `updated_at`). One
document read: 6 events, 2 document status changes, 2 job status changes. The build up to its stall (read, canon,
episodes, scenes, shots for 4 of 6 scenes): 20 events. A frame or a render was not run (no functions). These are
dozens of rows per run, against the 1285 queries the build page read in the same ten minutes.

Data left in the dev database: production `traffic-create-20261113-194816` (1 document, 2 jobs, 1 episode, 6 scenes,
14 shots, 7 canon entries) and 13b's seed. `python plan/2026-11-13b/measure/seed.py clean` removes both, when the
person says so.

## Phase 1: nothing to fix

F1 was not reproduced (phase 0) and F6 is not a product problem (phase 0), so no product change; D5 is not needed.

## Phase 2: one status source: built, measured

- API: `/live`'s item for a `structure_build` job carries `seq`, the job's newest event number (`jobs.last_seq`, one
  more query only when a build job is in the answer). `GET /build` carries `seq` too.
- Interface: the build page is a server shell (`page.tsx`) and a client screen (`features/build/components/build-screen.tsx`)
  drawn from three TanStack queries (`queryKeys.build`, `openQuestions`, `structure`) seeded by the server read
  (`features/build/queries.ts`; a newer server read replaces the cache, an older one never does). `useBuildLive` listens
  to the activity store: when the build job's `seq` or status is newer than what the page holds, it catches up once (a
  change arriving meanwhile is read in one more catch-up), and invalidates the tree only when a stage or the status moved
  and the questions only when their count moved. An answer or a retry catches up and kicks the poll. **No
  `router.refresh()` and no timer on the build page.** The status chip in the header reads the same cache.
- The activity store emits an event when an item's `seq` changes, not only its status (`previous` stays the status).
- The start-build dialog reads `/documents` once on open, draws status changes from the store's messages, and reads the
  list once more when a document (or its `doc_ingest` job) settles. Poller C is gone.
- `BuildRefresher`, `useLiveRefresh` and `usePoll` are deleted (no caller left); `docs/ARCHITECTURE.md` "Live updates"
  says the shared poll is the only one.
- Tests: `tests/api/test_live.py` (seq, only the build reads one; the pre-existing failure in
  `test_finished_work_shows_once_after_since_then_busy_goes_false` was its seed: `f2` was "finished" after `since`, now
  an hour before); interface `store.test.ts` (a newer `seq` is an event), `features/build/queries.test.tsx`,
  `start-build-dialog.test.tsx` (one read on open, none in 3 s, one more when ready), and the chat and retry tests (no
  page refresh).
- Measured with a **simulated build** (`measure/fakebuild.py`: a `structure_build` job in the creation production whose
  events, one every 3 s for 90 s, are written with the service key; no function runs, no model is called;
  `measure/buildwalk.js` keeps the build page open through it). The same simulation on the old code (stashed) and the
  new ([report.b0.txt](measure/report.b0.txt), [report.p2.txt](measure/report.p2.txt)):

  | Build page, 92 s, an event every 3 s | API requests | DB queries | KB |
  |---|---:|---:|---:|
  | Before (old code) | 116 | 504 | n/a (the bytes column came with this plan) |
  | Phase 2 | 69 | 369 | 206 |

  Before: `/build` 58, `/questions` 29, `/overview` 29 (each change = a page refresh). Phase 2: `/live` 29, `/build` 30
  (whole, on every new event), `/overview` 8 (stages only), `/questions` 2.

## Phase 3: lighter reads: built, measured; schema v25 NOT applied

- `live_items(p_production, p_since)` (security invoker, `search_path = ''`, service role only): the four tables and
  the build's newest event number in one union, ordered by `updated_at`. In `supabase/migrations/20261113145807_live_items.sql`,
  `Database/schema_v25.sql` (v24 + the function beside `canon_refine_apply`) and `Database/upgrade_v24_to_v25.sql`;
  pgTAP rows in `supabase/tests/database/022_live_items.test.sql`. **Not verified: Docker was not running**, so neither
  `npx supabase test db`, the advisors nor the three-dump comparison were run. D6 (applying v25) is the person's.
- `jobs.live_items()` calls it; before v25 it gets `PGRST202` once, logs it, and the process stops asking: `/live` then
  reads the four tables (and `last_seq`) as in phase 2. `tests/api/test_live.py::test_with_schema_v25_it_is_one_query`.
- `GET /build/events?after_seq=N` (`BuildDelta`): the latest build job, its events after N, the open questions count:
  3 queries whatever the build's length. The events become changes in order (`fold`, shared with `view`), with the job's
  status and `last_agent`. `BuildView` carries `last_agent` too. The interface applies a delta with `applyBuildDelta`
  (`map-build.ts`); a delta for another job (a retry) makes it read `/build` whole. `tests/api/test_build_delta.py`
  checks that a delta applied to the view at ANY earlier event gives exactly `/build`'s view, for a running, waiting,
  finished and failed build; `map-build.test.ts` holds the same rule in TypeScript (change both).
- `GET /build` reads the job once (it already did: the plan's "twice" was not in the trace), counts the open questions
  and the episodes, scenes and shots with `count` queries (`questions.count_open`, `episodes.count_structure`, HEAD
  requests) instead of reading every row. The interface counts the summary from the tree when it has it (the tree is
  read again when a stage moves).
- Measured (same simulation, [report.p3.txt](measure/report.p3.txt); the hosted database has no v25, so `/live` is still
  5 queries):

  | Build page, 93 s | API requests | DB queries | KB |
  |---|---:|---:|---:|
  | Phase 2 | 69 | 369 | 206 |
  | Phase 3 | 67 | 280 | 126 |

  `/build/events` 3 queries and 0.4 KB a call (was `/build` 6 and 2.6 KB, growing with the build). With v25, `/live`
  drops from 5.3 to 1 query: about 130 fewer in this stretch. The simulation has news on every poll; a real build is
  quieter between model calls, so it would read `/build/events` less often.

## Phase 4: batched reads on the pages: built, measured

1. **`/usage` held** (F8): `apiHeld(path, ms)` in the interface's `lib/api/server.ts` keeps a GET's answer per path and
   per access token across server renders (on `globalThis`: the dev server gives each route its own module copy; a
   failed read is not kept; at most 500 entries). `/v1/usage` is held 60 s, `/v1/director-personas` 10 min. The API side
   already holds the month's sum (plan 13b phase 7); unchanged.
2. **`GET /v1/productions/{id}/home`** (F9, `routers/home.py`): the production, the caller's access, the documents and
   the director board, each by calling its own route's function (`tests/api/test_home.py` holds each part equal to its
   route). The documents page reads it (`features/documents/api.ts` `getDocumentsHome`; the server seam `getDocuments`
   had no other caller and is gone). The board summary comes from the board's own personas, so the persona library is
   not read on that page at all. `/overview` stays the layout's read. `/sable` was left: it is one status read per five
   minutes per tab with 0 queries (TanStack, plan 13b phase 7).
3. **A Zora turn ends with the scene's two views** (F10): the turn route reads the function's frames as they pass (never
   changing them; a chunk may end inside a frame or a letter) and, when the turn changed the plan (a `plan` frame, or
   `done` with a revision or an undo / redo: the panel's own test), clears the request's memo and appends
   `event: views {scene, production}`, equal to `GET .../scenes/{id}` and `.../production`. The workspace's
   `SceneRefreshProvider` takes an `apply` that puts both in the cache; the director page (server-drawn) still refreshes.
   `tests/zora/test_api.py` (two new tests), `features/zora/client.test.ts`.
4. **`GET .../shots/{id}/panel`** (F11, `routers/shot_panel.py`): both render plans and the handoff view from one
   `load_shot` (`renders.plans_for` and `handoff.view_of` split out of their routes). The Generate Video card's first read
   of a shot is this one request, which fills both of its queries; a later read (a take landed, a 409) asks only the half
   that changed. `tests/api/test_renders.py::test_the_shot_panel_is_both_plans_and_the_handoff_from_one_load`.
5. **No `/packet` 404s** (F12): `/page` carries `packet` (the `/packet` answer, or null). `packets.get` is memoised, so
   it reuses the read `scenes.view` makes (0 extra queries). The director page's `getScenePacket` reads the same `/page`
   path, which `api()` shares within a render: no request of its own.
6. **`/page` back to 16 queries** (F13): `series`, `last_` and the other read-only names (`events`, `find_`, `match_`,
   `processing_before`, `download`, `refined`) are reads to the memo now. `test_page_reads_the_scene_rows_once` wraps
   EVERY repository in the memo, as production does (it wrapped only the memoised ones, which is why it missed this);
   it failed before the fix and passes after.
7. `/cost` (F14) is plan 13b's: measured 23 queries here.

Measured (`measure/pages.js`, nothing running; baseline code stashed vs this phase, same production, `next dev`;
[report.b4.txt](measure/report.b4.txt), [report.p4b.txt](measure/report.p4b.txt)):

| Page | API requests before | after | DB queries before | after |
|---|---:|---:|---:|---:|
| Productions | 3 | 2 | 3 | 2 |
| Documents | 9 | 4 | 11 | 9 |
| Overview | 4 | 3 | 5 | 4 |
| Episode | 3 | 2 | 6 | 5 |
| Scene director | 8 | 6 | 33 | 24 |
| Shot workspace | 9 | 8 | 52 | 43 |
| Whole walk | 42 | 30 | 117 | 94 |

`/usage` was read once in the whole walk (was on every page). The Generate Video card was not on screen in the
headless viewport, so `/panel` did not run in the walk (its test covers it). Not measured: a Zora turn (it needs the
zora function and a model).

## Phase 5: the stream: built, measured; default stays `poll` (D4)

- `contracts/live.py`: the shapes only (`LiveItem`, as `/live` returned it; `LiveNotice` for the board and a thread
  another person wrote in; `Live`). `/live` uses them (same JSON) and exposes `read_live()` for the catch-up.
- `api/live/hub.py` `LiveHub`, one per API instance (`app.state.live_hub`, made at startup): it listens through a
  `ChangeSource` only while a stream is open and stops when the last one closes. `RealtimeSource` is Supabase Realtime,
  server side, with the service key, one channel over `first_frames`, `video_renders`, `documents`, `jobs`,
  `job_events`, `chat_messages`, `production_director_board`. A change becomes the `/live` item (named fields only: a
  row is never forwarded); a `job_events` insert becomes the build job's item with its `seq` (the job's production and
  kind from the jobs seen, else read once and remembered, at most 2000); a chat message is a `thread` notice that is
  NOT sent to its own author; a board change is a `board` notice. One odd row is logged and skipped.
- `GET /v1/productions/{id}/stream?since=` (`routers/live.py`), `Permission.VIEW` (a stranger: 404, nothing opens):
  registers with the hub first, then sends the catch-up from `read_live(since)`, then each change, every frame with
  `id:` = its version; a change already sent (same status and `seq`) is not sent twice; `: keep-alive` every 20 s; it
  ends after 270 s (`LIVE__MAX_S`, D2), after 120 s with nothing of the production active, when the person's fourth
  stream on the production closes it (the oldest goes), or when its queue (200) overflows. A settled item calls
  `job_ended()` as `/live` does. `LIVE__TRANSPORT=poll` (default) makes it 404.
- Not built: notices for shots and scenes. A planner's shots arrive with its job settling (already invalidated), and a
  person's own edit already put the write's answer in the cache: a "scene changed" notice would make every edit read the
  scene again. Chat panels keep their messages in their own state, so a `thread` notice invalidates the `threads`
  queries only; an open chat does not yet show another person's message by itself.
- Interface: the activity store has a second transport (`open`, `lib/activity/index.ts`, on when
  `NEXT_PUBLIC_LIVE_TRANSPORT=stream`): `browserEventStream` (`lib/api/browser.ts`) reads the stream with `fetch` and a
  bearer header (no token in a URL). The store opens it where it used to start polling, feeds the same item handling
  (listeners see the same events), keeps `since` from the frame ids, ends with the server when nothing is active and
  reconnects when something is, holds no stream in a hidden tab, reconnects after a drop at 1, 2, 4 … 30 s, and polls
  after 3 failed connects in a row or at once on 404. `activity.onNotice` gives notices to the provider, which
  invalidates the scene (board) or the threads. Screens did not change.
- Tests: `tests/api/test_live_stream.py` (a fake source: scoping by production, nothing but the item's fields, the
  build's `seq` and one job lookup, own chat messages left out, the fourth tab and the slow client, 404 with poll, 404
  for a stranger, catch-up then each change once then the idle end and the hub stopping); `store.test.ts` (six stream
  cases).
- Measured live, with Realtime on the hosted project (the simulated build, `next dev`,
  [report.p5.txt](measure/report.p5.txt)): one `/stream` request for the whole build, no `/live` poll, 7.2 KB pushed.

## Phase 6: not built (D3)

The counts of phase 0 say there is nothing to throttle: no worker writes `updated_at` itself (a trigger does, on its own
writes), and a run writes dozens of `job_events` rows, against the hundreds of reads the pages made. No worker sends
ticks, so item 3 (ticks are pushed, never stored) has nothing to change today. D3 is the person's: this record is the
input.

## Phase 7: measured again (2026-11-13)

`next build && next start` works now: `ActivityProvider` read `useParams()` outside `<Suspense>`, which stopped every
build on `CLIENT_HOOK_DYNAMIC` (plan 13b saw it) and printed the console error in every walk. The URL is now read by a
null-rendering child behind its own `<Suspense>` (children are not held back). The same simulated build and the page
walk, on `next start` ([report.p7poll.txt](measure/report.p7poll.txt), [report.p7stream.txt](measure/report.p7stream.txt),
[report.p7pages.txt](measure/report.p7pages.txt)):

| Moment | Before (old code, `next dev`) | Poll (`next start`) | Stream (`next start`) |
|---|---|---|---|
| A build running, 92 s, an event every 3 s | 116 requests, 504 queries | 66 requests, 276 queries | 40 requests, 144 queries |
| ... of which status reads | `/build` 58 (6 q each) + 2 refresh reads per change | `/live` 29 (5.3 q each; 1 with v25) | `/stream` 1 (7 q, once) |
| ... the change itself | `router.refresh()`: `/build` + `/overview` + `/questions` | `/build/events` (3 q), `/overview` on a stage | same |
| Reading a document | `/live` + `/documents` every ~3 s | `/live` only | nothing between changes |
| Documents page (landing) | 9 requests, 11 queries | 4, 9 | same |
| Every navigation | `/usage` (1-2 q) | once a minute per person | same |
| Scene director | 8 requests, 33 queries | 6, 24 | same |
| Shot workspace | 9 requests, 52 queries | 8, 44 | same |
| After a Zora turn | 2 reads, ~20 queries | 0 reads: the turn's own stream ends with both views (tested, not walked: it needs the function and a model) | same |

Against the plan's targets (section 4): a running build with the stream sends no status reads (one stream), and a change
costs one small read (`/build/events`, 3 queries) plus `/overview` when a stage moves; the simulation has a change every
3 s, so it makes 30 of those. `/live` at 1 query needs v25 (D6). The productions page loop (F1) was not reproduced.

Open items for the person:
- D4: `LIVE__TRANSPORT=stream` (API) and `NEXT_PUBLIC_LIVE_TRANSPORT=stream` (interface, at build time) as the default.
- D6: apply `Database/upgrade_v24_to_v25.sql` (after the local-stack check that Docker prevented here: `npx supabase test
  db`, the advisors and the three-dump comparison).
- D3: phase 6 (nothing to throttle today).
- The cause of the incident in phase 0 (real model calls with the key removed) is unknown; no build walk was run after it.
- `seed.py clean` (plan 13b `measure/`) removes the walk's production `traffic-create-20261113-194816`, its 6 simulated
  build jobs and 13b's seed, when the person says so.
