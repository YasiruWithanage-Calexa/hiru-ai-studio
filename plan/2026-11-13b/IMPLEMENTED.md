# plan/2026-11-13b: what is built

## Phase 1: one read per request (R1, R2): built offline, not yet measured

- `src/api/repositories/memo.py`: a per-request read memo. `RequestLogMiddleware` opens it; `build_supabase_repos`
  wraps every repository in `MemoRepo`. Memoised getters: `scenes.get/list`, `shots.get/list`, `lines.list`,
  `episodes.get/list`, `scene_looks.list`, `looks.list_for_production`, `canon.list` (`MEMOISED`).
- Deviations from the plan's wording: `canon.list` is also memoised (`/page` read it twice); concurrent identical reads
  share one query; a read that began before a write never stores its answer; a method name not recognised as a read
  counts as a write and clears the memo (fail safe: a redundant query, never a stale row). Callers get deep copies.
- Fakes are not wrapped (tests/api/fakes.py unchanged); `tests/api/test_page.py::test_page_reads_the_scene_rows_once`
  wraps them to count, and `tests/api/test_read_memo.py` covers the mechanism.
- Checks: ruff (the two E501 in `tests/api/test_production.py` and `test_thumbs` needing PIL were already failing),
  mypy clean, `tests/api` the same 7 failures with and without this change.
- Measured 2026-11-13 (section 3, `next dev`, the same walk as the baseline: 276 API requests both times). Report:
  [phase1-report.txt](phase1-report.txt). **Target met: `/page` 20 -> 14 queries** (min 13, max 16), and no query is
  repeated inside any request any more (baseline: 6 repeats in every `/page`).

  | Page open | DB queries before | after |
  |---|---:|---:|
  | Scene director | 50 | 45 |
  | Shot workspace | 111 | 101 |
  | Shot production | 97 | 89 |
  | Shot handoff | 31 | 25 |
  | Stepping to the next shot (handoff) | 32-34 | 26-27 |
  | Whole walk | 827 | 733 (-11 %) |

  `/handoff` (10), `/render-plan` (8-9) and `/cost` (19) are unchanged: their repeats are ACROSS requests, which a
  per-request memo cannot share; phases 5 and 6 take those. Timings move with the hosted database's latency (the same
  route varies 2x between runs), so they are not compared. No new errors: the five `/packet` 404s are in the baseline too
  (by design: the seeded scenes have no breakdown).

## Phases 2 and 3: the planner and the cast's looks come with `/page`: built, measured

- API: `ScenePage` (`routers/page.py`) gains `shot_planner`, `planners_with_plans` (a planner column counts only when its
  own planner wrote it, the test each planner's route uses), `cast_looks` (character id -> the `/canon/{id}/looks`
  answer, scene cast only) and `scene_looks`. No new reads except one `episodes.list` (the looks' `episode_count`); the
  rest are already in the request's memo. The fields are on `ScenePage`, not `SceneView`, so `view` stays equal to the
  single route's answer (`test_page.py` checks both).
- Interface: `getSceneRaw` carries them as `raw.extras`; `getSceneCanon` is now a plain function over them (no requests);
  the director page draws the production's planner plus any planner holding a plan for the scene (D1 = yes, the
  recommended default; not yet confirmed by the person), the others make no request. The workspace page uses the same looks.
- Measured 2026-11-13 (`next dev`; [phase3-report.txt](phase3-report.txt)):

  | Page open | API requests before | after | DB queries before (phase 1) | after |
  |---|---:|---:|---:|---:|
  | Scene director | 21 | 15 | 45 | **29** |
  | Shot workspace | 34 | 31 | 101 | 95 |

  `/page` 14.7 queries on average (was 14: one `episodes.list` for the looks). Only the production's planner route is
  called now (was four). Still open for later phases: `/sable` 3x per page (phase 7), `/render-plan` and `/handoff` 2-4x
  (phase 5), `/cost` 19 (phase 6).
- Interface `npm run test`: one failure in `raphael-panel.test.tsx` (caps now include 1.0 from an earlier commit), not
  from this work. Type-check and lint clean.

