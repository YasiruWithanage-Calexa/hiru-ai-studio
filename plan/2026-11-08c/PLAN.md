# Quiet by default: one copy of the data, one download per file (plan/2026-11-08c)

Status: written 2026-11-08, not built. Plain words: [human-read.md](human-read.md). Repos: this one (API) and
`hiru-ai-studio-interface`. Model to copy: PromptMotion's frontend (`prompt-motion-frontend/src`), which already works
this way.

## 1. Why

The app runs on the person's machine, but the database and Storage are the hosted Supabase project "Hiru AI Studio -
Dev". Every read the API makes goes over the internet to Supabase. On 2026-11-08 that project showed **Cached Egress
83.3 GB of 5 GB (1,666 %)**, against **0.18 GB** stored. Every stored file had been downloaded about 470 times.
Reading both repos found the causes:

| # | Finding | Where |
|---|---|---|
| F1 | **Every file link is new on every read.** A ticket carries a random nonce, so the same picture gets a new URL each time a page reads its data. The browser caches by URL, so it never reuses a download. | `src/api/services/media_links.py` `ticket()` (`os.urandom(12)`) |
| F2 | **The API keeps no copy of any file.** Each `/files` hit downloads the file from Supabase again. | `src/api/routers/files.py` |
| F3 | **Thumbnails are the full pictures.** Frames and sheets are 1536×1024 PNG (about 2–3 MB). A 200 px storyboard tile downloads the whole file. Image resizing is not on the Supabase plan. | `libs/hiru_ai/adapters/images.py:24`; `storyboard.tsx`, `scene-strip.tsx`, canon cards |
| F4 | **Every click re-reads the whole page.** The interface has 45 `router.refresh()` calls in 30 files. Each one re-runs every server read on the page. The shot workspace has about 10: scene, production, episode, threads, messages, Zora status, access, cost, usage, me. Each read is several Supabase queries, and each mints new tickets (F1). | `features/*/components/*.tsx`; `features/scenes/api.ts` `getSceneContext` |
| F5 | **Writes already return the new data, and the interface throws it away.** Many write routes answer with the updated view (`SceneView` ×8, `ShotProductionView` ×5, `HandoffView` ×3, `CanonEntity` ×4 …), then the client calls `router.refresh()` anyway. | `src/api/routers/*.py`; `run()` in `shot-workspace.tsx` / `production-workspace.tsx` |
| F6 | **The "small status read" is the full scene loader.** `fetchFrameProgress` calls `GET …/scenes/{id}/production` every 4 s. That runs about 10 queries (whole canon, every look in the production, all frame columns) and mints a ticket for every frame. | `features/production/client.ts:228`; `routers/production.py:262` `load()` |
| F7 | **Many pollers run at once, each on its own timer.** `waitForJob` every 2 s, `useLiveRefresh` 4 s (×2), `generate-video-card` 4 s, `takes-log` 5 s, documents 2.5 s, build 3 s / 2.5 s, plus the chat pollers. Nothing shares one read. | `lib/poll/*`, the files above |
| F8 | **In the committed code (`HEAD`), pollers re-read every page on a timer:** `setInterval(router.refresh, 4000)` while any frame is `queued`/`running`, and 5 s for takes. The loop kept running in hidden tabs. The working-tree fix (`lib/media/media-cache.tsx`, `use-poll.ts`) is uncommitted and covers the scene pages only. | `git show HEAD:…/production-workspace.tsx` line 94 |
| F9 | **Nothing ends a stuck job.** A frame or render left `queued`/`running` by a dead worker stays that way, and its poller never stops. | no cleanup in `src/api`, `src/services` |
| F10 | **Hot reads use `select("*")`** (44 places), so every poll pulls whole rows: prompts, checks and so on. | `src/api/repositories/supabase.py` |
| F11 | **Media paths can be overwritten** (`x-upsert: true` on every worker upload), so a path is not guaranteed to name one file forever. Caching by path needs that guarantee. | `services/*/runtime/rest.py` `upload` |

Put together: a person leaves the shot page open while one frame paints, and the page downloads every picture in the
scene every 4 seconds, from the internet, at full size.

## 2. The target (how PromptMotion does it)

1. **One shared copy of the data in the browser** (TanStack Query, `staleTime` 30 s). A page reads once. Moving between
   shots reads nothing new.
2. **A write answers with the updated object**, and the client puts it into the shared copy (`setQueryData`). No page
   re-read.
3. **Polling only while something is running**, through one read that returns statuses only, and only for the
   production on screen. Nothing runs when the page is idle or the tab is hidden.
