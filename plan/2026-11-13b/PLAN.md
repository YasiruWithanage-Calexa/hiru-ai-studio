# One read per row: cutting redundant database calls (plan/2026-11-13b)

Status: written 2026-11-13, nothing built. Repos: this one (API) and `hiru-ai-studio-interface`. It continues
plan/2026-11-08c ("quiet by default"). That plan stopped the polling and the file downloads; this one stops a single
page open from reading the same rows many times. Build **one phase at a time**, re-measure after each (section 3),
then write `IMPLEMENTED.md` here with the new numbers.

## 1. Why

On 2026-11-13 a headless Chrome walked the studio, signed in as a test director, on seeded dummy data (3 episodes,
12 scenes, 72 shots, 120 frames, 72 takes; production `bac48f6d-e702-499b-9983-7ca73bf02ba8`). The API wrote every
request and each database query it made to a trace file. Full output: [baseline-report.txt](baseline-report.txt).

### Baseline (dev server, `next dev`, React Strict Mode on)

| Page open | API requests | DB queries | Worst repeat in that one open |
|---|---:|---:|---|
| Scene director (`.../scenes/{id}/director`) | 21 | **50** | the scene row read **9x**, its shots and lines **6x** each |
| Shot workspace (`.../shots/{id}/workspace`) | 34 | **111** | the scene row **11x**, its episode **10x**, shots and lines **9x** |
| Shot production (`.../shots/{id}/production`) | 19 | 97 | |
| Shot handoff (`.../shots/{id}/handoff`) | 6 | 31 | |
| Production overview | 5 | 9 | |
| Canon / canon entity | 8 / 9 | 13 / 17 | |
| Idle 75 s on any page | 0 | 0 | (good: nothing polls when nothing runs) |

Per route (DB queries per call): `/scenes/{id}/page` **20**, `/scenes/{id}/cost` **19**, `/shots/{id}/handoff` 10,
`/shots/{id}/render-plan` 9, `/canon/usage` 4, `/scenes/{id}/{adam,david,jonathan,raphael}` 3 each.

Strict Mode runs a plain `useEffect` twice in dev, so a fetch made outside TanStack Query is doubled in the dev
numbers. Those fetches are wrong either way (they skip the shared cache), so the plan moves them into queries rather
than discounting them.

### Findings

| # | Finding | Where |
|---|---|---|
| R1 | **`/page` re-reads what it already loaded.** It calls `production.load`, `scenes.view` and `structure.get_episode`, and each loads the scene, its shots, its lines and the episode again: 20 queries, 6 of them exact repeats. | `src/api/routers/page.py:41-46` |
| R2 | **Every shot route reloads the whole scene.** `/handoff`, `/render-plan` and `/cost` each read the scene, all its shots, lines, frames and prompts to answer about one shot. | `routers/handoff.py`, `routers/renders.py`, `services/costs.py` via `production.load` |
| R3 | **The scene page reads all four planners.** `/adam`, `/david`, `/jonathan`, `/raphael` (3 queries each, each re-reading scene, shots, lines) on every open, whatever `settings.shot_planner` says. | interface `app/(studio)/.../director/page.tsx:104-121` |
| R4 | **Looks are read once per character (N+1).** `getSceneCanon` calls `/canon/{id}/looks` per character (each re-reads the entity and every episode) plus `/scenes/{id}/looks`. `/page` already loads the production's `canon_looks` and the scene's `scene_looks`. | interface `features/canon/api.ts:69-92` |
| R5 | **Server reads come in three waves.** The page awaits `/page` + `/zora` + `/canon/usage` + `/access`, then the looks, then `AppHeader` asks for `/v1/me` + `/v1/usage`, then the planner slots start. About 1.5-2 s before the page is whole. | `director/page.tsx:41-55`; `AppHeader` |
| R6 | **The Generate Video card fetches outside the shared cache.** Two `/render-plan` reads (take and draft, about 9 queries each) on mount, before anyone presses Generate, plus `/handoff` again although the server page already read it. Plain `useEffect`, so nothing is shared and dev doubles it. | interface `features/handoff/components/generate-video-card.tsx:68-110` |
| R7 | **The scene cost is 19 queries, uncached.** 6 reads of `token_usage`; when the production has no history, two of them read the last 400 rows of every production. Runs on every shot workspace open. | `src/api/services/costs.py:88-132` |
| R8 | **Small reads repeat on every navigation.** `/v1/me`, `/v1/usage` (a month-long `token_usage_since` sum each time) and `/access`: 28 times each in the walk. Sable's status is read 2-3x per page because `scene-chat-choice.tsx` calls `getSableStatus` directly instead of `useSableStatus`. | `routers/usage.py`; interface `features/sable/components/scene-chat-choice.tsx:66` |
| R9 | **List reads take every column.** `/overview` reads every shot of the production with `select=*`; `/canon/usage` reads every scene and every shot with `select=*`. Scenes carry the planner plans (`adam`, `david`, `jonathan`, `raphael`, `script`, `staging`, `coverage`, `reading`); shots carry `ir`, `design`, `card`, `intent`. On the dummy rows: scenes 15.8 KB vs 3.0 KB with the needed columns, shots 63 KB vs 11 KB. Real plans are far larger. | `repositories/supabase.py` (scenes/shots `list_for_production`) |
| R10 | **Take posters can never be stored, and their links always 404.** The `takes` bucket allows video types only, so the assembler's `<take>.poster.webp` is refused. `_take_view` still returns a `poster_url`, and `/files` does not remember a miss, so each time a generated take's card shows, the API asks Supabase again and gets 404. (Found by the seed upload and by reading the code; not seen in the walk, whose takes are uploads.) | `Database/schema_v21.sql:1244`; `routers/handoff.py:141`; `services/file_cache.py` |