## Phase 5: the Generate Video card reads through the cache, and later: built, measured

- API: `GET .../shots/{id}/render-plans` (`routers/renders.py`) returns `{take, draft}` from ONE `load_shot`; each half
  equals its single route (`test_renders.py`). It costs 8.5 queries for both plans (one plan was 8-9). The single route stays.
- Interface: `GenerateVideoCard` reads the plans and the shot's takes with `useQuery` (`queryKeys.renderPlans`,
  `queryKeys.handoff`), enabled only once the card is on screen (D2 = when visible, the recommended default, not yet
  confirmed by the person; no `IntersectionObserver` = read at once). `useOnActivity` invalidates the handoff query; a 409
  invalidates the plans. No `initialData`: the workspace and production pages never read `/handoff` on the server, so there
  is nothing to seed (the 2x `/handoff` in the baseline was Strict Mode).
- Measured 2026-11-13 (`next dev`; [phase5-report.txt](phase5-report.txt)):

  | Page open | API requests before (phase 3) | after | DB queries before | after |
  |---|---:|---:|---:|---:|
  | Shot workspace | 31 | 23 | 95 | **60** |
  | Shot production | 19 | 11 | 91 | 56 |

  The plan's target for the workspace (about 15 requests, 45 queries) is not met: what is left is `/sable` 3x (phase 7),
  `/scenes/{id}/cost` 19 queries (phase 6) and the card's reads, which now happen only when it is seen.
- Interface tests: the card's tests use a query provider and the new client call, plus one test that nothing is read
  before the card is visible. Same single unrelated `raphael-panel` failure.

## Phase 6: the scene cost: partly built, target not met

- `SupabaseCosts` holds the price rows 60 s (`add_price` clears them; a failed read is never kept, so the in-code prices
  cannot be held by an error) and the cross-production usage history 10 min (`recent_usage(None, ...)`; a production's own
  history is read every time). Copies are returned. Nothing computed (no total) is cached. `tests/api/test_costs_cache.py`.
- Measured: `/cost` 19 -> 16 to 19 queries (avg 17.5 over 2 calls; 19 on the first, after a restart). **The target (10) is
  not met**: 9 of the queries are `production.load` (the scene, shots, lines, canon, frames, prompts, episode, looks, picks)
  which the cost needs for each shot's state, and 4 are the scene's and the episode's `token_usage` reads. Getting to 10 needs
  a lighter loader for costs, which would be a new code path next to the Production panel's; not done.
- **Not done, on purpose:** the plan's "ask for the cost from a client `useQuery`". The slot already streams inside
  `<Suspense>` (the page shell does not wait for it), and a client query would not re-read when a batch action refreshes the
  page, so the figure could be stale (it "reloads with the page" today). The person may want it anyway.

## Phase 7: the small repeated reads: built, measured

- `SupabaseUsage` holds the month's token sum and the budget 60 s; both are cleared by `api.cache.job_ended()`, the sum also
  when this process records a call, the budget by `set_budget`.
- `scene-chat-choice.tsx` uses the shared `useSableStatusRead` (new, next to `useSableStatus`) instead of its own call; the
  remembered chat pick is read once the status has answered, so the server render never depends on it.
- Measured 2026-11-13 ([phase7-report.txt](phase7-report.txt)): `/v1/usage` 2.1 -> 1.4 queries per call (one cache miss per
  minute or per ended job); `/sable` is read once per page (no step has a repeated API URL any more: `dupAPI` is 0 on every
  step, was 5 on the workspace). Scene director 15 -> 11 requests, shot workspace 23 -> 19, queries unchanged (29 and 60).

## Phase 4: one wave of server reads: built (no query change, timing not separately compared)

- `warmHeader()` (`src/lib/api/warm-header.ts`) starts `/v1/me` and `/v1/usage` at the top of the director, workspace and
  production pages, beside the page's own reads; `api()` shares one request per path per render, so `AppHeader` takes the
  same promises instead of asking after the page finished. The director also starts the breakdown packet read at the top
  (it needs only the URL) and its slot awaits that promise.
- Not done: starting the four planner reads at the top. After phase 2 only the production's planner is read, and it needs
  the `/page` answer to be known, so it already starts as soon as the page's first reads return.
