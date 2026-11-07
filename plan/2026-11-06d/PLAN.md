# A scene's full production cost, beside "Recommend settings for all shots": plan

The person asked (2026-11-06): show, per scene, the full production cost: what the scene's breakdown has
already cost, and what it will cost to finish, with video generation at **actual cost + 10% margin**. It sits
next to the **Recommend settings for all shots** button in the scene panel's header
(`hiru-ai-studio-interface/src/features/production/components/scene-batch-actions.tsx`).

This plan **changes a fixed decision**. CLAUDE.md and PLAN.md §10 said "the UI shows no credits or costs". The person
changed that on 2026-11-06, for this feature only, with the answers in §2.

## 1. What we found

| Fact | Where |
|---|---|
| Every model call already writes a `token_usage` row: model, input, cached input, output and reasoning tokens, `production_id`, `job_id`. It has **no `scene_id`**. | `Database/schema_v14.sql` (`token_usage`), `hiru_ai/core/usage.py`, `api/services/ai.py` `UsageContext` |
| Scene-wide jobs put the scene in `jobs.request` (`{"scene_id": …}`): design, frames, prompts, Adam, David. `script_split` works on a whole episode, and Adam can plan "a few" scenes in one job. | `api/routers/production.py:423,534,625`, `api/routers/scenes.py:541,571,637` |
| Frames record their image tokens as ordinary `token_usage` rows (`frame_render.image`). | `hiru_ai/adapters/images.py` |
| A video render keeps `engine`, `model`, `spec` (resolution, duration_s, aspect) and a `usage` jsonb ("never shown"). One row per press; `takes` per press is in the settings. | `video_renders`, `contracts/video_gen.py` |
| What a shot WILL be rendered with is already code: `video_gen.resolve(production, shot, production_aspect, shot_seconds)` gives engine, model, resolution, duration and takes, with the shot's length as the fallback duration. | `contracts/video_gen.py:250` |
| The only prices in the repo are two copies of OpenAI list prices in scripts (`scripts/adam_cost.py`, `scripts/david_spike.py`). There is no video price anywhere. | — |
| `/v1/usage` returns a percentage only. | `api/routers/usage.py` |
| Schema v14 (video renders) is built and verified on the local stack, **not applied** to the hosted project. | `plan/2026-11-06c/IMPLEMENTED.md` |

## 2. Decisions

The person decided these on 2026-11-06:

1. **Who sees costs:** producer, director and admin. These are the roles that hold `RENDER_VIDEO`, the people who
   can spend. A new `Permission.VIEW_COSTS` in `contracts/roles.py` is given to exactly those roles. Everyone else
   sees no money anywhere, as before.
2. **Currency:** USD.
3. **Prices:** a table an admin can edit (`prices`), seeded with list prices. Each price has a `valid_from`, so a
   change applies to new work only and old spending keeps the price it was made at.

The person decided these on 2026-11-06 (second message):

4. **Margins, per kind of work:**
   - video generation: actual + **10%**
   - image generation (frames, reference sheets): actual + **5%**
   - text model calls (planning, design, prompts, the director): actual, no margin
5. **Retry margin:** once everything is priced, **+20%** for retries.
6. **The interface shows ONE figure**, the scene total. It shows no breakdown, no lines, no rates and no margins. The
   API sends the frontend only that total, so a breakdown cannot leak through the network tab either.

This plan takes the decisions below. The person can overturn any of them (§11):

7. **The retry margin applies to the "to finish" part only.** Work already done cannot be retried, and its cost is
   known: `total = spent + to_finish × 1.20` (D-B).
8. **"Actual" means metered usage × the list price at the time of the work.** Providers return no bill per call, so
   we price what we metered: tokens for model calls, image tokens for frames, rendered seconds for video. The scripts
   do the same today.
9. **`/v1/usage` stays a percentage.** This feature adds a cost per scene. It does not add a monthly bill.

## 3. In one picture

```
 Scene 4 header
 [Recommend settings for all shots] [Generate frames…] [Generate prompts…]   Scene ≈ $20.86

 Hover / title text, words only:  "Estimated cost to make this scene."
                                   + "Before recommended settings." when the shots are not designed yet
                                   + "Some prices are missing." when a price is missing

 How the server gets there (never sent to the browser):
   spent      = text calls (actual) + images × 1.05 + videos × 1.10                        e.g. $6.12
   to finish  = (videos × 1.10 + images × 1.05 + prompts (actual)) × 1.20                  e.g. $12.28 × 1.20
   total      = spent + to finish                                                          e.g. $20.86
```

## 4. Money rules: `contracts/costs.py` (pydantic + stdlib only)

- Money is an integer number of **micro-dollars** (`int`, 1 USD = 1,000,000). No float is ever summed. The
  interface rounds to cents only for display.
- `Price`: `kind` (`tokens` | `video_second` | `estimate`), match keys (`model_prefix` for tokens;
  `engine` + `model` + `resolution` for video), unit prices (`input`, `cached_input`, `output` per million tokens;
  `per_second` for video), `valid_from`.
