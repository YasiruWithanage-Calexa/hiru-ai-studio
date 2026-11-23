# Usage in USD: final prices, secret margins, current provider rates (plan/2026-11-23)

Revision 2 (2026-11-23). Nothing in this plan is built. Revision 1 showed provider cost; the person then set the
studio's margins and asked that users only ever see the **final price**. This revision:

1. moves the margins into one **YAML file** that is easy to change, dated so a change never re-prices past work, and
   never sent to the interface (§3.1);
2. prices everything as **provider cost x (1 + margin)**: the new Settings → Usage page and the existing scene
   estimate ("Scene ≈ $X") alike (§3.2, §3.6);
3. brings the **price list up to date** (Gemini Omni 1.2 Flash, gpt-6.1, gpt-image-2, ...) and prices Omni by the
   tokens it reports, not a guessed per-second rate (§3.3);
4. closes the meter gaps that made the bill inaccurate: image input split into text and image tokens, the long-context
   rate, Omni thinking tokens (§3.4);
5. adds the admin **Settings** area with **Usage**: the month's total and each production, split into Chat &
   decisions, Image generation and Video generation, in USD (§3.5).

Checking the meter against the providers' invoices is later (§8). Every phase is offline ($0) except phase 0's reading
of the official price pages. Applying schema v29 to the hosted project is the person's. Read this file whole, then
`src/libs/contracts/costs.py`, `src/api/services/costs.py` and `plan/2026-11-06d/PLAN.md` (scene cost).

## 0. Rules for the chat that builds this (read before anything)

- **The margins are secret.** No API response, page, error, audit row, test snapshot sent to the interface, or log
  line at INFO or above carries a margin, a provider cost, or anything a margin can be worked out from. Users (admins
  included) see final prices only. The margins exist in `margins.yaml` and in memory in the API process, nowhere else.
  A test scans every response model for margin / cost fields (§5 phase 2).
- **One set of money rules.** Every figure goes through `contracts.costs` (`price_for`, `kind_of`, `render_billed`,
  margins), in integer micro-dollars. Never a second pricing function, never a float summed.
- **A missing price is shown, never zero and never a guess.** The page and the scene figure say a price is missing.
- **No paid call.** Nothing calls a model. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **Admin only** for Settings → Usage (D1). Members see only the monthly percentage in the top bar.
- **Two repos.** Backend: this repo (`.venv/Scripts/python.exe`, Python 3.12). Interface:
  `..\hiru-ai-studio-interface`; its `CLAUDE.md` and `AGENTS.md` are binding.
- Write code with the Write or Edit tool. Read `git status` / `git diff` of a file before editing it (other plans'
  work is uncommitted). Never stash or reset the person's tree.

## 1. What exists today