4. **One link per file**, reused while it is still valid (`lib/mediaLinks.ts` `stableLink`, keyed by storage path).
5. Added here: **every file crosses the internet once** (an API disk cache), and **tiles use small thumbnails**.

### Budgets (the numbers the tests in §5 enforce)

| Situation | Today (estimated from the code; phase 0 measures it) | Budget |
|---|---|---|
| Open a shot page, first time | ~10 API calls, ~30–40 Supabase queries, every picture at full size | ≤ 6 API calls; thumbnails only |
| Click a shot in the same scene | ~10 API calls (page re-read) | **0** (already in memory) |
| One edit (camera, intent, coverage …) | 1 write + 1–2 full page re-reads (~20 API calls) | **1** API call |
| Start a job, wait 60 s | page re-read + `waitForJob` every 2–5 s + 1–3 other pollers, each a full scene load | 1 write + 1 status read every 3 s (~20 tiny reads) + 1 re-read when it finishes |
| Page open, nothing running | 0–N pollers depending on state; a stuck job means forever | **0 requests** |
| The same picture, the 2nd to 100th time | a full download from Supabase each time | **0** bytes from Supabase (browser cache, else the API disk) |
| A storyboard tile | 2–3 MB PNG | ≤ 60 KB WebP |

## 3. Decisions (the person's)

| # | Question | Recommendation |
|---|---|---|
| D1 | Client data library | **TanStack Query**, the same as PromptMotion, so its patterns (`seedProduction`, `optimistic`, `stableLink`) port over almost line for line. Server components still render the shell and pass the first read in as `initialData`, so the CLAUDE.md "server components by default" rule holds. |
| D2 | Live updates: poll or push | **One status poll while something runs** (3 s, paused when hidden), like PromptMotion's `refetchInterval: busy ? POLL_MS : false`. It is simple, needs no new infrastructure, and costs one tiny query. Server-sent events can come later (§9) if 3 s feels slow. |
| D3 | Size limit for the API's disk cache | **5 GB**, oldest files removed first, in `%LOCALAPPDATA%/hiru-ai/files` (setting `FILES__CACHE_DIR`, `FILES__CACHE_MAX_GB`). The whole bucket is 0.18 GB today. |
| D4 | Thumbnail size and format | **640 px wide WebP, quality 75** (about 30–60 KB). Saved next to each picture when it is uploaded; existing pictures are backfilled by a script (§4.1c). |
| D5 | Ticket lifetime | Keep **1 hour**, but give every ticket in the same hour the **same URL** (§4.1a). The browser may then cache it for the rest of that hour. |
| D6 | Stuck-job limits | Frame 10 min, take 30 min (Veo can be slow), document 20 min, other jobs 15 min. A stuck job is then marked `failed` with "Stopped: no progress for N minutes". |

## 4. Design, by phase

### Phase 0 — Measure first (½ day)

- API middleware `observability.traffic`, on when `DEBUG_TRAFFIC=true`. Once a minute it logs one line per route: calls,
  Supabase queries made, `/files` hits served from the disk cache vs from Supabase, and bytes sent. Supabase queries are
  counted by wrapping the repos' `execute()` and the storage client.
- `scripts/traffic_scene.py`: signs in, opens a shot page's reads, makes one camera edit, starts one frame job and waits
  for it. Writes the counts to `plan/2026-11-08c/baseline.json`. Run it before and after each phase. No model calls: run
  it with the fake image provider.

### Phase 1 — Files cross the internet once (API; 1–1½ days)

**1a. Same file, same hour, same URL.** `media_links.ticket()` derives the nonce from
`HMAC(key, bucket|path|hour_end)` instead of `os.urandom`, and `e` becomes the end of the current hour, plus one hour
if fewer than 10 minutes remain. The same file in the same window gives a byte-identical ticket. AES-GCM stays safe
because the nonce changes whenever the plaintext does (an SIV-style construction). `/files` answers
`Cache-Control: private, max-age=<seconds left on the ticket>, immutable`. Test: two calls in one window are
identical; the next window differs; a tampered ticket is still 404.

**1b. Disk cache in `/files`.** On a hit, stream the local file with Range support (Starlette `FileResponse` handles
206). On a miss, download from Supabase once, write to `<dir>/<bucket>/<path>.part`, rename, then serve. Concurrent
misses for one path share one download (the existing `AsyncTTLCache` single-flight pattern). Removed oldest-first above
D3's cap. A deleted object (document delete, `repos.storage.remove`) also removes its cached copy. Test: the second
request makes zero upstream calls; Range on a cached video returns 206.