- `price_for(kind, keys, at, prices)`: the price valid at time `at`. For tokens the longest model prefix wins, as in
  `adam_cost.py`. **A missing price is reported, never guessed.** The total carries a `missing` note ("no price
  for veo-3.1 at 1080p") and leaves that item out.
- The margins live here and nowhere else, as basis points so no float enters the money:
  - `MARGIN = {"text": 0, "image": 500, "video": 1000}` (5% and 10%)
  - `RETRY_MARGIN = 2000` (20%)
  - `with_margin(micros, kind) -> int` and `with_retry(micros) -> int` round half up.
- `kind_of(phase) -> "text" | "image"`: `frame_render.image` and the other image phases are `image`, everything else
  is `text`. A closed list, tested, so a new image phase cannot be priced as text by accident.
- `cost_tokens(row, prices) -> int`: one `token_usage` row at actual cost, then `with_margin(…, kind_of(row.phase))`.
  Reasoning tokens are counted as output tokens, as the provider bills them.
- `cost_render(render, prices) -> int`: rendered seconds × takes made × per_second, then
  `with_margin(…, "video")`.
- `estimate_shot_video(resolved: ResolvedSettings, prices) -> int`: duration_s × takes × per_second, then the video
  margin. It takes the output of `video_gen.resolve`, so the estimate uses the same settings the render would use.
- `scene_total(spent_items, to_finish_items) -> SceneTotal`: sums each part with its own margins first, then
  applies `with_retry` to the to-finish sum, once. `SceneTotal` holds the parts for tests and logs. Only `total`
  goes on the wire (§6).
- The `scripts/` copies of `PRICES` are replaced by a call to `costs`, which removes a second source of truth. The
  scripts report actual cost without margins: `costs.actual(...)`.

**Rules that must not drift:**
- Each margin is applied once, only in `with_margin` / `with_retry`. The retry margin is applied after the kind
  margins, to the estimate only.
- No breakdown leaves the server: the response model has no field for one.
- A cost is computed at read time from metered usage and the dated price list. Nothing stores a money figure, so a
  price fix corrects history only when its `valid_from` says so.
- A missing price is a note, never zero and never a guess.

## 5. Storage (one structural change, folded into the v14 pair while v14 is unapplied, else a v15 pair)

- **`prices`** table: `id`, `kind`, `model_prefix`, `engine`, `model`, `resolution`, `input_micros`,
  `cached_input_micros`, `output_micros` (per million tokens), `per_second_micros`, `valid_from`, `note`, `set_by`,
  `created_at`. It is seeded with OpenAI list prices (from `adam_cost.py`) and the Omni Flash / Veo 3.1 list prices
  per second and resolution. `scripts/video_probe.py --generate` confirms those against a real bill before they are
  trusted (Phase 0). RLS is enabled with an `is_admin()` read policy and no write policy. The API reads prices with
  the service role.
- **`token_usage.scene_id uuid null`** (references `scenes`, on delete set null) with an index
  `(scene_id, created_at)`.
  - Writers: `RunContext` already knows the scene in scope, and `UsageContext` gets the same. Every call made for
    one scene writes the scene. The director chat writes its scene when the chat is about one scene.
  - The upgrade backfills old rows from `jobs.request->>'scene_id'` where the job named exactly one scene.
- **Episode-wide work** (`script_split`, a multi-scene Adam job) has no single scene. Its rows keep
  `scene_id = null`. A scene's cost shows that work as one line, **"Share of episode breakdown"**, split by the
  scene's share of the episode's dialogue lines (§11, D-A).
- **Video renders** already carry `shot_id`, `spec` and `usage`. The only addition is that `usage` must record
  `seconds_rendered` and `takes_made`. The function fills these; they are already "tokens or seconds".
  `failed` and `refused` renders count only if the provider billed them. Phase 0 settles which ones it bills.
- pgTAP: `015_costs.test.sql` checks that `prices` has RLS on, admin read only, and no browser writes, and that
  `scene_id` has its index and is set to null when its scene is deleted.

## 6. API

- `GET /v1/productions/{pid}/scenes/{sid}/cost` → `SceneCost`, guarded by `require_permission(Permission.VIEW_COSTS)`.
  A production the caller cannot see answers 404. A member without the permission gets 403.
  - **The response is only:**
    `{currency: "USD", total_micros, designed: bool, complete: bool}`. `complete` is false when a price is missing.
    The parts below are computed in `services/costs.py`, logged at debug level, and never returned.
  - **spent**:
    - `breakdown`: planning, design and the director's work on the scene, from `token_usage` where `scene_id` is
      the scene.
    - `episode_share`: the scene's share of episode-wide rows.
    - `frames`: `frame_render.*` phases.
    - `prompts`.
    - `videos`: done and billed renders of the scene's shots, with margin.
  - **to_finish**:
    - `videos`: for each shot **without an accepted take**, `video_gen.resolve(...)` → `estimate_shot_video`.
      The response reports shots, takes, seconds and resolution.
    - `frames`: shots without a current accepted frame × this production's median cost per frame (the last 20
      `frame_render` items). With no history, the median across productions is used, and with none there, the
      seeded `estimate` price.
    - `prompts`: unlocked shots × the median cost per prompt, found the same way.
  - total = spent + `with_retry(to_finish)`.
