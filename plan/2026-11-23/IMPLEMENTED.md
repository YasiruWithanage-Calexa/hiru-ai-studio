# plan/2026-11-23 — what was built (2026-11-23)

Built offline, both repos, uncommitted. No model call was made. Schema v29 is NOT applied to the hosted project (phase 8
is the person's). Decisions taken as recommended unless the person says otherwise: **D1** admins only, **D2** UTC months,
**D3** no chart, **D5** corrected prices backdated (by the migration only), **D6** the admin price list keeps provider
rates, **D7** retry stays 20 %, **D8** margins change by editing the file and redeploying.

## Phase 0 — prices confirmed on the official pages (read-only, 2026-11-23)

Read `developers.openai.com/api/docs/pricing` and `aistudio.google.com/docs/pricing` (ai.google.dev redirects there).
Every rate of PLAN §3.3 was confirmed, with two corrections folded in:

| | confirmed | change from the plan's table |
|---|---|---|
| gpt-5 / mini / nano | 1.25/0.125/10 · 0.25/0.025/2 · 0.05/0.005/0.40 | none |
| gpt-5.5 | 5.00 / 0.50 / 30.00, **long 10.00 / 1.00 / 45.00** | long tier added (not in the plan) |
| gpt-6.1-sol | 2.00 / 0.10 / 10.00, long 4.00 / **0.20** / 15.00 | cached long confirmed 0.20 |
| gpt-6.1-terra | 1.00 / 0.05 / 5.00, long 2.00 / 0.10 / 7.50 | none |
| text-embedding-3-large / small | 0.13 / 0.02 | none |
| gpt-image-2 | text 5.00 (cached 1.25), pictures 8.00 (cached 2.00), out 30.00 | cached rates apply only through the Responses API (we use the images API, so cached is ~0) |
| Gemini Omni 1.2 Flash | in 1.50; **text incl. thinking 9.00**; video 12.00; 1,931 / 5,792 / 8,688 tokens a second at 360p / 720p / 1080p = 0.023 / ~0.07 / 0.104 a second | "9.00 includes thinking" settled |

Google also says requests to `gemini-omni-1.1-flash` route to 1.2 from 2026-12-03 at 1.2 rates (we no longer send 1.1).
Not done: the read-only counts on the hosted project (rows a month, rows with no production, the first 1.2 render).
The Omni 1.2 per-second rows are dated 2026-11-19 (plan/2026-11-19's switch); the person can move that date if the first
1.2 render was earlier.

## What changed

**Margins** — `src/api/margins.yaml` (llm 10, image 20, video 30, retry 20, from 2026-01-01), read by
`api/margins.py` (`load` / `install`, at API start-up) and checked by `contracts.costs.parse_margins` (dated entries,
percent → basis points from text, every fault an error). **Moved from the plan's `src/libs/contracts/`**: `contracts`
may import only pydantic and the standard library (every function bundles it; `tests/test_isolation.py`), so the file
and its YAML reading live with the API, the only reader. `margins()` raises until they are installed (never 0 %); the
root `conftest.py` installs them for every test. `MARGIN` / `RETRY_MARGIN` constants are gone. `with_margin(micros,
kind, at)` applies the entry in force when the work was made. PyYAML is now a main dependency; the yaml ships as `api`
package data.

**Money rules** (`contracts/costs.py`) — new price fields (`image_input_micros`, `cached_image_input_micros`,
`text_output_micros`, `long_context_from`, `long_*_micros`) and kind `video_tokens`; `tokens_actual` bills pictures and
long calls; `picture_split` (an older row = all pictures; cached off text first); `video_actual` prices Omni by its tokens
(`video_tokens` × 12 + `thought_tokens` × 9 + input × 1.50), else per second; a named Omni 1.1 row keeps 1.1 renders at
$0.10/s. `SEED_PRICES` = the confirmed list; gpt-6.1-terra moved in from `UNSEEDED_PRICES`.

**Meter** — `adapters/images.py` and the legacy `frame_render/engine/image.py` read `usage.input_tokens_details`
(`image_tokens`, `cached_tokens`) and write `image_input_tokens`; both writers retry a row without the column on a
database before v29 (no switch). `video_render` stores `video_tokens` and `thought_tokens` (`omni.thought_tokens`).

**Schema v29** — `Database/upgrade_v28_to_v29.sql`, `Database/schema_v29.sql`: `token_usage.image_input_tokens`, the
price columns and kind, 9 price rows (backdated corrections at 2026-01-01 00:00:01 so they win over the v17 rows; Omni
1.2 per-second rows from 2026-11-19), and `public.token_usage_totals(...)` (service role only).

**Usage API** — `contracts/usage_totals.py` (month bounds, price/margin boundaries, `group_rows` = the SQL's twin,
`price_month`), `api/services/usage_totals.py` (RPC first, API-side sums before v29, 60 s cache cleared when a job ends),
`api/routers/admin_usage.py` (`GET /v1/admin/usage?month=`, admin only, final micro-dollars only). `PUT /v1/prices`
takes `video_tokens` and sends v29 columns only when set.

**Interface** — `/settings` (layout + `SettingsSidebar`: Usage, Prices), `/settings/usage` (`features/usage-report`:
summary tiles, production table, month picker, unpriced note), `/settings/prices` (the price panel, now showing picture
input, long context and `video_tokens`, and accepting them), `/prices` → permanent redirect, avatar button "Settings",
shadcn `Table` added and re-themed. `CLAUDE.md` rule and `docs/ARCHITECTURE.md` updated.

## Found while building

- **Summing broke the cached-picture rule.** On a real Postgres (throwaway `pgserver`, 400 random rows) the month priced
  from sums was $0.0275 off pricing each row: "cached tokens come off the text first" is not linear. Fixed by splitting
  per row before summing (`cached_image_input_tokens`, cached capped at input) in SQL, in `group_rows` and in the fake;
  after the fix the difference was 5 micro-dollars on 132 rows (rounding). A unit test now pins the case.
- **The secrecy scan read nothing at first.** This FastAPI nests included routers, so `app.routes` held one route; the
  test now scans the OpenAPI schema (>500 response fields) and fails if it reads too few.

## Checks

- Backend: `ruff` clean on every file this plan touched (5 older E501 findings elsewhere remain); `mypy` clean (1149
  files); `tests/test_isolation.py` green (it caught the first version's `import yaml` in contracts). Full suite: 68
  failed / 6,221 passed on this tree vs 44 failed at a clean HEAD worktree. Every failure that is not also at HEAD (25)
  passes when run without the repo's local `.env` (the HEAD worktree has none; its URLs use port 8001), so none comes
  from this plan. The 44 fail at HEAD too (Adam, Raphael, script_split, parity, ...).
- SQL: upgrade applied twice to a throwaway Postgres 16 holding v28's `token_usage` + `prices` + the v17 seed: 24 price
  rows both times; the database picks the intended row for gpt-image-2, gpt-6.1-sol, Omni 1.2 (before and after
  2026-11-19) and Omni 1.1; `token_usage_totals` equals `group_rows` exactly.
- Interface: `next typegen`, lint and `tsc` clean; vitest 568/569 — the one failure is
  `raphael-panel.test.tsx` ("reads a result from an older version"), in code this plan does not touch.
  `format:check` warns on 70 files, all Windows line endings in this checkout (each is clean with CR removed).

## The person's (phase 8)

1. Apply `Database/upgrade_v28_to_v29.sql` on the hosted project.
2. Redeploy the API (it now needs PyYAML and reads `margins.yaml`).
3. Open Settings → Usage for November; add a price for anything it lists as unpriced.
4. Compare the month with the OpenAI and Google consoles by eye: our total ÷ (1.1 to 1.3) should be near the bills.
5. Expect every "Scene ≈ $X" to rise once (margins 10/20/30 instead of 0/5/10).