**1c. Thumbnails.** Add `Pillow` to `requirements.txt`. One function, `media_thumbs.make(png_bytes) -> webp_bytes`.
Every upload of a frame, reference sheet or look sheet also writes `<path>.thumb.webp`. These are the three
`frame_render/graph.py` paths and `production.py:726` / `renders.py:153` for person uploads. Views gain `thumb_url`
beside `url`. For takes, the API saves the take's first frame as `<take>.poster.webp` when the take lands; workers
already have ffmpeg for `last_frame`. `scripts/backfill_thumbs.py` makes the missing ones for existing files, once. It
downloads each file once, about 0.18 GB.

**1d. A media path names one file forever.** Worker `upload()` for the `frames`, `references` and `takes` buckets sends
`x-upsert: false`. A collision is a bug and fails loudly. Every media path already includes a fresh id (frame id,
`job_id[:8]`, take id), so nothing should break. A test asserts every media upload site builds its path from a new id.

### Phase 2 — One copy of the data in the browser (interface; 3–4 days)

**2a. Set up TanStack Query.** Add `@tanstack/react-query`, with one `QueryClientProvider` in `app/(studio)/layout.tsx`
(`staleTime: 30_000`, `gcTime: 30 min`, `retry: 1`, `refetchOnWindowFocus: false`). Query keys live in one file,
`src/lib/query/keys.ts`: `production(id)`, `scene(pid, sid)`, `sceneProduction(pid, sid)`, `shot(pid, shotId)`,
`handoff(pid, shotId)`, `canon(pid)`, `canonEntity(pid, eid)`, `documents(pid)`, `threads(pid, sid)`, `usage()`,
`me()`.

**2b. Server reads become the first value.** Pages keep their `features/*/api.ts` server reads (CLAUDE.md rule) and
pass the result to a client component as `initialData`. Each feature gets one hook, such as
`useSceneProduction(pid, sid, initial)`, in `features/<x>/queries.ts`. That hook is the only reader on the client.

**2c. Writes update the copy and nothing else.** For every write route:
- if it already returns the view (F5), `setQueryData(key, mapped)`;
- if it returns `ActionResult`, `Started` or nothing, change the route to return the updated view. A job route returns
  `{job_id, view}`, where the view already shows the queued frame. The list of routes to change is made in this phase
  from `grep "@router.(post|patch|put|delete)"` (92 routes);
- an edit that should feel instant uses PromptMotion's `optimistic(draft, request)`: show it now, send it, take the
  server's answer, and roll back on refusal.

**2d. `router.refresh()` is removed from interaction code.** It is only allowed after sign-in or sign-out and a
production switch. The 45 calls are replaced by 2c. A write that changes data on another screen invalidates that query
by key (`invalidateQueries(canon(pid))`), so it is read again only when that screen opens.

**2e. One link per file, everywhere.** Port PromptMotion `lib/mediaLinks.ts` (`stableLink`, keyed by storage path,
reused for 40 minutes) into `src/lib/media/links.ts`. The API adds a `file_key` (bucket + path hash, never the raw path)
beside each `url` / `thumb_url`. One `<Media>` component (image or video) is the only way to show an API file. It uses
`thumb_url` for tiles and `url` for the large view or download. This replaces `MediaCacheProvider` and the six plain
`<img>` canon views. After 1a this is a second layer of protection, not the only one.

**2f. Video.** `preload="none"` with the poster thumbnail. Only the take being played is downloaded.

### Phase 3 — One status read while work runs (both repos; 1½ days)

**API:** `GET /v1/productions/{id}/activity?scene_id=` returns
`{busy, version, items:[{kind, id, shot_id, status, updated_at}]}` for frames, drafts, takes/renders, documents and
jobs that are `queued`/`running`, or that finished since `since=`. It runs **two column-limited queries**: no canon, no
looks, no tickets. `version` is the newest `updated_at`.

**Interface:** one hook, `useActivity(pid, sceneId)`, mounted once per production layout. It polls every **3 s** only
while `busy`, and stops when the tab is hidden (the existing `usePoll` rules). When an item's status changes, it
invalidates **only** the queries that item belongs to: for example, a frame of shot S re-reads `shot(S)` and
`sceneProduction`. Everything else reads `busy` from this hook.

Removed: `waitForJob`, both `useLiveRefresh` uses, the `generate-video-card` and `takes-log` polls, `build-refresher`,
the documents panel poll, and `fetchFrameProgress`. The chats keep their own streams (they are already server-sent
events).

### Phase 4 — Lean reads in the API (1–1½ days)