| Piece | Where | Today |
|---|---|---|
| Margins | `contracts/costs.py` `MARGIN = {"text": 0, "image": 500, "video": 1000}`, `RETRY_MARGIN = 2000` (basis points) | hard-coded; applied only by the scene estimate |
| A row per model call | `token_usage` | provider's counts; `output_tokens` already includes reasoning |
| A row per picture | `token_usage`, phase `frame_render.image` (`adapters/images.py`) | ONE `input_tokens` (text + reference images together), no cached part |
| A row per video | `video_renders.usage` | `prompt_tokens`, `completion_tokens` (Omni's video, ~99 % of the money, plus thinking), `seconds_rendered`, `takes_made`, `billed` |
| Omni's price | `SEED_PRICES` `_vid("omni_flash", "720p", "0.10")` | a guess from the 1.1 preview; no 360p / 1080p row |
| Long context | `tokens_actual` | one rate whatever the prompt size (gpt-6.1-sol bills 2x input / 1.5x output above 272K) |
| Admin price list | `GET/PUT /v1/prices`, interface `/prices` | provider rates (no margin) |
| Spend over a month | nothing | |

## 2. What the person asked (2026-11-22/23)

- Settings → Usage: total and per production, split into Chat & decisions (LLM), Image generation, Video generation,
  in USD. Our meter first; the invoice check later.
- Margins: **LLM +10 %, image +20 %, video +30 %**. Never shown; users see the final price.
- The margins in an easy-to-change YAML file.
- The estimate (scene figure) uses the same margins.
- Current prices for Gemini Omni 1.2 Flash and the other services, so the dashboard bills accurately.

## 3. The design

### 3.1 `margins.yaml`

`src/api/margins.yaml` (built: moved from `src/libs/contracts/`, see IMPLEMENTED.md; read by `api/margins.py`):

```yaml
# INTERNAL AND SECRET. Never shown in the interface, never sent by the API, never logged above DEBUG.
# Percent added on top of what the provider charges. The final price = provider cost x (1 + percent / 100).
#
# To change a margin, ADD an entry with a later `from` date; never edit an old one. Work is priced with the
# entry in force when it was made, so a change never re-prices past spending. Then redeploy the API.
# Up to two decimals (12.5 is fine). 0 is allowed. Every bucket must be present in every entry.

margins:
  - from: 2026-01-01
    llm: 10        # Chat & decisions: every model call that is not a picture (chat, planners, readers, checks, embeddings)
    image: 20      # Image generation: first frames, boards, face and look sheets
    video: 30      # Video generation: every billed render

estimate:
  retry: 20        # Scene ≈ $X only: added to the part still to make (renders that will be redone). Not on spent work.
```

- Loaded once per process by `contracts.costs.margins()` (`yaml.safe_load`, validated by a pydantic model: dates in
  order, every bucket present, 0 <= percent <= 500, at most 2 decimals). Percent is converted to basis points from the
  decimal STRING (as `micros_of` does), never through a float.
- **A missing or invalid file stops the API from starting** (a clear error naming the file and the fault). Never a
  default of 0: a silent zero margin would under-bill everything.
- `margin_at(bucket, when)` returns the basis points of the entry in force at `when`. `with_margin(micros, bucket,
  when)` replaces `with_margin(micros, kind)`; `with_retry` reads `estimate.retry`.
- Bucket names: `llm` (was `text`), `image`, `video`. `kind_of` keeps returning `text` / `image` / `metered`; one
  mapping `BUCKET_OF_KIND = {"text": "llm", "image": "image"}` joins them.
- `MARGIN` and `RETRY_MARGIN` constants are removed; `tests/contracts/test_costs.py` reads the file instead of
  asserting numbers.

### 3.2 Final price everywhere

`final = provider cost + margin` per item, rounded half-up to the micro-dollar, then summed. Applied once, in
`contracts.costs` only (`cost_tokens`, `cost_render`, the estimates). Who uses it:

| Figure | Before | After |
|---|---|---|
| Scene ≈ $X (spent part) | text +0 %, image +5 %, video +10 % | llm +10 %, image +20 %, video +30 % (dated) |
| Scene ≈ $X (to finish) | same, then +20 % retry | same new margins, then `estimate.retry` (20 %) |
| Settings → Usage | (new) | final prices only |
| Admin price list `/prices` | provider rates | unchanged: provider rates (D6) |
| `/v1/usage` percentage | tokens / token budget | unchanged (§7) |

`tokens_actual` and `video_actual` (provider cost, no margin) stay for the live scripts and tests; their results never
leave the server.

### 3.3 Prices (schema v29 seeds them; candidates to confirm in phase 0)

Read 2026-11-23, mostly from third-party listings; **phase 0 checks each against the official page before seeding**
(openai.com/api/pricing, ai.google.dev/gemini-api/docs/pricing) and records the date and URL in `note`. USD.

**OpenAI, per million tokens (standard tier)**

| model_prefix | input | cached input | output | change |
|---|---|---|---|---|
| gpt-5-nano | 0.05 | 0.005 | 0.40 | same |
| gpt-5-mini | 0.25 | 0.025 | 2.00 | same |
| gpt-5 | 1.25 | 0.125 | 10.00 | same |
| gpt-5.5 | 5.00 | 0.50 | 30.00 | same; one source says 3.00 / 20.00: **confirm** |
| gpt-6.1-sol | 2.00 | 0.10 | 10.00 | same, **plus long context: above 272K input, 4.00 input / 15.00 output** (cached x2 assumed: confirm) |
| gpt-6.1-terra | 1.00 | 0.05 | 5.00 | **new in the database** (was code-only); long context 2.00 / 7.50 above 272K |
| text-embedding-3-large | 0.13 | 0.13 | 0 | same |
| text-embedding-3-small | 0.02 | 0.02 | 0 | same |
| gpt-image-2 | **text 5.00, image 8.00** | **text 1.25, image 2.00** | 30.00 | **split** (today one input rate of 8.00 and cached 2.00) |

**Google, Gemini Omni 1.2 Flash** (`gemini-omni-1.2-flash`, per million tokens)

| | rate | note |
|---|---|---|
| input (text + pictures) | 1.50 | |
| video output | 12.00 | the video itself: what `completion_tokens` mostly is |
| text / thinking output | 9.00 | some listings give 12.00 for all output: **confirm** |

Per-second rates Google quotes for 1.2 (used only when a render has no token counts, and for estimates):
360p **0.023**, 720p **0.07**, 1080p **0.104** (was one 0.10 row for 720p only).

**Omni is priced by its tokens.** A render whose `usage` has `completion_tokens` is priced as
`prompt_tokens x input + video_tokens x video output + thought_tokens x text output` with a new price kind
`video_tokens` matched by `model` (`gemini-omni-1.2-flash`). A render without token counts (older rows, an engine that
reports none) falls back to `seconds x takes x video_second` as today. Both are provider cost; the video margin then
applies.

**Retired engines** (Veo 3.1, Omni 1.1) keep their rows so old renders keep their price.

**Dating the new rows (D5).** A price applies to work made after its `valid_from`. To bill past work accurately, the
v29 migration dates each corrected row from when that rate really began for us (Omni 1.2: the day the product switched
to it, 2026-11-19, from `video_renders`; gpt-image-2 split and long context: 2026-01-01 since they were always billed
that way). `PUT /v1/prices` still refuses a past date; only a migration may backdate, and it says so in `note`.

### 3.4 Meter fixes (what the provider bills that we do not record yet)

| Gap | Fix | Schema v29 |
|---|---|---|
| Image input is one number | `adapters/images.py` reads `usage.input_tokens_details` (`text_tokens`, `image_tokens`, `cached_tokens`) and writes `input_tokens` (all), `image_input_tokens`, `cached_input_tokens` | `token_usage.image_input_tokens int not null default 0`; `prices.image_input_micros`, `prices.cached_image_input_micros` |
| Long context | `tokens_actual`: a row whose `input_tokens` is above the price's `long_context_from` is priced at the long rates | `prices.long_context_from int not null default 0` (0 = none), `long_input_micros`, `long_cached_input_micros`, `long_output_micros` |
| Omni thinking billed at the video rate | `video_render/engine/omni.py` `usage_tokens` returns video and thought tokens apart; `render.py` stores `usage.video_tokens`, `usage.thought_tokens` | none (`video_renders.usage` is jsonb) |
| Omni per-second guess | §3.3 | `prices.kind` check gains `video_tokens` |

Old rows keep working: no `image_input_tokens` → all input at the text rate (what it would have cost at most at the
image rate is not guessed; the page shows the figure as it is). No `video_tokens` → `completion_tokens` at the video
output rate.

### 3.5 Settings → Usage

**API** (admin only): `GET /v1/admin/usage?month=2026-11` (default the current month; before 2026-01 or in the future is
422).

```
{ "currency": "USD", "month": "2026-11", "as_of": "…",
  "total":       {"llm_micros": …, "image_micros": …, "video_micros": …, "total_micros": …},
  "productions": [ {"production_id": "…", "name": "Love Hour", "llm_micros": …, …}, …,
                   {"production_id": null, "name": null, …} ],          (no production: last, only if not zero)
  "missing":     [ {"what": "some-model", "bucket": "llm", "count": 14} ],
  "complete":    true }
```

Every `*_micros` is a FINAL price. There is no field for cost, margin, rate or token count.

**Pricing a month without reading every row (schema v29 RPC).** `public.token_usage_totals(since, until, boundaries
timestamptz[], image_phases text[], metered_prefixes text[], long_from int)` returns sums per `(production_id, model,
kind, interval, long)`: `calls`, `input_tokens`, `image_input_tokens`, `cached_input_tokens`, `output_tokens`.
`boundaries` = every `valid_from` of a `tokens` price **and every `from` of `margins.yaml`**, sorted, so inside one
interval neither the price nor the margin changes. `long` = `input_tokens > long_from` per row (the smallest
`long_context_from` among prices; a row is re-checked against its own model's threshold in Python, and the RPC is
called with the per-model thresholds folded in, so a group never mixes long and short calls of one model). Python prices
each group with the same functions as a single row. Rounding differs from row-by-row by < 1 micro-dollar per row; a
test bounds it. Videos (hundreds a month) are read and priced one by one. Before v29 is applied: the same answer from
paged rows grouped in Python; a test proves both paths agree. Cached 60 s per month, cleared when a job ends.

A month is a calendar month in **UTC** (D2), as the top-bar percentage.

**Interface** (`..\hiru-ai-studio-interface`):

```
Settings
┌──────────────┬──────────────────────────────────────────────────────────────┐
│ Usage    ●   │ Usage                                   [ November 2026  ▾ ] │
│ Prices       │                                                              │
│              │ Total                                             $536.64    │
│              │ ┌──────────────────┬──────────────────┬──────────────────┐   │
│              │ │ Chat & decisions │ Image generation │ Video generation │   │
│              │ │ $42.02           │ $25.92           │ $458.90          │   │
│              │ └──────────────────┴──────────────────┴──────────────────┘   │
│              │ By production                                                │
│              │ Production       Chat & decisions   Image    Video    Total  │
│              │ Love Hour        $24.31            $17.28  $338.00  $379.59  │
│              │ …                                                            │
│              │ ⚠ 14 calls (some-model) have no price and are not counted    │
└──────────────┴──────────────────────────────────────────────────────────────┘
```

- Routes: `settings()` → `/settings` (redirects to Usage), `settingsUsage()` → `/settings/usage?month=`,
  `settingsPrices()` → `/settings/prices`; `/prices` redirects there.
- `app/(studio)/settings/layout.tsx`: header + left menu (Usage, Prices); not-found for a non-admin.
- `features/usage-report/`: `api.ts` (`GET /v1/admin/usage`), `types.ts`, `lib/map-usage.ts` (`formatUsd(micros)`,
  `—` for zero), `usage-summary.tsx`, `usage-table.tsx` (shadcn `Table`, production name links to it),
  `month-picker.tsx` (client, shadcn `Select`, navigates to `?month=`; server read, no polling).
- No words about margins or "list price" anywhere on the page. The only note: a missing price, as a `Chip`.
- Header: the avatar's **Prices** button becomes **Settings** (admins).
- Interface `CLAUDE.md`: Settings → Usage joins Scene ≈ $X and the price list as places money appears; "margins are
  never shown or sent".

### 3.6 Scene ≈ $X (the estimate)

`api/services/costs.py` keeps its logic; only the money underneath changes:
- spent: each item with its dated margin (§3.2);
- to finish: the next video at Omni 1.2's per-second rate for the shot's resolution (§3.3) x the video margin; frames
  and prompts from the production's recent median (already final, margins in) or the seeded flat estimate x margin;
  then `estimate.retry` on the to-finish part only.
The response stays `total_micros`, `designed`, `complete`.

## 4. Changes, file by file

**contracts**
- `src/libs/contracts/margins.yaml` (new, §3.1), included in the package data (`pyproject.toml`).
- `src/libs/contracts/costs.py`: `margins()`, `margin_at`, dated `with_margin`, `with_retry` from the file; `Price`
  gains `image_input_micros`, `cached_image_input_micros`, `long_context_from`, `long_*_micros`; kind `video_tokens`;
  `tokens_actual` (image split, long context); `video_actual` (tokens first, seconds fallback); `SEED_PRICES` (§3.3);
  `gpt-6.1-terra` moves from `UNSEEDED_PRICES` to `SEED_PRICES`; `MARGIN`, `RETRY_MARGIN` removed.
- `src/libs/contracts/usage_totals.py` (new): `MonthUsage`, `ProductionUsage`, `BucketTotals`, `price_groups`,
  `boundaries(prices, margins)`.

**meter**
- `src/libs/hiru_ai/adapters/images.py`: image / text / cached input from `input_tokens_details`.
- `src/libs/hiru_ai/core/usage.py`: `row()` takes `image_input_tokens` (default 0).
- `src/services/video_render/video_render/engine/omni.py` + `render.py`: `video_tokens`, `thought_tokens` in `usage`.
- `src/services/frame_render/.../store.py` and every store that inserts `token_usage`: pass the new column only when
  present (a row without it stays a valid row on a database before v29).

**schema** (`Database/upgrade_v28_to_v29.sql`, `Database/schema_v29.sql`): `token_usage.image_input_tokens`; `prices`
new columns and kind; `token_usage_totals` RPC (grants as `token_usage_since`); the price rows of §3.3 with their dates.

**api**: `repositories/__init__.py` + `supabase.py` (`token_totals`, `renders_between`, pre-v29 fallback);
`services/usage_totals.py`; `routers/admin_usage.py` + registration; `routers/costs.py` `PriceIn`/`PriceOut` new fields
and `video_tokens` validation; `tests/api/fakes.py`.

**interface**: §3.5 (`routes.ts`, `app/(studio)/settings/**`, `/prices` redirect, `features/usage-report/**`,
`features/prices/**` new price fields in the admin list, `account-avatar.tsx`, `CLAUDE.md`, `docs/ARCHITECTURE.md`).

## 5. Phases

| # | What | Done when |
|---|---|---|
| 0 | Confirm every rate of §3.3 on the official OpenAI and Google pricing pages (read-only); fix the table where they differ; write URL + date into each `note`. Read-only counts on the hosted project: `token_usage` rows a month, rows with no production, models with no price, the first `video_renders` row on `gemini-omni-1.2-flash` (the Omni row's date) | table confirmed, numbers in `IMPLEMENTED.md` |
| 1 | `margins.yaml` + loader + dated `with_margin` / `with_retry`. Tests: the file parses; a missing file / missing bucket / unsorted dates / 3 decimals / negative fail with a clear error; 12.5 % in basis points exactly; an item made before a new `from` keeps the old margin; scene-cost tests updated to the new margins and still green | tests green, `mypy` clean |
| 2 | Secrecy guard: a test walks every FastAPI response model and fails on a field named like `margin`, `cost`, `rate`, `markup`, `tokens` outside an allow-list (`/v1/prices` admin rates); a test that `margins.yaml` values never appear in any API response of the test world; logging of margins at DEBUG only | tests green |
| 3 | Prices + meter (§3.3, §3.4): `tokens_actual` image split and long context; `video_actual` by tokens then seconds; images adapter and Omni usage; tests with recorded provider `usage` shapes (OpenAI images `input_tokens_details`, Omni interaction `usage`); old rows without the new fields price as before | tests green |
| 4 | `contracts/usage_totals.py` + schema v29 + repo + RPC fallback. Tests: buckets; metered rows left out; reasoning not added twice; a price change and a margin change mid-month each split an interval; long calls apart; group vs row pricing < 1 micro per row on 1,000 rows; both paths equal | tests green |
| 5 | Service + router: admin 200 in the §3.5 shape; member 403; bad month 422; null production last; sort by total; cache cleared after a job | tests green |
| 6 | Interface: Settings layout and menu, Usage page, month picker, Prices moved + new price fields, redirect, header button. Tests: summary and table from a fixture; `formatUsd`; non-admin → not found; picker URL; no word "margin" in the rendered page | `npx next typegen && npm run check && npm run format:check` green |
| 7 | Docs: backend `CLAUDE.md` (margins file, the secrecy rule, scene cost margins changed), `docs/AI_CATALOG.md`, interface `CLAUDE.md` + `docs/ARCHITECTURE.md`, `IMPLEMENTED.md` | read through |
| 8 | **The person's**: apply v29 on the hosted project; open Settings → Usage for November; check a known scene's figure; compare the month with the OpenAI and Google consoles by eye (our total / 1.1-1.3 should be near the bills) | the person's yes |

Before finishing each backend phase: `ruff check src tests scripts`, `mypy`, `pytest -q`.

## 6. Decisions

- **D1 (open)**: who opens Settings → Usage. Recommended: **admins only** for now. Because the page shows final prices
  only, opening it to producers later (their own productions) is safe for the margins.
- **D2 (open)**: month in **UTC** (recommended) or Sri Lanka time.
- **D3 (open)**: a daily chart. Recommended: later.
- **D4 (decided, 2026-11-23)**: our meter first; the invoice check later (§8).
- **D5 (open)**: backdate the corrected prices so past work bills accurately (§3.3). Recommended: **yes**, by the
  migration only, each row's date stated in its `note`. The scene figures of existing scenes will move once.
- **D6 (open)**: the admin price list keeps showing provider rates (it is how an admin enters a new price). Together
  with Settings → Usage an admin could work the margins out. Recommended: **keep it** (admins are the studio); if
  admins must not know the margins either, the price list moves out of the interface and prices are added by migration
  only.
- **D7 (decided, 2026-11-23)**: margins llm 10 %, image 20 %, video 30 %, from 2026-01-01; estimate retry stays 20 %
  (confirm the retry).
- **D8 (open)**: change the margins by editing `margins.yaml` and redeploying (this plan). An admin screen to change
  them is later, if wanted; it would have to stay invisible to everyone else.

## 7. What the page will not show

- Calls cut off by a timeout that the provider still billed (no row).
- Batch / flex / priority tiers (none used today; a call on one would be priced at the standard rate).
- Storage, egress, Langfuse, hosting (fixed infrastructure).
- Lab and script runs that do not write to the production database.
- A deleted production's renders (deleted with it); its calls move to "No production".
- The top-bar percentage stays token-based; a dollar budget is a separate plan.

## 8. Later (not in this plan)

- **Invoice check**: OpenAI organisation Costs API (admin key) and Google billing export, per day, beside our provider
  cost on an admin-only line that is NOT on the Usage page (it would show the margin).
- Breakdown inside a production: episode, scene, agent, user, model.
- Separate image phases (first frame, board, face sheet, look sheet).
- Top-bar percentage from final prices against a dollar budget.