## 2. Rules that do not change

From `CLAUDE.md`, and they bind every phase:

- Routers never query Supabase: all DB access is `api/repositories` (`Repos` protocols), tests replace it with
  `tests/api/fakes.py`. Anything added to a repo is added to the fake too.
- A production the caller cannot see is 404. Access stays read from the DB on each request (the 15 s cache in
  `authz` is the only shortcut).
- Kept-briefly caches are cleared on write: `authz.forget_access()`, `api.cache.job_ended()`; a new cache follows
  that pattern and is cleared by the same writes.
- Costs: the cost response stays **the total and two flags, nothing else**; nothing stores a money figure (an
  in-memory copy of the price rows is allowed, a computed total is not); each margin applied once.
- A write route returns the updated view. Status reads list their columns and mint no tickets.
- The interface reads through TanStack Query (`staleTime` 30 s); a server component passes `initialData`.
- Schema changes go in the next version's pair (`Database/schema_v24.sql`, `upgrade_v23_to_v24.sql`) plus a
  migration; the person applies them. The dev project in `.env` (`gzvtzarhcwrtzyzvgymp`) already answers v21's
  `scene_packets`, and v22 and v23 (canon inferred, canon refine) came after it, so this plan's pair is v24 on v23.
- Before finishing a phase: `ruff check src tests scripts`, `mypy`, `pytest -q`, the interface's `npm run check`.

## 3. How to measure (before and after every phase)

Everything is in [measure/](measure/). It writes to the hosted dev project, but only dummy rows in the test
production, and calls no model.

1. Data (once; already seeded on 2026-11-13, skip if `measure/manifest.json` exists):
   `python measure/seed.py media`, `python measure/seed.py seed`, then `python measure/seed.py ids`.
   This creates the user `traffic-bot@hiru.test` (director on the test production). `seed.py clean` removes all of it.
2. API with the trace on (the `DEBUG_TRAFFIC_LOG` switch added 2026-11-13 in `api/observability.py`):
   `DEBUG_TRAFFIC=true DEBUG_TRAFFIC_LOG=plan/2026-11-13b/measure/trace.jsonl .venv/Scripts/python -m uvicorn api.main:app --app-dir src --env-file .env --port 8001`
   (delete the old `trace.jsonl` first).
3. Interface on :3030 (`npm run dev`; for the final numbers also `npm run build && npm run start -- -p 3030`, which has
   no Strict Mode doubling).
4. `cd plan/2026-11-13b/measure && npm install && node walk.js 8000 75000` (about 8 minutes).
5. `python measure/analyze.py`. It writes `measure/report.txt`; compare the per-step table and the "Identical DB
   query repeated INSIDE one request" section with [baseline-report.txt](baseline-report.txt).