- Hot reads list their columns, not `*`: frames, takes, renders, prompts and shots in `load()`, and every read in
  `activity`.
- `resolve_access(user, production)` is cached for 15 s (the `AsyncTTLCache` already used for profiles) and cleared on
  member or role writes.
- `canon.list(production)` and `looks.list_for_production` are cached for 30 s per production and cleared by the canon
  and look write routes. The scene loader stops re-reading the whole canon on every call.
- The shot page's first read becomes `GET …/scenes/{id}/page`: one response holding scene, production view, episode,
  access and threads. That replaces 5 of the ~10 calls. Usage and me stay separate (shared by every page, cached 60 s).

### Phase 5 — Stuck jobs end (API; ½ day)

A sweeper in the API's existing worker loop (`src/api/workers`) runs once a minute. Anything still
`queued`/`running` past D6's limit, with no `job_events` row in that time, becomes `failed` with a plain reason. The
same pass marks that job's frames and renders `failed`. A poller then sees `busy: false` and stops. Test: a fake job
older than the limit is failed; one with a recent event is left alone.

## 5. Guards, so it does not come back

| Guard | Where | Fails when |
|---|---|---|
| Lint: no `router.refresh()` | `eslint.config.mjs` `no-restricted-syntax`; allow-list: login, logout, production switch | anyone adds one |
| Lint: no `setInterval` / `setTimeout` loop for data | same rule, in `features/**` | a component starts its own timer |
| Lint: API media only through `<Media>` | ban `<img src={…Url}>` and `<video src={…}>` in `features/**` | a plain tag shows an API file |
| Request budget tests | vitest + MSW: render the shot workspace, click a shot, edit the camera, start a job, run fake timers 60 s, then count requests | any row of §2's budget table is exceeded |
| Idle test | the same harness with nothing running: 5 fake minutes | any request is made |
| Ticket test | pytest | two tickets for one file in one window differ |
| Disk cache test | pytest with a fake upstream | a second `/files` hit reaches upstream |
| Activity cost test | pytest with a counting repo | `activity` makes more than 2 queries or mints a ticket |
| Write routes return data | pytest over the route table | a POST/PATCH/PUT in the interface's list returns no view |
| Upload path test | pytest | a media upload sends `x-upsert: true` or reuses a path |
| Traffic log | phase 0 middleware, on in dev | (alert) any route > 60 calls/min, or one file from upstream > 2× per hour, logs a `WARNING` with the route |
| Rules | both `CLAUDE.md` files | — |

CLAUDE.md lines to add (interface): *"Client data goes through TanStack Query hooks in `features/*/queries.ts`. A write
puts its returned view into the cache; never `router.refresh()` after a click. Polling only through `useActivity`.
API files only through `<Media>`, with `thumb_url` for anything smaller than the full view."* (API): *"A write route
returns the updated view. Media paths are never overwritten. Status reads list columns and mint no tickets."*

## 6. What does not change

- Files still leave only through `/files/{ticket}`: no Supabase URL ever reaches the browser, and tickets stay
  encrypted and expiring (the `media_links.py` reasons all still hold).
- Who may see what (RLS, `require_permission`), every route path, the chats' streams, the workers and their retries.
- No schema change, no new hosted service.

## 7. Order and effort

| Phase | Effort | What it removes |
|---|---|---|
| 0 Measure | ½ d | — (gives the numbers) |
| 1 Files once | 1–1½ d | nearly all the egress (F1, F2, F3, F11) |
| 5 Stuck jobs | ½ d | endless polling (F9) |
| 2 One copy | 3–4 d | the request storms on clicks (F4, F5, F8) |
| 3 One status read | 1½ d | stacked pollers and the heavy status read (F6, F7) |
| 4 Lean reads | 1–1½ d | per-request DB weight (F10) |
| Guards (§5) | written alongside each phase | the regression |

Phases 1 and 5 go first because they stop the egress in two days, even before the interface changes. Commit the
working-tree `media-cache.tsx` / `use-poll.ts` fix now: it is a stopgap until phase 2 replaces it.

Before each phase is done: `npx next typegen && npm run check && npm run format:check` (interface), the API test suite,
and `scripts/traffic_scene.py` against the budgets.

## 8. Open after build (the person's)

- Run phase 0's script on the real project and compare with the budget table.
- Watch Supabase Usage → Cached Egress daily for a week after phase 1: it should go nearly flat.
- D1–D6.

## 9. Later, only if asked

- Server-sent events for activity (push instead of a 3 s poll).
- Supabase Realtime on the `jobs` table instead of the API poll.
- Resize-on-request thumbnails if more sizes are needed.