- Timings on the hosted dev database move 2x between runs, so no before/after time is claimed. What the trace shows: no
  step makes a repeated API call, and `/v1/me` and `/v1/usage` now run in the page's first wave.

## Phase 8: list reads take only the columns they use: built

- `scenes.list_light(production_id, episode_id=None)`, `shots.list_light` (`SCENE_LIGHT` / `SHOT_LIGHT` in
  `repositories/__init__.py`) and `shots.list_pinned` (`id, scene_id, pins:design->pins`, returned as `design: {pins}`, which
  is all `canon/usage` read). Used by `/overview`, `/structure`, `/episodes`, `/canon/usage`, the episode route and the
  scene view's sibling list. The fakes return ONLY those columns, so a mapper that reads another field fails its test.
  `list_light` for scenes is memoised in the request like `list`. The scene loaders keep `select=*`.
- Measured on the dummy rows (the trace's query strings): the production-wide lists now select the named columns; the
  dummy rows are 15.8 KB vs 3.0 KB (scenes) and 63 KB vs 11 KB (shots) per production-wide read, from the plan's
  baseline. No production with real planner output exists in the dev database, so the real saving (far larger) is not
  measured. The `pins:design->pins` select is accepted by the hosted PostgREST (`/canon/usage` answers 200).

## Phase 9: take posters: built; schema v24 NOT applied

- D3 = (a), the recommended default (not yet confirmed by the person): `Database/schema_v24.sql` (whole), 
  `Database/upgrade_v23_to_v24.sql` and `supabase/migrations/20261113062313_take_posters.sql` add `takes.poster_path` and
  allow `image/webp` in the `takes` bucket. **Not verified:** the three-dump comparison CLAUDE.md asks for needs the local
  Supabase stack, which was not run; the v24 file is v23 with the header, one column, its comment and one array changed. (First written as v22 on v21;
  renumbered to v24 on top of the v22 and v23 pairs that landed meanwhile, which are unchanged.)
- `_take_view` returns `poster_url` only when the row has a `poster_path`; the upload route records the path when the
  assembler made the still, and sends the column only then (so the API still works on a v21 database). The video_render
  function makes no still, so generated takes show none until `scripts/backfill_thumbs.py --apply --posters`, which now
  also records `poster_path` (needs v24).
- `file_cache` remembers a 404 for 10 minutes per process; forgotten when this process stores that path
  (`SupabaseStorage.upload`) and when a job ends (`job_ended()`, because a worker may have just written it).
- Tests: `test_file_misses.py`, and a poster_url test in `test_handoff.py`.

## Phase 10: measured again

Walk on `next dev` (full report [final-dev-report.txt](final-dev-report.txt)); the whole trace has no 5xx and no repeated
query inside a request (the five `/packet` 404s are by design).

| Page open | API requests: baseline -> now | DB queries: baseline -> now |
|---|---:|---:|
| Scene director | 21 -> 11 | 50 -> **29** |
| Shot workspace | 34 -> 19 | 111 -> **60** |
| Shot production | 19 -> 11 | 97 -> 53 |
| Shot handoff | 6 -> 6 | 31 -> 27 |
| Production overview | 5 -> 5 | 9 -> 7 |
| Canon / canon entity | 8 / 9 -> 8 / 9 | 13 / 17 -> 12 / 16 |

Targets: scene director about 25 queries (got 29), shot workspace about 45 (got 60). What keeps them above: `/page` at 15
queries, and `/cost` at 17 on the workspace (phase 6).

**`next start` numbers: not produced.** `npm run build` fails in this repository state, with or without these changes
(`CLIENT_HOOK_DYNAMIC` from `ActivityProvider` while prerendering a page; checked by stashing the interface changes: it
fails on `/canon` instead of `/activity`). The dev server on :3030 was left running. Strict Mode doubling is therefore still in
the dev numbers above (the walk's counts show no doubled calls any more, because each read is in the shared cache).

`python plan/2026-11-13b/measure/seed.py clean` (section 6) has NOT been run: the test data is still in the dev database.