- Admin: `GET /v1/prices`, `PUT /v1/prices` (adds a dated row and never edits one; audited like `usage.budget`).
- All reads go through a new `repos.costs` protocol (`api/repositories`) with a fake in `tests/api/fakes.py`.
  Routers never query Supabase.
- The math is a pure call on fetched rows, so a scene of 30 shots is one query per table. No N+1.

## 7. Interface (`hiru-ai-studio-interface`)

- `SceneCost` sits at the right of `SceneBatchActions`. It is plain text, "Scene ≈ $20.86", rounded to cents, with
  no popover, no lines, no rates and no margins. Its title text is words only (§3). It is rendered only when the
  person has `VIEW_COSTS` (from `/v1/me`'s permissions for the production). A 403 hides it silently.
- It reloads when any batch action finishes (`router.refresh()` already runs). Pressing "Recommend settings for all
  shots" changes durations and lengths, so the figure moves with it.
- There is a mock in the mock-data seam, and tests for the label, the hidden state, and the before-design and
  missing-price notes. One test asserts that the rendered text contains only one money figure.
- Admin settings: a plain prices page (list plus "add a price from date").

## 8. Phases

### Phase 0: prices (the person's)
- Collect the list prices: OpenAI (current models in `OPENAI__MODEL_*`), Omni Flash and Veo 3.1 per second at
  360p, 720p and 1080p, with and without audio if they differ.
- `scripts/video_probe.py --generate --yes` (it costs money) is run against one real bill to confirm "seconds ×
  price" and whether failed or refused renders are billed. The results go in `IMPLEMENTED.md`.

### Phase 1: contracts (offline)
- `contracts/costs.py` + `tests/contracts/test_costs.py`:
  - micro-dollar math, longest prefix, dated prices
  - 5% on images, 10% on video, 0 on text, each exactly once
  - 20% retry on the to-finish part only, after the kind margins
  - missing price → incomplete
  - an estimate that equals `resolve()`'s seconds × takes
- `Permission.VIEW_COSTS` in `contracts/roles.py` and `tests/contracts/test_roles.py`.
- `scripts/adam_cost.py` and `scripts/david_spike.py` use `costs`.

### Phase 2: storage (local stack)
- A migration (`npx supabase migration new costs`), `prices` + seed, `token_usage.scene_id` + backfill, and pgTAP.
- Fold into `schema_v14.sql` / `upgrade_v13_to_v14.sql` if v14 is still unapplied, else a v15 pair. Verify with the
  three-way dump.

### Phase 3: writers (offline)
- `RunContext` and `UsageContext` write `scene_id`. `video_render` records `seconds_rendered` and `takes_made`.
- `tests/parity` stays green. Tests cover the legacy engine and the graph engine.

### Phase 4: API (offline)
- `repos.costs`, `services/costs.py`, `routers/costs.py`, the prices routes, and `tests/api/test_costs.py`:
  - 404, 403, a viewer sees nothing
  - the response has only the four fields
  - a scene with no work
  - an episode share
  - a missing price
  - before design and after design
  - an accepted take leaves the estimate

### Phase 5: interface (mocks, then localhost)
- The one-figure `SceneCost`, the admin prices page, and tests. Then a look on localhost against the hosted dev
  DB, which is the person's to run because it reads real usage.

### Docs
- CLAUDE.md: "The UI shows no credits or costs" becomes "No costs in the interface **except** a scene's cost for
  `VIEW_COSTS` (plan/2026-11-06d); `/v1/usage` stays a percentage". Also update PLAN.md §10 and §14, and the memory
  note.

## 9. What this plan does not do

- No production-wide or episode-wide total. One could sum scenes later, using the same `SceneCost`.
- No budget, alert or stop on spending.
- No margin on model calls. No invoicing or export.
- No breakdown anywhere in the interface. Retries are covered by the flat 20%, not by counting retakes.
- It does not change `/v1/usage`.

## 10. Risks

- **Video list prices may not equal the bill** (audio, rounding to whole seconds, refused renders). Phase 0 checks
  one real bill. Each price row has a `note` for its source.
- **Old rows without a scene.** The backfill covers single-scene jobs. Chat and episode work before Phase 3 show up
  as "not tied to a scene" in `notes`.
- **The estimate moves.** Durations change after "Recommend settings for all shots". The before-design note and the
  refresh handle it.
- **People read the figure as a quote.** The "≈" and the title text say it is an estimate.

## 11. Decisions for the person

- **D-A Episode-wide work:** share it by the scene's dialogue lines (proposed), by shot count, or don't show it on
  a scene.
- **D-B What the 20% retry margin covers:** only the to-finish estimate (proposed: spent work is known and cannot be
  retried), or the whole total.
- **D-C Failed renders:** count them only when the provider bills them (proposed, settled in Phase 0), or always.
- **D-D The seeded prices** (Phase 0) and the go-ahead for the live check on localhost.