Record each phase's numbers in `IMPLEMENTED.md` as a row: page, API requests, DB queries, before, after.

## 4. Phases

Ordered by gain per effort. Each phase stands alone and can ship alone.

### Phase 1: load a scene once per request (R1, R2) (API)

**Approach (recommended):** a request-scoped read memo in the repository layer. A context variable, opened by
`RequestLogMiddleware` (the same place the DB counter lives), keyed by `(repo, method, args)`, for the idempotent
getters the scene loaders use: `scenes.get`, `shots.list` (by scene), `lines.list` (by scene), `episodes.get`,
`scenes.list` (by episode), `scene_looks.get`, `canon_looks.list`. **Any write through any repo clears the whole memo
for that request** (simple and safe: a write-then-read in one request always sees its write). Outside a request (workers,
scripts, tests that call repos directly) there is no memo, so behaviour is unchanged.

- Callers must not mutate returned rows. Return a copy from the memo (`copy.deepcopy` or `dict(row)` for flat rows);
  measure the cost. `handoff._probe_generated` mutates `take` rows, and takes are not memoised.
- Alternative if the memo feels too implicit: change `page.py` to call `production.load` once and pass the loaded
  rows into `scenes.view` and `structure.get_episode` (new optional parameters). It fixes `/page` only, not R2.

**Tests:** a fake-repo counter test: `/page` makes each listed read once; a write between two reads in one request
re-reads. Existing `tests/api` stay green.

**Target:** `/page` from 20 to at most 14 queries. Scene director total from 50 to about 44. Most of the shot routes'
repeats go only once phase 5 shares one request for them.

### Phase 2: read only the planner the production uses (R3) (interface, small API add)

`/page` (the `SceneView`) gains `planners_with_plans: list[str]`, the planner columns that are not `{}` (computed from
the scene row it already has, no new query), and the production's `shot_planner` if the view does not already carry it.
The director page renders the slot for `settings.shot_planner`, plus any planner that already holds a plan for this
scene, and skips the others (no request).

**Decision for the person (D1):** should a scene planned earlier by another planner still show that planner's panel?
Recommended: yes, show it, so a stored plan never disappears from view.

**Target:** scene director from about 44 to about 35 queries; 3 fewer requests.

### Phase 3: looks in one read (R4) (API + interface)

`/page` already loads `canon_looks` for the production and `scene_looks` for the scene. Add to its answer, for the scene's
cast only, each character's looks and the scene's chosen look (the shape `getSceneCanon` builds today). Remove the
per-character `/canon/{id}/looks` calls and the `/scenes/{id}/looks` call from the director and workspace pages. The
single routes stay for the canon pages and for re-reads after a write.

**Target:** scene director from about 35 to about 26 queries; requests drop by 1 + one per character.

### Phase 4: one wave of server reads (R5) (interface)

In the director, workspace and production pages, start every independent read in the first `Promise.all`: add
`getCurrentUser()` and `getMonthlyUsage()` there (`api()` is wrapped in React `cache`, so `AppHeader` then reuses the
same promise). Start the planner and packet reads at the top as promises and pass them to the Suspense slots
(`use(promise)`), so they run while `/page` runs. After phase 3 the scene's canon no longer needs a second wave.

**Target:** no query-count change; the trace's start times for one page open fall within about 100 ms of each other,
and the page's total server time drops. Report the before and after server time (the sum of the `ms` column for the
step, and the wall time from the first request to the last).

### Phase 5: the Generate Video card reads through the cache, and later (R6) (interface, small API add)

- `fetchShotTakes` becomes a `useQuery` with key `handoff(shotId)`, seeded with `initialData` from the server page
  where the page already read `/handoff`.
- The two render plans become one request: `GET .../render-plan?both=true` returns `{take, draft}` from one load (or
  phase 1's memo makes two calls share it; one request is still better). Use `useQuery`, `enabled` only when the card
  is open, or when the person hovers or presses Generate. **Decision D2:** read the plan on page open (shows "blocked"
  reasons at once) or only when the card is opened? Recommended: when the card is visible, via `IntersectionObserver`,
  so the shot workspace opens without it.
- `useOnActivity` then invalidates the `handoff(shotId)` query instead of calling `loadTakes` by hand.

**Target:** shot workspace from 34 requests and 111 queries to at most about 15 requests and 45 queries (dev).

### Phase 6: the scene cost (R7) (API)

- Keep the price list in memory for 60 s, cleared by `PUT /v1/prices` (prices are append-only with `valid_from`, so the
  rows are safe to hold).
- The fallback history from all productions (`recent_usage(None, ...)`): hold it in memory for 10 min. It is an
  average used for an estimate, and is only needed while a production has none of its own.
- Use phase 1's memo for the scene rows (`/cost` re-reads the scene, shots, lines, frames and prompts today).
- The interface asks for the cost after the page shows (a client `useQuery`, not part of the server render) so it
  never delays the page.

The response stays the total and two flags. **Target:** `/cost` from 19 to at most 10 queries, and off the critical path.

### Phase 7: the small repeated reads (R8) (API + interface)

- `/v1/usage`: hold the month's percentage in memory 60 s per process, cleared by `api.cache.job_ended()` (the only
  thing that moves it is finished model work).
- `scene-chat-choice.tsx`: use `useSableStatus(productionId)` instead of calling `getSableStatus` in an effect.
- `/v1/me` and `/access` are already cheap (0 queries thanks to the 15 s cache): leave them.

**Target:** Sable status 1 read per page load; `/v1/usage` 0 queries on a cache hit.

### Phase 8: list reads take only the columns they use (R9) (API)

For `/overview` and `/canon/usage` (and any other production-wide list of scenes or shots), add repo methods that
select named columns, e.g. `scenes.list_light(production_id)` and `shots.list_light(production_id)`, and use them where
the route only needs ids, numbers, titles, status, durations, speakers and so on. Keep `select=*` where a whole row is
truly used (the scene loaders). Add the methods to `tests/api/fakes.py`. Check each mapper the route feeds, so no field
it reads is dropped.

**Target:** the same query counts with smaller rows. Measure bytes per route from `/debug/traffic`
(`scripts/traffic_scene.py` prints them) before and after, on a production with real planner output if one exists by
then.

### Phase 9: take posters (R10) (schema + API)

**Decision D3** (schema, the person's): either

- **(a, recommended)** allow `image/webp` in the `takes` bucket (`schema_v24.sql` + `upgrade_v23_to_v24.sql` +
  migration): one line, and posters work as `CLAUDE.md` describes; or
- (b) store posters in the `frames` bucket, which allows WebP, and change `poster_path` and every reader.

Either way:

- `_take_view` returns `poster_url` only when the poster is known to exist. Record the result of `assembler.poster`
  (new `takes.poster_path`, nullable, in the same v24 pair), or check the disk cache.
- `file_cache` remembers a 404 for 10 minutes, so a missing file is not asked for again on every view.
- `scripts/backfill_thumbs.py` makes the missing posters once, after (a) or (b) is applied.

### Phase 10: measure again and write it down

Run section 3 on both `next dev` and `next start`; write the before and after table into `IMPLEMENTED.md`. The
baseline's dev numbers are the comparison point. Expected end state (dev): scene director about 25 queries (from 50),
shot workspace about 45 (from 111).

## 5. Decisions for the person

| # | Question | Recommended |
|---|---|---|
| D1 | Keep showing an older planner's panel when the scene holds its plan? | Yes |
| D2 | Read the render plan when the page opens, or when the Generate card is visible? | When visible |
| D3 | Posters: allow WebP in `takes`, or move posters to `frames`? | Allow WebP in `takes` (v24) |
| D4 | Keep the `DEBUG_TRAFFIC_LOG` trace (off by default, local only) in the codebase? | Yes; it is how phase 10 measures |

## 6. Left in the dev database by the measurement

In the test production only: 3 "[traffic seed]" episodes with their scenes, shots, lines, frames, prompts and takes,
6 canon entities (C01-C04, L01, L02), 312 storage objects, and the user `traffic-bot@hiru.test`. Keep them until
phase 10 is measured, then run `python plan/2026-11-13b/measure/seed.py clean`.
